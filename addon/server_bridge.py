import bpy
import json
import struct
import threading
import socket
import os
import traceback
from pathlib import Path

from .handlers import scene, polyhaven, sketchfab, hyper3d, hunyuan3d, trellis2
from .handlers import ambientcg, polypizza, smithsonian3d
from .handlers import nodes, modifiers, camera, collections, io as io_handler
from .handlers import objects, mesh_ops, materials, uv, bake, lod
from .handlers import rigging, animation, physics, scene_tools, volumes
from .handlers import selection
from .handlers import procedural
from .handlers import perception, file_ops, viewport, lights, world
from .handlers import snapshots, render_region
from .handlers import hierarchy, drivers, custom_props, curves, particles

# Discovery directory — shared with MCP server
SERVERS_DIR = Path.home() / ".blenderweave" / "servers"


def discover_servers():
    """Scan for available MCP servers. Returns list of (server_id, meta_dict)."""
    servers = []
    if not SERVERS_DIR.exists():
        return servers
    for meta_file in SERVERS_DIR.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text())
            pid = meta.get("pid")
            if pid and _pid_alive(pid):
                sock_file = meta_file.with_suffix(".sock")
                if sock_file.exists():
                    servers.append((meta_file.stem, meta))
        except Exception:
            pass
    # Sort by start time (newest first)
    servers.sort(key=lambda s: s[1].get("started", ""), reverse=True)
    return servers


def _pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _server_label(meta: dict) -> str:
    """Human-readable label from server metadata: 'project_name (HH:MM)'."""
    cwd = meta.get("cwd", "")
    name = Path(cwd).name if cwd else "unknown"
    started = meta.get("started", "")
    time_str = ""
    if started:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(started)
            time_str = f" ({dt.strftime('%H:%M')})"
        except Exception:
            pass
    return f"{name}{time_str}"


class BlenderWeaveClient:
    """Unix socket client that discovers and connects to MCP servers.

    Scans ~/.blenderweave/servers/ for available MCP servers.
    Auto-connects if exactly one server found, or connects to a specified one.
    Auto-reconnects on connection drop.
    """

    # Connection states
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"

    def __init__(self, server_id=None):
        self.server_id = server_id  # None = auto-discover
        self.server_label = None    # Human-readable label for UI
        self.state = self.DISCONNECTED
        self.socket = None
        self._reader_thread = None
        self._reconnect_timer = None
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        """Start the client — attempt to connect and begin auto-reconnect loop."""
        if self._running:
            return
        self._running = True
        self._try_connect()

    def stop(self):
        """Stop the client and all background threads."""
        self._running = False
        self._cancel_reconnect_timer()
        with self._lock:
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
        self.state = self.DISCONNECTED
        self.server_label = None
        print("BlenderWeave client stopped")

    def _try_connect(self):
        """Discover a server and connect via unix socket."""
        if not self._running:
            return
        self.state = self.CONNECTING

        # Find the server to connect to
        socket_path = None
        if self.server_id:
            # Specific server requested
            socket_path = SERVERS_DIR / f"{self.server_id}.sock"
            meta_path = SERVERS_DIR / f"{self.server_id}.json"
            if not socket_path.exists():
                self.state = self.DISCONNECTED
                self._schedule_reconnect()
                return
            try:
                meta = json.loads(meta_path.read_text())
                self.server_label = _server_label(meta)
            except Exception:
                self.server_label = self.server_id
        else:
            # Auto-discover
            servers = discover_servers()
            if not servers:
                self.state = self.DISCONNECTED
                self._schedule_reconnect()
                return
            # Connect to the most recent server
            sid, meta = servers[0]
            self.server_id = sid
            self.server_label = _server_label(meta)
            socket_path = SERVERS_DIR / f"{sid}.sock"

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(str(socket_path))
            sock.settimeout(None)
            with self._lock:
                self.socket = sock
            self.state = self.CONNECTED
            print(f"BlenderWeave connected to {self.server_label}")
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
        except (ConnectionRefusedError, OSError, socket.timeout) as e:
            self.state = self.DISCONNECTED
            print(f"BlenderWeave connection failed: {e} — retrying in 3s")
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        """Schedule a reconnect attempt via bpy.app.timers."""
        if not self._running:
            return
        self._cancel_reconnect_timer()

        def reconnect_callback():
            if self._running and self.state == self.DISCONNECTED:
                self._try_connect()
            return None  # Don't repeat — we reschedule on failure
        try:
            bpy.app.timers.register(reconnect_callback, first_interval=3.0)
            self._reconnect_timer = reconnect_callback
        except Exception:
            pass

    def _cancel_reconnect_timer(self):
        """Cancel any pending reconnect timer."""
        if self._reconnect_timer:
            try:
                if bpy.app.timers.is_registered(self._reconnect_timer):
                    bpy.app.timers.unregister(self._reconnect_timer)
            except Exception:
                pass
            self._reconnect_timer = None

    def _on_disconnect(self):
        """Handle connection drop — clean up and schedule reconnect."""
        with self._lock:
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
        self.state = self.DISCONNECTED
        print("BlenderWeave disconnected — will reconnect")
        if self._running:
            self._schedule_reconnect()

    @staticmethod
    def _recv_exact(sock, n):
        """Read exactly n bytes from sock."""
        buf = b''
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Connection closed while reading")
            buf += chunk
        return buf

    @staticmethod
    def _send_framed(sock, payload_bytes):
        """Send a length-prefixed frame: 4-byte big-endian length + payload."""
        header = struct.pack('>I', len(payload_bytes))
        sock.sendall(header + payload_bytes)

    def _reader_loop(self):
        """Read commands from the MCP server, execute in Blender's main thread."""
        with self._lock:
            sock = self.socket
        if not sock:
            return

        try:
            while self._running and self.state == self.CONNECTED:
                try:
                    header = self._recv_exact(sock, 4)
                    msg_len = struct.unpack('>I', header)[0]
                    data = self._recv_exact(sock, msg_len)
                    command = json.loads(data.decode('utf-8'))

                    # Execute in Blender's main thread via timer
                    def execute_wrapper(cmd=command, s=sock):
                        try:
                            response = self.execute_command(cmd)
                            response_bytes = json.dumps(response).encode('utf-8')
                            try:
                                self._send_framed(s, response_bytes)
                            except Exception:
                                print("Failed to send response — client disconnected")
                        except Exception as e:
                            print(f"Error executing command: {e}")
                            traceback.print_exc()
                            try:
                                error_response = {"status": "error", "message": str(e)}
                                self._send_framed(s, json.dumps(error_response).encode('utf-8'))
                            except Exception:
                                pass
                        return None

                    bpy.app.timers.register(execute_wrapper, first_interval=0.0)
                except ConnectionError:
                    print("MCP server disconnected")
                    break
                except Exception as e:
                    print(f"Error in reader loop: {e}")
                    break
        except Exception as e:
            print(f"Reader loop error: {e}")
        finally:
            self._on_disconnect()

    def execute_command(self, command):
        try:
            return self._execute_command_internal(command)
        except Exception as e:
            print(f"Error executing command: {e}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _build_handlers(self):
        """Build the full handler dispatch dict."""
        handlers = {
            "get_scene_info": scene.get_scene_info,
            "get_object_info": scene.get_object_info,
            "get_viewport_screenshot": scene.get_viewport_screenshot,
            "execute_code": scene.execute_code,
            "get_polyhaven_status": polyhaven.get_polyhaven_status,
            "get_hyper3d_status": hyper3d.get_hyper3d_status,
            "get_sketchfab_status": sketchfab.get_sketchfab_status,
            "get_hunyuan3d_status": hunyuan3d.get_hunyuan3d_status,
            "get_trellis2_status": trellis2.get_trellis2_status,
            # New structured tools
            "build_node_graph": nodes.build_node_graph,
            "get_node_graph": nodes.get_node_graph,
            "list_node_types": nodes.list_node_types,
            "modify_object": modifiers.modify_object,
            "set_camera": camera.set_camera,
            "render_scene": camera.render_scene,
            "poll_render_job": camera.poll_render_job,
            "camera_walkthrough": camera.camera_walkthrough,
            "manage_collections": collections.manage_collections,
            "import_model": io_handler.import_model,
            "export_model": io_handler.export_model,
            "set_keyframe": scene.set_keyframe,
            "analyze_scene": scene.analyze_scene,
            # Object CRUD
            "create_object": objects.create_object,
            "transform_object": objects.transform_object,
            "duplicate_object": objects.duplicate_object,
            "delete_object": objects.delete_object,
            # Mesh operations
            "mesh_operation": mesh_ops.mesh_operation,
            # Materials
            "manage_materials": materials.manage_materials,
            # UV mapping
            "uv_operation": uv.uv_operation,
            # Texture baking
            "bake_textures": bake.bake_textures,
            # LOD & collision
            "generate_lod_chain": lod.generate_lod_chain,
            "generate_collision_mesh": lod.generate_collision_mesh,
            # Rigging
            "manage_armature": rigging.manage_armature,
            "manage_weights": rigging.manage_weights,
            "manage_shape_keys": rigging.manage_shape_keys,
            # Animation
            "manage_actions": animation.manage_actions,
            "manage_nla": animation.manage_nla,
            # Physics & constraints
            "manage_physics": physics.manage_physics,
            "manage_constraints": physics.manage_constraints,
            # Viewport & render
            "set_viewport_shading": scene_tools.set_viewport_shading,
            "configure_render_settings": scene_tools.configure_render_settings,
            # Volume grids
            "volume_operation": volumes.volume_operation,
            # Selection
            "manage_selection": selection.manage_selection,
            # Batch operations
            "batch_transform": objects.batch_transform,
            # Procedural geometry
            "procedural_generate": procedural.procedural_generate,
            # Perception (replaces telemetry)
            "get_scene_perception": perception.get_scene_perception,
            "get_viewport_thumbnail": perception.get_viewport_thumbnail,
            "get_scene_delta": perception.get_scene_delta,
            # Hierarchy
            "manage_hierarchy": hierarchy.manage_hierarchy,
            # Drivers
            "manage_drivers": drivers.manage_drivers,
            # Custom properties
            "manage_custom_properties": custom_props.manage_custom_properties,
            # Curves
            "manage_curves": curves.manage_curves,
            # Particles
            "manage_particles": particles.manage_particles,
            # File operations
            "save_file": file_ops.save_file,
            "open_file": file_ops.open_file,
            "undo": file_ops.undo,
            "redo": file_ops.redo,
            "set_frame": file_ops.set_frame,
            # Viewport control
            "set_viewport": viewport.set_viewport,
            # Light management
            "manage_lights": lights.manage_lights,
            # World/environment
            "manage_world": world.manage_world,
            # Scene snapshots
            "manage_snapshots": snapshots.manage_snapshots,
            # Render region
            "render_region": render_region.render_region,
        }

        # Poly Haven handlers — always registered; property checked inside handler
        # so addon reload doesn't lose them (gives clear error vs "unknown command")
        handlers.update({
            "get_polyhaven_categories": polyhaven.get_polyhaven_categories,
            "search_polyhaven_assets": polyhaven.search_polyhaven_assets,
            "download_polyhaven_asset": polyhaven.download_polyhaven_asset,
            "set_texture": polyhaven.set_texture,
        })

        # AmbientCG handlers
        handlers.update({
            "get_ambientcg_status": ambientcg.get_ambientcg_status,
            "search_ambientcg_assets": ambientcg.search_ambientcg_assets,
            "download_ambientcg_asset": ambientcg.download_ambientcg_asset,
        })

        if bpy.context.scene.blenderweave_use_hyper3d:
            handlers.update({
                "create_rodin_job": hyper3d.create_rodin_job,
                "poll_rodin_job_status": hyper3d.poll_rodin_job_status,
                "import_generated_asset": hyper3d.import_generated_asset,
            })

        if bpy.context.scene.blenderweave_use_sketchfab:
            handlers.update({
                "search_sketchfab_models": sketchfab.search_sketchfab_models,
                "get_sketchfab_model_preview": sketchfab.get_sketchfab_model_preview,
                "download_sketchfab_model": sketchfab.download_sketchfab_model,
            })

        if bpy.context.scene.blenderweave_use_hunyuan3d:
            handlers.update({
                "create_hunyuan_job": hunyuan3d.create_hunyuan_job,
                "poll_hunyuan_job_status": hunyuan3d.poll_hunyuan_job_status,
                "import_generated_asset_hunyuan": hunyuan3d.import_generated_asset_hunyuan,
            })

        if bpy.context.scene.blenderweave_use_trellis2:
            handlers.update({
                "create_trellis2_job": trellis2.create_trellis2_job,
                "poll_trellis2_job": trellis2.poll_trellis2_job,
            })

        # Poly Pizza handlers — always registered; status checked inside handler
        handlers.update({
            "get_polypizza_status": polypizza.get_polypizza_status,
            "search_polypizza_models": polypizza.search_polypizza_models,
            "download_polypizza_model": polypizza.download_polypizza_model,
        })

        # Smithsonian 3D handlers — always registered; status checked inside handler
        handlers.update({
            "get_smithsonian_status": smithsonian3d.get_smithsonian_status,
            "search_smithsonian_models": smithsonian3d.search_smithsonian_models,
            "download_smithsonian_model": smithsonian3d.download_smithsonian_model,
        })

        # Spatial power tools
        from .handlers import assembly
        handlers.update({
            "place_relative": objects.place_relative,
            "create_assembly": assembly.create_assembly,
        })

        return handlers

    def _execute_command_internal(self, command):
        cmd_type = command.get("type")
        params = command.get("params", {})

        # Health ping — lightweight, no handler dict lookup needed
        if cmd_type == "ping":
            return {"status": "success", "result": {
                "pong": True,
                "blender_version": ".".join(str(v) for v in bpy.app.version),
            }}

        # Status check (always available, used for health ping)
        if cmd_type == "get_polyhaven_status":
            return {"status": "success", "result": polyhaven.get_polyhaven_status()}

        # Batch execute — run multiple commands in one round-trip
        if cmd_type == "batch_execute":
            handlers = self._build_handlers()
            results = []
            bpy.ops.ed.undo_push(message="batch_execute start")
            for cmd in params.get("commands", []):
                tool = cmd.get("tool")
                h = handlers.get(tool)
                if not h:
                    results.append({"error": f"Unknown tool: {tool}"})
                    continue
                try:
                    results.append(h(**cmd.get("params", {})))
                except Exception as e:
                    results.append({"error": str(e)})
            bpy.ops.ed.undo_push(message="batch_execute end")
            # Perception runs once via normal post-command logic below
            result = {"results": results, "count": len(results)}
            # Fall through to perception attachment
            cmd_type = "batch_execute"
            # Skip handler lookup, go straight to perception
            return self._attach_perception_and_return(cmd_type, result)

        handlers = self._build_handlers()
        handler = handlers.get(cmd_type)
        if handler:
            try:
                print(f"Executing handler for {cmd_type}")
                result = handler(**params)
                print(f"Handler execution complete")

                return self._attach_perception_and_return(cmd_type, result)
            except Exception as e:
                print(f"Error in handler: {e}")
                traceback.print_exc()
                return {"status": "error", "message": str(e)}
        else:
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}


    # Commands that don't trigger auto-perception
    READ_ONLY = {
        # Query/status
        "get_scene_info", "get_object_info", "get_viewport_screenshot",
        "analyze_scene", "list_node_types", "get_node_graph",
        "get_polyhaven_status", "get_hyper3d_status",
        "get_sketchfab_status", "get_hunyuan3d_status",
        "get_trellis2_status",
        "get_scene_perception", "get_viewport_thumbnail",
        "get_scene_delta", "manage_snapshots", "undo_history",
        # Poll/generation start
        "poll_hunyuan_job_status", "poll_trellis2_job",
        "poll_rodin_job_status",
        "create_trellis2_job", "create_hunyuan_job", "create_rodin_job",
        # Search/browse
        "get_polyhaven_categories", "search_polyhaven_assets",
        "search_sketchfab_models", "get_sketchfab_model_preview",
        # AmbientCG / Poly Pizza / Smithsonian search+status
        "get_ambientcg_status", "search_ambientcg_assets",
        "get_polypizza_status", "search_polypizza_models",
        "get_smithsonian_status", "search_smithsonian_models",
        # Render (don't render to perceive a render)
        "render_scene", "render_region",
        # Settings/metadata/viewport
        "save_file", "open_file", "undo", "redo", "set_frame",
        "configure_render_settings", "set_viewport_shading", "set_viewport",
        "manage_custom_properties", "manage_drivers",
    }

    def _attach_perception_and_return(self, cmd_type, result):
        """Attach auto-perception and delta to result, return success response."""
        if cmd_type not in self.READ_ONLY:
            try:
                ctx_scene = bpy.context.scene
                prev_perc = getattr(perception, '_last_perception', None)

                # Perception mode determines what's included
                mode = getattr(ctx_scene, "blenderweave_perception_mode", "SMART")

                if mode == "COMPACT":
                    # Minimal: OBJ + DELTA + VERIFY only
                    perc = perception.get_scene_perception(
                        include_spatial=False,
                        include_lighting=False,
                        include_materials=False,
                        include_constraints=True,  # spatial facts always useful
                        include_shadows=False,
                        include_ray_grid=False,
                        include_multi_view=False,
                        include_hierarchy=False,
                        include_physics=False,
                        include_animation=False,
                        include_micro_render=False,
                    )
                elif mode == "SMART":
                    # Full perception minus physics/animation, radius-filtered
                    # Auto-tune perception radius from scene AABB diagonal
                    smart_radius = 8.0
                    try:
                        import mathutils
                        scene_min = mathutils.Vector((float('inf'),) * 3)
                        scene_max = mathutils.Vector((float('-inf'),) * 3)
                        found_mesh = False
                        for obj in bpy.context.scene.objects:
                            if obj.type == 'MESH' and obj.visible_get():
                                for corner in obj.bound_box:
                                    world_pt = obj.matrix_world @ mathutils.Vector(corner)
                                    scene_min = mathutils.Vector((min(scene_min[i], world_pt[i]) for i in range(3)))
                                    scene_max = mathutils.Vector((max(scene_max[i], world_pt[i]) for i in range(3)))
                                found_mesh = True
                        if found_mesh:
                            diag = (scene_max - scene_min).length
                            smart_radius = max(8.0, min(diag * 0.6, 100.0))
                    except Exception:
                        pass
                    # Use panel radius if set, else auto-tuned
                    panel_radius = getattr(ctx_scene, "blenderweave_perception_radius", 15.0)
                    radius = panel_radius if panel_radius > 0 else smart_radius
                    perc = perception.get_scene_perception(
                        include_spatial=True,
                        include_lighting=True,
                        include_materials=True,
                        include_constraints=True,
                        include_shadows=True,
                        include_ray_grid=True,
                        include_multi_view=True,
                        include_hierarchy=True,
                        include_physics=False,
                        include_animation=False,
                        include_micro_render=True,
                        perception_radius=radius,
                    )
                else:
                    # Full: respect individual toggles
                    perc = perception.get_scene_perception(
                        include_spatial=getattr(ctx_scene, "blenderweave_fb_spatial", True),
                        include_lighting=getattr(ctx_scene, "blenderweave_fb_lighting", True),
                        include_materials=getattr(ctx_scene, "blenderweave_fb_materials", True),
                        include_constraints=getattr(ctx_scene, "blenderweave_fb_constraints", True),
                        include_shadows=getattr(ctx_scene, "blenderweave_fb_shadows", True),
                        include_ray_grid=getattr(ctx_scene, "blenderweave_fb_ray_grid", True),
                        include_multi_view=getattr(ctx_scene, "blenderweave_fb_multi_view", True),
                        include_hierarchy=getattr(ctx_scene, "blenderweave_fb_hierarchy", True),
                        include_physics=getattr(ctx_scene, "blenderweave_fb_physics", True),
                        include_animation=getattr(ctx_scene, "blenderweave_fb_animation", True),
                        include_micro_render=getattr(ctx_scene, "blenderweave_fb_micro_render", True),
                    )
                if isinstance(result, dict) and not perc.get("error"):
                    result["_auto_perception"] = perc
                    if prev_perc and not prev_perc.get("error"):
                        delta = _compute_auto_delta(prev_perc, perc)
                        if delta:
                            result["_auto_delta"] = delta
            except Exception as fb_err:
                print(f"Auto-feedback failed: {fb_err}")
        return {"status": "success", "result": result}


def _compute_auto_delta(prev, curr):
    """Compute delta between two perception dicts.

    Tracks: object position/scale/rotation/coverage/material, light energy/color/position,
    material add/remove/appearance changes.
    """
    deltas = []

    # Build object lookup by name (MESH only for meaningful comparison)
    prev_objs = {o["name"]: o for o in prev.get("visible_objects", []) if o.get("type") in ("MESH", None)}
    curr_objs = {o["name"]: o for o in curr.get("visible_objects", []) if o.get("type") in ("MESH", None)}

    # Added/removed objects
    for name in sorted(set(curr_objs) - set(prev_objs)):
        deltas.append(f"{name} added")
    for name in sorted(set(prev_objs) - set(curr_objs)):
        deltas.append(f"{name} removed")

    # Changed objects
    for name in sorted(set(prev_objs) & set(curr_objs)):
        po, co = prev_objs[name], curr_objs[name]
        changes = []

        # Position
        p_wc = po.get("world_center", [0, 0, 0])
        c_wc = co.get("world_center", [0, 0, 0])
        dx, dy, dz = c_wc[0] - p_wc[0], c_wc[1] - p_wc[1], c_wc[2] - p_wc[2]
        if (dx * dx + dy * dy + dz * dz) ** 0.5 > 0.001:
            dirs = []
            if abs(dx) > 0.001: dirs.append(f"{'+' if dx > 0 else '-'}X")
            if abs(dy) > 0.001: dirs.append(f"{'+' if dy > 0 else '-'}Y")
            if abs(dz) > 0.001: dirs.append(f"{'+' if dz > 0 else '-'}Z")
            changes.append(f"moved [{dx:.2f},{dy:.2f},{dz:.2f}] ({','.join(dirs)})")

        # Coverage change (object resized or camera-relative change)
        p_cov = po.get("screen_coverage_pct", 0)
        c_cov = co.get("screen_coverage_pct", 0)
        if abs(p_cov - c_cov) > 1.0:
            changes.append(f"coverage {p_cov:.0f}%→{c_cov:.0f}%")

        # Material swap
        p_mat = (po.get("material") or {}).get("name", "")
        c_mat = (co.get("material") or {}).get("name", "")
        if p_mat and c_mat and p_mat != c_mat:
            changes.append(f"material {p_mat}→{c_mat}")

        # Material property changes (roughness, metallic, color)
        if p_mat == c_mat and p_mat:
            pm, cm = po.get("material", {}), co.get("material", {})
            for prop in ("roughness", "metallic", "transmission", "emission_strength"):
                pv = pm.get(prop)
                cv = cm.get(prop)
                if pv is not None and cv is not None and abs(pv - cv) > 0.01:
                    changes.append(f"{prop} {pv}→{cv}")
            # Base color
            pbc = pm.get("base_color")
            cbc = cm.get("base_color")
            if isinstance(pbc, list) and isinstance(cbc, list) and len(pbc) >= 3 and len(cbc) >= 3:
                if sum(abs(pbc[i] - cbc[i]) for i in range(3)) > 0.03:
                    changes.append("color changed")

        if changes:
            deltas.append(f"{name} {', '.join(changes)}")

    # Light changes
    prev_lights = {l["name"]: l for l in prev.get("lights", [])}
    curr_lights = {l["name"]: l for l in curr.get("lights", [])}
    for name in sorted(set(curr_lights) - set(prev_lights)):
        deltas.append(f"light {name} added")
    for name in sorted(set(prev_lights) - set(curr_lights)):
        deltas.append(f"light {name} removed")
    for name in sorted(set(prev_lights) & set(curr_lights)):
        pl, cl = prev_lights[name], curr_lights[name]
        changes = []
        # Energy
        pe, ce = pl.get("energy", 0), cl.get("energy", 0)
        if abs(pe - ce) > 0.1:
            changes.append(f"energy {pe}→{ce}")
        # Color
        pc, cc = pl.get("color", [1, 1, 1]), cl.get("color", [1, 1, 1])
        if sum(abs(pc[i] - cc[i]) for i in range(min(len(pc), len(cc), 3))) > 0.03:
            changes.append(f"color [{cc[0]},{cc[1]},{cc[2]}]")
        # Position
        pp, cp = pl.get("location", [0, 0, 0]), cl.get("location", [0, 0, 0])
        if sum(abs(pp[i] - cp[i]) for i in range(3)) > 0.01:
            changes.append("moved")
        if changes:
            deltas.append(f"light {name} {', '.join(changes)}")

    # Material add/remove + appearance changes
    prev_mats = {m["name"]: m for m in prev.get("material_predictions", [])}
    curr_mats = {m["name"]: m for m in curr.get("material_predictions", [])}
    for name in sorted(set(curr_mats) - set(prev_mats)):
        deltas.append(f"material {name} added")
    for name in sorted(set(prev_mats) - set(curr_mats)):
        deltas.append(f"material {name} removed")
    for name in sorted(set(prev_mats) & set(curr_mats)):
        pa = prev_mats[name].get("appearance", "")
        ca = curr_mats[name].get("appearance", "")
        if pa != ca:
            deltas.append(f"material {name} appearance {pa}→{ca}")

    return deltas
