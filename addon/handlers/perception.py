"""Scene perception engine — full 3D spatial intelligence without screenshots.

Replaces telemetry.py. Provides depth-sorted objects, spatial relationships,
light-surface analysis, material predictions, constraint checks, ray grid,
shadow analysis, multi-view ray grids, and enhanced scene delta.
100-200ms per call. Auto-attached to every modifying command.
"""
import bpy
import traceback
import time
import tempfile
import os
import uuid
import base64
import math

# Cache for delta diffing
_last_perception = None

# Cache for micro-render (keyed on scene hash)

# Pre-transform state cache for VERIFY system
_verify_pre_state = None

_object_cache = {}
_material_cache = {}


def _matrix_hash(obj):
    """Fast hash of matrix_world for cache invalidation."""
    m = obj.matrix_world
    # Hash position + rotation columns (12 floats), rounded to avoid float jitter
    return hash(tuple(round(m[r][c], 4) for r in range(3) for c in range(4)))


def _material_fingerprint(mat):
    """Compute fingerprint of Principled BSDF inputs for cache invalidation."""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    import hashlib
    h = hashlib.md5()
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            for inp in node.inputs:
                if inp.links:
                    # Track linked node + socket
                    for link in inp.links:
                        h.update(f"{link.from_node.name}:{link.from_socket.name}".encode())
                else:
                    try:
                        val = tuple(inp.default_value) if hasattr(inp.default_value, '__iter__') else (inp.default_value,)
                        h.update(f"{inp.name}:{val}".encode())
                    except Exception:
                        pass
            break
    return h.hexdigest()


def get_scene_perception(include_spatial=True, include_lighting=True,
                         include_materials=True, include_constraints=True,
                         include_shadows=True, include_ray_grid=True,
                         include_multi_view=True, include_hierarchy=True,
                         include_physics=True, include_animation=True,
                         include_micro_render=True,
                         focus_point=None, perception_radius=None):
    """Full scene perception — structured 3D spatial intelligence.

    Proximity-based: objects are filtered and LOD-tiered by distance from
    focus_point. Closer objects get more detail.

    Args:
        focus_point: [x,y,z] world-space focus. Defaults to camera position.
        perception_radius: Max distance in meters. Objects beyond this are
            counted but not detailed. Defaults to None (include all).
            Recommended: 5-10m for interiors, 20-50m for exteriors.

    LOD tiers (when perception_radius is set):
        NEAR  (0 to radius*0.4):  Full detail — all fields, REL, SPATIAL
        MID   (radius*0.4 to 0.8): Summary — pos, dim, top, src, rot, material name
        FAR   (radius*0.8 to 1.0): Minimal — name, pos, dim only
        OUT   (beyond radius):     Count only
    """
    try:
        scene = bpy.context.scene
        depsgraph = bpy.context.evaluated_depsgraph_get()

        result = {
            "timestamp": time.time(),
            "frame": scene.frame_current,
            "render_engine": scene.render.engine,
        }

        # Camera info
        cam = scene.camera
        if cam:
            cam_data = {
                "name": cam.name,
                "location": [round(v, 3) for v in cam.location],
                "focal_length": round(cam.data.lens, 1) if cam.data else None,
            }
            # Compute FOV from focal length + sensor width (M1)
            if cam.data and cam.data.lens > 0:
                sensor_w = cam.data.sensor_width
                fov_rad = 2 * math.atan(sensor_w / (2 * cam.data.lens))
                cam_data["fov"] = round(math.degrees(fov_rad), 1)
            result["camera"] = cam_data

        # ── Core: Gather visible objects with depth ──
        from bpy_extras.object_utils import world_to_camera_view
        import mathutils

        # ── Focus point + proximity radius ──
        if focus_point is not None:
            focus = mathutils.Vector(focus_point)
        elif cam:
            focus = cam.matrix_world.translation.copy()
        else:
            focus = mathutils.Vector((0, 0, 0))

        # LOD tier boundaries (fractions of perception_radius)
        use_proximity = perception_radius is not None and perception_radius > 0
        if use_proximity:
            near_dist = perception_radius * 0.4
            mid_dist = perception_radius * 0.8
            far_dist = perception_radius
        else:
            near_dist = mid_dist = far_dist = float('inf')

        out_count = 0  # objects beyond radius

        result["focus"] = [round(focus[i], 2) for i in range(3)]
        if use_proximity:
            result["perception_radius"] = perception_radius

        visible_objects = []
        lights = []
        mesh_objects = []  # for spatial/lighting analysis

        # ══════════════════════════════════════════════════════════════
        # PHASE 1: Quick distance pre-filter + light collection
        # Uses matrix_world.translation only (1 vector read, no AABB).
        # Assigns LOD tier. Objects beyond radius are counted and skipped.
        # ══════════════════════════════════════════════════════════════
        from ._utils import compute_world_aabb
        try:
            from ._utils import Octree
        except ImportError:
            Octree = None
        try:
            from ._utils import SpatialGrid
        except ImportError:
            SpatialGrid = None

        # Build spatial index for pairwise analysis (shared across all subsystems)
        # Prefer Octree (adaptive) over SpatialGrid (uniform) when available
        if Octree:
            # Pre-compute bounds from all visible mesh objects for Octree init
            _scene_positions = []
            for _obj in scene.objects:
                if _obj.visible_get() and _obj.type == 'MESH':
                    _scene_positions.append(_obj.matrix_world.translation)
            if _scene_positions:
                _pad = 2.0
                _bmin = [min(p[i] for p in _scene_positions) - _pad for i in range(3)]
                _bmax = [max(p[i] for p in _scene_positions) + _pad for i in range(3)]
                for i in range(3):
                    if _bmax[i] - _bmin[i] < 4.0:
                        _mid = (_bmin[i] + _bmax[i]) / 2
                        _bmin[i] = _mid - 2.0
                        _bmax[i] = _mid + 2.0
                _spatial_grid = Octree(_bmin, _bmax)
            else:
                _spatial_grid = Octree([0, 0, 0], [10, 10, 10])
        elif SpatialGrid:
            _spatial_grid = SpatialGrid(cell_size=2.0)
        else:
            _spatial_grid = None

        # Pre-filter: collect candidates with LOD tier, skip out-of-range
        candidates = []  # [(obj, lod_tier)]
        for obj in scene.objects:
            if not obj.visible_get():
                continue

            if obj.type == 'LIGHT':
                light = obj.data
                light_entry = {
                    "name": obj.name,
                    "type": light.type,
                    "energy": round(light.energy, 1),
                    "color": [round(c, 3) for c in light.color],
                    "location": [round(v, 3) for v in obj.location],
                }
                if light.type == 'SPOT':
                    light_entry["spot_angle"] = round(math.degrees(light.spot_size), 1)
                    light_entry["spot_blend"] = round(light.spot_blend, 2)
                elif light.type == 'AREA':
                    light_entry["area_shape"] = light.shape
                    light_entry["area_size"] = round(light.size, 3)
                    if light.shape in ('RECTANGLE', 'ELLIPSE'):
                        light_entry["area_size_y"] = round(light.size_y, 3)
                light_entry["shadow"] = light.use_shadow
                lights.append(light_entry)
                continue

            # Quick distance check using origin (cheap — no AABB computation)
            if use_proximity:
                origin_pos = obj.matrix_world.translation
                dist_quick = (origin_pos - focus).length
                # Add margin for large objects whose AABB might extend into radius
                if dist_quick > far_dist + 5.0:
                    out_count += 1
                    continue
                elif dist_quick > mid_dist:
                    candidates.append((obj, "FAR"))
                elif dist_quick > near_dist:
                    candidates.append((obj, "MID"))
                else:
                    candidates.append((obj, "NEAR"))
            else:
                candidates.append((obj, "NEAR"))

        # ══════════════════════════════════════════════════════════════
        # PHASE 2: Object gathering — detail level based on LOD tier
        # Only computes AABB/materials/screen for NEAR+MID objects.
        # FAR objects get name + pos + dim + top only.
        # ══════════════════════════════════════════════════════════════

        # Compute depth thresholds from NEAR+MID objects only
        all_positions = []
        for obj, lod in candidates:
            if obj.type == 'MESH' and lod != "FAR":
                all_positions.append(obj.matrix_world.translation.copy())

        if all_positions and cam:
            cam_pos = cam.matrix_world.translation
            distances = [(p - cam_pos).length for p in all_positions]
            min_dist = min(distances) if distances else 0
            max_dist = max(distances) if distances else 1
            depth_range = max_dist - min_dist if max_dist > min_dist else 1
            fg_threshold = min_dist + depth_range * 0.33
            bg_threshold = min_dist + depth_range * 0.66
        else:
            fg_threshold = 3.0
            bg_threshold = 7.0

        for obj, lod_tier in candidates:
            # ── Compute AABB center (needed for all tiers) ──
            try:
                aabb_min_v, aabb_max_v, aabb_ctr = compute_world_aabb(obj)
                if aabb_ctr is not None:
                    aabb_center = [round(aabb_ctr[i], 3) for i in range(3)]
                else:
                    aabb_center = [round(v, 3) for v in obj.matrix_world.translation]
            except Exception:
                try:
                    bbox_corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
                    aabb_center = [
                        round(sum(c[i] for c in bbox_corners) / len(bbox_corners), 3)
                        for i in range(3)
                    ]
                except Exception:
                    aabb_center = [round(v, 3) for v in obj.matrix_world.translation]

            # Refine LOD with actual AABB center distance (more accurate than origin)
            if use_proximity:
                dist_to_focus = (mathutils.Vector(aabb_center) - focus).length
                if dist_to_focus > far_dist:
                    out_count += 1
                    continue
                elif dist_to_focus > mid_dist:
                    lod_tier = "FAR"
                elif dist_to_focus > near_dist:
                    lod_tier = "MID"
                else:
                    lod_tier = "NEAR"

            obj_data = {
                "name": obj.name,
                "type": obj.type,
                "world_center": aabb_center,
                "_lod": lod_tier,
            }

            # ── FAR tier: minimal data, skip everything expensive ──
            if lod_tier == "FAR":
                try:
                    bbox_corners_f = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
                    bb_min_f = [min(c[i] for c in bbox_corners_f) for i in range(3)]
                    bb_max_f = [max(c[i] for c in bbox_corners_f) for i in range(3)]
                    obj_data["dimensions"] = [round(bb_max_f[i] - bb_min_f[i], 3) for i in range(3)]
                    obj_data["top_z"] = round(bb_max_f[2], 3)
                except Exception:
                    pass
                visible_objects.append(obj_data)
                # Insert into spatial grid but don't add to mesh_objects
                if _spatial_grid:
                    _spatial_grid.insert(obj, obj_data, aabb_center)
                continue

            # ── NEAR + MID: full or summary data ──
            if obj.type == 'MESH' and cam:
                # ── Cache check: reuse object-intrinsic data if matrix unchanged ──
                mh = _matrix_hash(obj)
                cached = _object_cache.get(obj.name)
                cache_hit = cached and cached.get("matrix_hash") == mh

                # Screen-space bbox and depth (ALWAYS recompute — camera may have moved)
                bbox = _get_screen_bbox(obj, scene, cam)
                if bbox:
                    coverage = bbox["width"] * bbox["height"]
                    obj_data["screen_coverage_pct"] = round(coverage * 100, 1)
                    obj_data["quadrant"] = _get_quadrant(bbox["center_x"], bbox["center_y"])
                    obj_data["screen_bbox"] = [
                        round(bbox["min_x"], 3), round(bbox["min_y"], 3),
                        round(bbox["max_x"], 3), round(bbox["max_y"], 3),
                    ]

                # Depth from camera (ALWAYS recompute)
                depth = (obj.matrix_world.translation - cam.matrix_world.translation).length
                obj_data["depth"] = round(depth, 2)
                if depth <= fg_threshold:
                    obj_data["depth_layer"] = "foreground"
                elif depth <= bg_threshold:
                    obj_data["depth_layer"] = "midground"
                else:
                    obj_data["depth_layer"] = "background"

                # Visible face + per-object occlusion (ALWAYS recompute — camera-dependent)
                try:
                    ray_dir = (obj.matrix_world.translation - cam_pos).normalized()
                    hit, loc, normal, idx, hit_obj, matrix = scene.ray_cast(
                        depsgraph, cam_pos, ray_dir
                    )
                    if hit and hit_obj and hit_obj.name == obj.name:
                        abs_n = [abs(normal.x), abs(normal.y), abs(normal.z)]
                        axis = abs_n.index(max(abs_n))
                        sign = "+" if [normal.x, normal.y, normal.z][axis] > 0 else "-"
                        obj_data["visible_face"] = sign + "XYZ"[axis]
                    elif hit and hit_obj and hit_obj.name != obj.name:
                        # Center ray blocked — compute occlusion % via AABB corners
                        corners = _aabb_sample_points(obj, 3)
                        blocked = 0
                        for pt in corners:
                            rd = (pt - cam_pos).normalized()
                            h, _, _, _, ho, _ = scene.ray_cast(depsgraph, cam_pos, rd)
                            if h and ho and ho.name != obj.name:
                                blocked += 1
                        if corners:
                            obj_data["occlusion_pct"] = round(blocked / len(corners) * 100, 1)
                except Exception:
                    pass

                if cache_hit:
                    # ── Reuse cached object-intrinsic data ──
                    if cached.get("rotation"):
                        obj_data["rotation"] = cached["rotation"]
                    if cached.get("facing"):
                        obj_data["facing"] = cached["facing"]
                    if cached.get("dimensions"):
                        obj_data["dimensions"] = cached["dimensions"]
                    if cached.get("top_z") is not None:
                        obj_data["top_z"] = cached["top_z"]
                    if cached.get("source"):
                        obj_data["source"] = cached["source"]
                    if cached.get("material"):
                        obj_data["material"] = cached["material"]
                    if "has_uv" in cached:
                        obj_data["has_uv"] = cached["has_uv"]
                    if cached.get("zone"):
                        obj_data["zone"] = cached["zone"]
                else:
                    # ── Compute fresh object-intrinsic data ──

                    # Rotation — use world-space rotation (matrix_world decomposition)
                    # so Sketchfab mesh children inherit parent chain rotation
                    try:
                        world_rot = obj.matrix_world.to_euler()
                        rot_degs = [round(math.degrees(r), 1) for r in world_rot]
                    except Exception:
                        rot_degs = [round(math.degrees(r), 1) for r in obj.rotation_euler]
                    if any(abs(r) > 1.0 for r in rot_degs):
                        obj_data["rotation"] = rot_degs
                        # Compass facing derived from Z rotation
                        try:
                            from ._utils import rotation_to_compass
                            obj_data["facing"] = rotation_to_compass(rot_degs[2])
                        except Exception:
                            pass

                    # World-space bounding box dimensions + top surface Z
                    try:
                        bbox_corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
                        bb_min = [min(c[i] for c in bbox_corners) for i in range(3)]
                        bb_max = [max(c[i] for c in bbox_corners) for i in range(3)]
                        obj_data["dimensions"] = [round(bb_max[i] - bb_min[i], 3) for i in range(3)]
                        obj_data["top_z"] = round(bb_max[2], 3)
                    except Exception:
                        pass

                    # Source identity for Sketchfab hierarchy children
                    if obj.parent:
                        # Walk up to find the Sketchfab root or first named parent
                        src_name = None
                        current = obj.parent
                        while current:
                            if current.name.startswith("Sketchfab_model"):
                                break
                            # Use parent name if it looks semantic (not "root.001" etc.)
                            if (not current.name.startswith("root.") and
                                    not current.name.startswith("GLTF_") and
                                    not current.name.startswith("Object_") and
                                    not current.name.startswith("RootNode")):
                                src_name = current.name
                                break
                            current = current.parent
                        if src_name:
                            obj_data["source"] = src_name

                    # Material sampling (richer)
                    mat_info = _sample_material(obj)
                    if mat_info:
                        obj_data["material"] = mat_info

                    # UV layer presence
                    if obj.data and hasattr(obj.data, 'uv_layers'):
                        obj_data["has_uv"] = len(obj.data.uv_layers) > 0
                    else:
                        obj_data["has_uv"] = False

                    # Zone (user-defined via custom property or scene zones)
                    zone = obj.get("blenderweave_zone")
                    if zone:
                        obj_data["zone"] = str(zone)
                    elif not zone:
                        # Check scene-level zone definitions (bounds-based)
                        zone = _resolve_zone(obj, scene)
                        if zone:
                            obj_data["zone"] = zone

                    # ── Update cache with fresh data ──
                    _object_cache[obj.name] = {
                        "matrix_hash": mh,
                        "dimensions": obj_data.get("dimensions"),
                        "top_z": obj_data.get("top_z"),
                        "source": obj_data.get("source"),
                        "rotation": obj_data.get("rotation"),
                        "facing": obj_data.get("facing"),
                        "material": obj_data.get("material"),
                        "has_uv": obj_data.get("has_uv"),
                        "zone": obj_data.get("zone"),
                        "aabb_center": aabb_center,
                    }

                mesh_objects.append((obj, obj_data))

            # Insert into spatial grid for pairwise analysis
            if _spatial_grid:
                _spatial_grid.insert(obj, obj_data, aabb_center)

            visible_objects.append(obj_data)

        # ══════════════════════════════════════════════════════════════
        # PHASE 3: Finalize + store spatial grid in result for subsystems
        # ══════════════════════════════════════════════════════════════

        # Sort front-to-back by depth
        visible_objects.sort(key=lambda o: o.get("depth", 999))

        # Compute lod_counts BEFORE stripping _lod field (C1 fix)
        if use_proximity:
            result["out_count"] = out_count
            near_count = sum(1 for o in visible_objects if o.get("_lod") == "NEAR")
            mid_count = sum(1 for o in visible_objects if o.get("_lod") == "MID")
            far_count_r = sum(1 for o in visible_objects if o.get("_lod") == "FAR")
            result["lod_counts"] = {"near": near_count, "mid": mid_count, "far": far_count_r, "out": out_count}

        # Strip internal _lod field from output
        for obj_data in visible_objects:
            obj_data.pop("_lod", None)

        result["visible_objects"] = visible_objects
        result["object_count"] = len(visible_objects)
        result["_spatial_grid"] = _spatial_grid  # shared with subsystems

        # ── Semantic grouping: collapse Sketchfab multi-mesh imports ──
        try:
            _semantic_groups = _compute_semantic_groups(visible_objects, scene)
            if _semantic_groups:
                result["semantic_groups"] = _semantic_groups
        except Exception:
            pass
        result["lights"] = lights
        result["light_count"] = len(lights)
        total_energy = sum(l["energy"] for l in lights)
        result["total_light_energy"] = round(total_energy, 1)

        # Budget caps from scene properties (configurable via UI panel)
        result["_budget_caps"] = {
            "obj": getattr(scene, "blenderweave_cap_obj", 60),
            "rel": getattr(scene, "blenderweave_cap_rel", 20),
            "lit": getattr(scene, "blenderweave_cap_lit", 12),
            "shad": getattr(scene, "blenderweave_cap_shad", 10),
            "mat": getattr(scene, "blenderweave_cap_mat", 10),
            "spatial": getattr(scene, "blenderweave_cap_spatial", 15),
            "hier": getattr(scene, "blenderweave_cap_hier", 8),
            "contain": getattr(scene, "blenderweave_cap_contain", 10),
        }

        # Count emissive objects (scan all visible, not just MESH)
        emissive_count = _count_emissive_objects(scene)

        # ── World/environment ──
        world = scene.world
        if world and world.use_nodes:
            has_hdri = any(n.type == 'TEX_ENVIRONMENT' for n in world.node_tree.nodes)
            bg_node = None
            for n in world.node_tree.nodes:
                if n.type == 'BACKGROUND':
                    bg_node = n
                    break
            result["world"] = {
                "has_hdri": has_hdri,
                "bg_strength": round(bg_node.inputs['Strength'].default_value, 3) if bg_node else None,
                "bg_color": [round(c, 3) for c in bg_node.inputs['Color'].default_value[:3]] if bg_node and not has_hdri else None,
            }
        else:
            result["world"] = {"has_hdri": False, "bg_strength": None, "bg_color": None}

        # ── Ground Z detection ──
        # Find the lowest large horizontal surface (floor plane)
        try:
            ground_z = None
            for obj_data in visible_objects:
                dims = obj_data.get("dimensions")
                top = obj_data.get("top_z")
                if dims and top is not None:
                    dx, dy, dz = dims
                    # Large horizontal surface: footprint > 4m², thin (< 0.5m)
                    if dx * dy > 4.0 and dz < 0.5:
                        floor_z = round(top - dz, 3)
                        if ground_z is None or floor_z < ground_z:
                            ground_z = floor_z
            if ground_z is not None:
                result["ground_z"] = ground_z
            else:
                # Fallback: raycast from camera height downward
                import mathutils as _mu
                cam_z = cam.matrix_world.translation.z if cam else 1.5
                origin = _mu.Vector((0, 0, cam_z))
                hit, loc, _n, _i, _o, _m = scene.ray_cast(depsgraph, origin, _mu.Vector((0, 0, -1)))
                if hit:
                    result["ground_z"] = round(loc.z, 3)
        except Exception:
            pass

        # ── Composition (enhanced) ──
        if cam:
            result["composition"] = _analyze_composition(scene, cam, fg_threshold, bg_threshold)

        # ── Render settings ──
        result["render_settings"] = {
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "samples": _get_sample_count(scene),
            "film_transparent": scene.render.film_transparent,
        }

        # ══════════════════════════════════════════════════════════════
        # PHASE 4: Run all subsystems via registry
        # ══════════════════════════════════════════════════════════════

        # ── VERIFY (post-transform checks — only emit on failure) ──
        verify_failures = compute_verify()
        if verify_failures:
            result["verify"] = verify_failures

        # ── Run ALL registered subsystems via registry ──
        try:
            from .perception_registry import run_all, PerceptionContext
            from .subsystems import discover
            discover()

            ctx = PerceptionContext(
                mesh_objects=mesh_objects,
                visible_objects=visible_objects,
                spatial_grid=_spatial_grid,
                scene=scene,
                depsgraph=depsgraph,
                cam=cam,
                lights=lights,
                semantic_groups=result.get("semantic_groups", []),
                world_info=result.get("world", {}),
                result=result,
                emissive_count=emissive_count,
                include_flags={
                    "spatial": include_spatial,
                    "lighting": include_lighting,
                    "materials": include_materials,
                    "constraints": include_constraints,
                    "shadows": include_shadows,
                    "ray_grid": include_ray_grid,
                    "multi_view": include_multi_view,
                    "hierarchy": include_hierarchy,
                    "physics": include_physics,
                    "animation": include_animation,
                    "micro_render": include_micro_render,
                },
            )
            subsystem_results = run_all(ctx)
            result.update(subsystem_results)

            # Post-process: overwrite AABB coverage with ray grid values
            ray_grid = result.get("ray_grid")
            if ray_grid:
                ray_cov = ray_grid.get("coverage_map", {})
                for obj_data in result.get("visible_objects", []):
                    name = obj_data.get("name")
                    if name and name in ray_cov:
                        obj_data["screen_coverage_pct"] = ray_cov[name]

            # Post-process: enrich containment into visible_objects
            containment = result.get("containment")
            if containment:
                _enrich_containment(result.get("visible_objects", []), containment, mesh_objects)

        except Exception:
            traceback.print_exc()

        # ── Cleanup: strip internal fields ──
        result.pop("_spatial_grid", None)

        # ── Update delta cache ──
        global _last_perception
        _last_perception = result

        return result
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Perception failed: {str(e)}"}


def get_viewport_thumbnail(size=96, quality=50):
    """Capture a tiny viewport thumbnail as base64 JPEG."""
    try:
        temp_path = os.path.join(
            tempfile.gettempdir(),
            f"blenderweave_thumb_{uuid.uuid4().hex[:8]}.jpg"
        )

        # Find 3D viewport
        area = None
        for a in bpy.context.screen.areas:
            if a.type == 'VIEW_3D':
                area = a
                break
        if not area:
            return {"error": "No 3D viewport found"}

        # Capture screenshot — do NOT call bpy.ops.ed.undo() after.
        # The old code called undo() to compensate for screenshot_area's undo step,
        # but that undo silently reverts actual scene changes when called from
        # auto-feedback. The screenshot undo step is harmless (just image data).
        with bpy.context.temp_override(area=area):
            bpy.ops.screen.screenshot_area(filepath=temp_path)

        # Load, resize, save as JPEG
        img = bpy.data.images.load(temp_path)
        width, height = img.size

        if max(width, height) > size:
            scale = size / max(width, height)
            new_width = max(1, int(width * scale))
            new_height = max(1, int(height * scale))
            img.scale(new_width, new_height)
            width, height = new_width, new_height

        # Save as JPEG
        jpeg_path = temp_path.replace('.jpg', '_thumb.jpg')
        img.file_format = 'JPEG'
        scene = bpy.context.scene
        orig_quality = scene.render.image_settings.quality
        scene.render.image_settings.quality = quality
        img.save_render(jpeg_path)
        scene.render.image_settings.quality = orig_quality

        bpy.data.images.remove(img)

        # Read and encode
        with open(jpeg_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('ascii')

        # Cleanup
        for p in [temp_path, jpeg_path]:
            if os.path.exists(p):
                os.remove(p)

        return {
            "success": True,
            "thumbnail": img_b64,
            "width": width,
            "height": height,
            "size_bytes": len(img_b64) * 3 // 4,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Thumbnail capture failed: {str(e)}"}


def get_scene_delta():
    """Compare current scene state to last perception capture.

    Enhanced with per-object transform tracking, material property tracking,
    and contact topology changes.
    """
    global _last_perception

    if _last_perception is None:
        return {"error": "No previous perception. Call get_scene_perception first."}

    try:
        current = get_scene_perception(
            include_spatial=False, include_lighting=False,
            include_materials=False, include_constraints=False,
            include_shadows=False, include_ray_grid=False,
            include_multi_view=False,
        )
        if "error" in current:
            return current

        prev = _last_perception
        changes = []

        # Compare light energies
        prev_lights = {l["name"]: l for l in prev.get("lights", [])}
        curr_lights = {l["name"]: l for l in current.get("lights", [])}

        for name, curr_l in curr_lights.items():
            if name in prev_lights:
                prev_l = prev_lights[name]
                if abs(curr_l["energy"] - prev_l["energy"]) > 0.1:
                    changes.append(f"{name} energy {prev_l['energy']}W->{curr_l['energy']}W")
                if curr_l["color"] != prev_l["color"]:
                    changes.append(f"{name} color changed")
                if curr_l["location"] != prev_l["location"]:
                    changes.append(f"{name} moved")
            else:
                changes.append(f"Light added: {name}")

        for name in prev_lights:
            if name not in curr_lights:
                changes.append(f"Light removed: {name}")

        # Compare object counts
        if current["object_count"] != prev["object_count"]:
            diff = current["object_count"] - prev["object_count"]
            changes.append(f"Object count {prev['object_count']}->{current['object_count']} ({'+' if diff > 0 else ''}{diff})")

        # Compare camera
        prev_cam = prev.get("camera", {})
        curr_cam = current.get("camera", {})
        if prev_cam.get("location") != curr_cam.get("location"):
            changes.append("Camera moved")
        if prev_cam.get("focal_length") != curr_cam.get("focal_length"):
            changes.append(f"Focal length {prev_cam.get('focal_length')}->{curr_cam.get('focal_length')}")

        # Compare world
        prev_world = prev.get("world", {})
        curr_world = current.get("world", {})
        if prev_world.get("bg_strength") != curr_world.get("bg_strength"):
            changes.append(f"World strength {prev_world.get('bg_strength')}->{curr_world.get('bg_strength')}")

        # ── Enhanced: per-object transform tracking ──
        curr_objs = {o["name"]: o for o in current.get("visible_objects", []) if "world_center" in o}
        prev_objs = {o["name"]: o for o in prev.get("visible_objects", []) if "world_center" in o}

        for name, curr_o in curr_objs.items():
            if name in prev_objs:
                prev_o = prev_objs[name]
                pc = prev_o["world_center"]
                cc = curr_o["world_center"]
                delta = [round(cc[i] - pc[i], 3) for i in range(3)]
                if any(abs(d) > 0.01 for d in delta):
                    changes.append(f"moved: {name} by [{delta[0]},{delta[1]},{delta[2]}]")
            else:
                changes.append(f"Object added: {name}")

        for name in prev_objs:
            if name not in curr_objs:
                changes.append(f"Object removed: {name}")

        # ── Enhanced: material property tracking ──
        curr_mat_snap = {}
        for o in current.get("visible_objects", []):
            mat = o.get("material")
            if mat and mat.get("name"):
                curr_mat_snap[mat["name"]] = mat
        prev_mat_snap = {}
        for o in prev.get("visible_objects", []):
            mat = o.get("material")
            if mat and mat.get("name"):
                prev_mat_snap[mat["name"]] = mat

        for mat_name, curr_m in curr_mat_snap.items():
            if mat_name in prev_mat_snap:
                prev_m = prev_mat_snap[mat_name]
                for prop in ("metallic", "roughness", "transmission", "base_color",
                             "emission_strength", "subsurface_weight", "ior"):
                    cv = curr_m.get(prop)
                    pv = prev_m.get(prop)
                    if cv != pv:
                        changes.append(f"material_changed: {mat_name}.{prop}")

        # ── Enhanced: contact topology ──
        curr_contacts = set()
        for o1 in current.get("visible_objects", []):
            if "world_center" not in o1:
                continue
            for o2 in current.get("visible_objects", []):
                if o1["name"] >= o2["name"] or "world_center" not in o2:
                    continue
                dist = sum((o1["world_center"][i] - o2["world_center"][i]) ** 2 for i in range(3)) ** 0.5
                if dist < 0.1:
                    curr_contacts.add(frozenset({o1["name"], o2["name"]}))

        prev_contacts = set()
        for o1 in prev.get("visible_objects", []):
            if "world_center" not in o1:
                continue
            for o2 in prev.get("visible_objects", []):
                if o1["name"] >= o2["name"] or "world_center" not in o2:
                    continue
                dist = sum((o1["world_center"][i] - o2["world_center"][i]) ** 2 for i in range(3)) ** 0.5
                if dist < 0.1:
                    prev_contacts.add(frozenset({o1["name"], o2["name"]}))

        for pair in curr_contacts - prev_contacts:
            names = sorted(pair)
            changes.append(f"contact_formed: {names[0]}<->{names[1]}")
        for pair in prev_contacts - curr_contacts:
            names = sorted(pair)
            changes.append(f"contact_broken: {names[0]}<->{names[1]}")

        return {
            "success": True,
            "changes": changes,
            "change_count": len(changes),
            "message": "; ".join(changes) if changes else "No changes detected",
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Delta failed: {str(e)}"}







def _rgb_to_color_name(r, g, b):
    """Convert RGB (0-1 range) to a human-readable color name via HSL."""
    # Luminance (perceptual)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b

    # Achromatic check: low saturation
    mx = max(r, g, b)
    mn = min(r, g, b)
    chroma = mx - mn

    if chroma < 0.05:
        # Achromatic
        if lum > 0.85:
            return "white"
        elif lum > 0.6:
            return "light_gray"
        elif lum > 0.35:
            return "gray"
        elif lum > 0.12:
            return "dark_gray"
        else:
            return "near_black"

    # Hue calculation
    if mx == r:
        hue = 60 * (((g - b) / chroma) % 6)
    elif mx == g:
        hue = 60 * (((b - r) / chroma) + 2)
    else:
        hue = 60 * (((r - g) / chroma) + 4)
    if hue < 0:
        hue += 360

    # Lightness (HSL)
    lightness = (mx + mn) / 2
    # Saturation (HSL)
    if lightness == 0 or lightness == 1:
        sat = 0
    else:
        sat = chroma / (1 - abs(2 * lightness - 1))

    # Low saturation warm/cool tones
    if sat < 0.2:
        if hue < 60 or hue > 330:
            # Warm gray
            if lightness > 0.7:
                return "cream"
            elif lightness > 0.45:
                return "beige"
            elif lightness > 0.25:
                return "warm_brown"
            else:
                return "dark_brown"
        else:
            if lightness > 0.5:
                return "steel_gray"
            else:
                return "slate"

    # Saturated colors by hue
    if hue < 15 or hue >= 345:
        # Red
        if lightness > 0.7:
            return "salmon"
        elif lightness > 0.4:
            return "red"
        else:
            return "dark_brown"
    elif hue < 40:
        # Orange/brown
        if lightness > 0.65:
            return "peach"
        elif lightness > 0.45:
            return "orange"
        elif lightness > 0.2:
            return "warm_brown"
        else:
            return "chocolate"
    elif hue < 65:
        # Yellow/gold
        if lightness > 0.6:
            return "gold"
        elif lightness > 0.35:
            return "amber"
        else:
            return "dark_brown"
    elif hue < 80:
        # Yellow-green
        if lightness > 0.5:
            return "yellow"
        else:
            return "olive"
    elif hue < 160:
        # Green
        if lightness > 0.6:
            return "light_green"
        elif lightness > 0.3:
            return "green"
        else:
            return "dark_green"
    elif hue < 200:
        # Teal/cyan
        if lightness > 0.5:
            return "cyan"
        else:
            return "teal"
    elif hue < 260:
        # Blue
        if lightness > 0.6:
            return "cool_blue"
        elif lightness > 0.3:
            return "blue"
        else:
            return "dark_blue"
    elif hue < 310:
        # Purple
        if lightness > 0.6:
            return "lavender"
        elif lightness > 0.3:
            return "purple"
        else:
            return "dark_purple"
    else:
        # Pink/magenta
        if lightness > 0.6:
            return "pink"
        elif lightness > 0.3:
            return "magenta"
        else:
            return "dark_purple"


def _count_emissive_objects(scene):
    """Count visible objects with emission strength > 0 (any object type)."""
    count = 0
    for obj in scene.objects:
        if not obj.visible_get() or not obj.material_slots:
            continue
        found = False
        for slot in obj.material_slots:
            mat = slot.material
            if mat and mat.use_nodes and mat.node_tree:
                for node in mat.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        es = node.inputs.get('Emission Strength')
                        if es and es.default_value > 0:
                            count += 1
                            found = True
                            break
            if found:
                break
    return count
def _classify_mood(total_energy, world_strength, emissive_count):
    """Classify scene mood from lighting metrics."""
    if total_energy > 1000 or world_strength > 2.0:
        return "bright"
    elif total_energy > 200 or (world_strength > 0.5 and total_energy > 50):
        return "normal"
    elif total_energy > 50 or world_strength > 0.2 or emissive_count > 0:
        return "dim"
    else:
        return "dark"


def _sample_material(obj):
    """Sample the first Principled BSDF material on an object."""
    if not obj.material_slots:
        return None

    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes or not mat.node_tree:
            continue

        bsdf = None
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                bsdf = node
                break
        if not bsdf:
            continue

        # ── Material fingerprint cache check ──
        fp = _material_fingerprint(mat)
        if fp and mat.name in _material_cache:
            cached_mat = _material_cache[mat.name]
            if cached_mat.get("fingerprint") == fp:
                return cached_mat["info"]

        info = {"name": mat.name}

        # Base color
        bc = bsdf.inputs.get('Base Color')
        if bc:
            if bc.links:
                info["base_color"] = "textured"
                info["has_textures"] = True
            else:
                rgb = [round(c, 3) for c in bc.default_value[:3]]
                info["base_color"] = rgb
                info["has_textures"] = False
                info["color_name"] = _rgb_to_color_name(rgb[0], rgb[1], rgb[2])

        # Extended properties
        for prop_name in ['Metallic', 'Roughness', 'IOR']:
            inp = bsdf.inputs.get(prop_name)
            if inp and not inp.links:
                info[prop_name.lower()] = round(inp.default_value, 3)

        # Transmission (Blender 4+ uses "Transmission Weight")
        for tname in ['Transmission Weight', 'Transmission']:
            inp = bsdf.inputs.get(tname)
            if inp and not inp.links:
                info["transmission"] = round(inp.default_value, 3)
                break

        # Emission strength + color
        inp = bsdf.inputs.get('Emission Strength')
        if inp and not inp.links:
            info["emission_strength"] = round(inp.default_value, 3)
        ec = bsdf.inputs.get('Emission Color')
        if ec and not ec.links:
            info["emission_color"] = [round(c, 3) for c in ec.default_value[:3]]

        # Subsurface weight (Blender 4+)
        for sname in ['Subsurface Weight', 'Subsurface']:
            inp = bsdf.inputs.get(sname)
            if inp and not inp.links:
                info["subsurface_weight"] = round(inp.default_value, 3)
                break

        # Coat weight
        inp = bsdf.inputs.get('Coat Weight')
        if inp and not inp.links:
            info["coat_weight"] = round(inp.default_value, 3)

        # Transparent flag: transmission > 0.5 or Glass BSDF present
        is_transparent = info.get("transmission", 0) > 0.5
        if not is_transparent:
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_GLASS':
                    is_transparent = True
                    break
        if is_transparent:
            info["transparent"] = True

        # ── Cache material result with fingerprint ──
        if fp:
            _material_cache[mat.name] = {"fingerprint": fp, "info": info}

        return info

    return None


def _get_screen_bbox(obj, scene, cam):
    """Estimate an object's screen-space bounding box from camera perspective."""
    try:
        import mathutils
        from bpy_extras.object_utils import world_to_camera_view

        corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
        screen_coords = []
        for corner in corners:
            co = world_to_camera_view(scene, cam, corner)
            if co.z > 0:
                screen_coords.append((co.x, co.y))

        if not screen_coords:
            return None

        xs = [c[0] for c in screen_coords]
        ys = [c[1] for c in screen_coords]

        min_x = max(0, min(xs))
        max_x = min(1, max(xs))
        min_y = max(0, min(ys))
        max_y = min(1, max(ys))

        # Off-screen objects can produce degenerate bbox after clamping
        if min_x >= max_x or min_y >= max_y:
            return None

        return {
            "min_x": min_x, "min_y": min_y,
            "max_x": max_x, "max_y": max_y,
            "width": max_x - min_x,
            "height": max_y - min_y,
            "center_x": (min_x + max_x) / 2,
            "center_y": (min_y + max_y) / 2,
        }
    except Exception:
        return None


def _get_quadrant(cx, cy):
    """Return which region of the frame a point is in (3x3 grid)."""
    if cx < 0.333:
        h = "left"
    elif cx > 0.666:
        h = "right"
    else:
        h = "center"

    if cy < 0.333:
        v = "bot"
    elif cy > 0.666:
        v = "top"
    else:
        v = "mid"

    return f"{v}-{h}"


def _analyze_composition(scene, cam, fg_threshold=3.0, bg_threshold=7.0):
    """Analyze composition metrics from camera view.

    Enhanced with visual weight balance, depth layer distribution, and edge proximity.
    """
    try:
        from bpy_extras.object_utils import world_to_camera_view

        subjects = []
        for obj in scene.objects:
            if not obj.visible_get() or obj.type != 'MESH':
                continue
            co = world_to_camera_view(scene, cam, obj.location)
            if co.z > 0 and 0 <= co.x <= 1 and 0 <= co.y <= 1:
                # Get coverage for weight calculation
                bbox = _get_screen_bbox(obj, scene, cam)
                coverage = bbox["width"] * bbox["height"] if bbox else 0
                # Estimate luminance from material
                luminance = 0.5  # default
                mat_info = _sample_material(obj)
                if mat_info:
                    bc = mat_info.get("base_color", [0.5, 0.5, 0.5])
                    if isinstance(bc, list):
                        luminance = 0.2126 * bc[0] + 0.7152 * bc[1] + 0.0722 * bc[2]

                depth = (obj.matrix_world.translation - cam.matrix_world.translation).length
                subjects.append({
                    "name": obj.name,
                    "screen_x": co.x,
                    "screen_y": co.y,
                    "coverage": coverage,
                    "luminance": luminance,
                    "depth": depth,
                    "bbox": bbox,
                })

        # Rule of thirds
        thirds_score = 0
        if subjects:
            for s in subjects:
                x_dist = min(abs(s["screen_x"] - 0.333), abs(s["screen_x"] - 0.666))
                y_dist = min(abs(s["screen_y"] - 0.333), abs(s["screen_y"] - 0.666))
                score = max(0, 1.0 - min(x_dist, y_dist) * 5)
                thirds_score += score
            thirds_score = round(thirds_score / len(subjects), 3)

        total_in_scene = len([o for o in scene.objects if o.visible_get() and o.type == 'MESH'])

        # Visual weight balance: sum(coverage * luminance) for left/right halves
        left_weight = 0
        right_weight = 0
        for s in subjects:
            weight = s["coverage"] * s["luminance"]
            if s["screen_x"] < 0.5:
                left_weight += weight
            else:
                right_weight += weight
        total_weight = left_weight + right_weight
        balance = round(1.0 - abs(left_weight - right_weight) / max(total_weight, 0.001), 3)

        # Depth layer distribution
        fg_count = sum(1 for s in subjects if s["depth"] <= fg_threshold)
        mg_count = sum(1 for s in subjects if fg_threshold < s["depth"] <= bg_threshold)
        bg_count = sum(1 for s in subjects if s["depth"] > bg_threshold)
        layers_used = sum(1 for c in (fg_count, mg_count, bg_count) if c > 0)

        # Edge proximity: flag objects with bbox within 5% of frame edge
        edge_objects = []
        edge_margin = 0.05
        for s in subjects:
            bbox = s.get("bbox")
            if bbox:
                if (bbox["min_x"] < edge_margin or bbox["max_x"] > 1 - edge_margin or
                        bbox["min_y"] < edge_margin or bbox["max_y"] > 1 - edge_margin):
                    edge_objects.append(s["name"])

        result = {
            "rule_of_thirds_score": thirds_score,
            "subjects_in_frame": len(subjects),
            "total_visible": total_in_scene,
            "balance": balance,
            "depth_layers": f"{layers_used}/3",
            "depth_distribution": {"fg": fg_count, "mg": mg_count, "bg": bg_count},
        }
        if edge_objects:
            result["edge_objects"] = edge_objects
        return result
    except Exception:
        return {}


def _get_sample_count(scene):
    """Get current render sample count regardless of engine."""
    engine = scene.render.engine
    if engine == 'CYCLES':
        return scene.cycles.samples
    elif hasattr(scene, 'eevee') and hasattr(scene.eevee, 'taa_render_samples'):
        return scene.eevee.taa_render_samples
    return None



def _aabb_sample_points(obj, grid_size=3):
    """Return 9 sample points across the object AABB: 8 corners + center."""
    import mathutils
    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    center = mathutils.Vector((0, 0, 0))
    for c in corners:
        center += c
    center /= len(corners)
    return corners + [center]


def _enrich_containment(visible_objects, containment, mesh_objects):
    """Add inside= and contains: fields to visible_objects based on containment."""
    # Build lookup
    inner_to_outer = {}  # inner_name -> outer_name
    outer_to_inners = {}  # outer_name -> [inner_names]

    for c in containment:
        inner_to_outer[c["inner"]] = c["outer"]
        outer_to_inners.setdefault(c["outer"], []).append(c["inner"])

    # Check if outer is transparent (container flagging)
    mat_lookup = {}
    for _, data in mesh_objects:
        mat = data.get("material", {})
        if mat.get("name"):
            mat_lookup[data["name"]] = mat

    for obj_data in visible_objects:
        name = obj_data.get("name")
        if name in inner_to_outer:
            obj_data["inside"] = inner_to_outer[name]
        if name in outer_to_inners:
            obj_data["contains"] = outer_to_inners[name]


def _src_base_name(src):
    """Extract base name from a source identity, stripping instance suffixes.

    'Cassidy Dinning Chair_jok_0.002' → 'Cassidy Dinning Chair'
    'Cassidy Dinning Chair_1.003'     → 'Cassidy Dinning Chair'
    'Mesh1.0_0'                       → 'Mesh1.0'
    """
    import re
    # Strip trailing .NNN
    name = re.sub(r'\.\d{3}$', '', src)
    # Strip trailing _N or _word_N patterns (instance suffixes)
    name = re.sub(r'[_ ](jok_)?\d+$', '', name)
    # Strip trailing _N again for nested suffixes
    name = re.sub(r'[_ ]\d+$', '', name)
    return name.strip()


def _aggregate_group(members):
    """Compute aggregate AABB, dominant material, and facing for a group."""
    all_mins = []
    all_maxs = []
    for m in members:
        wc = m.get("world_center", [0, 0, 0])
        dims = m.get("dimensions", [0.1, 0.1, 0.1])
        half = [d / 2 for d in dims]
        all_mins.append([wc[i] - half[i] for i in range(3)])
        all_maxs.append([wc[i] + half[i] for i in range(3)])

    if not all_mins:
        return None

    agg_min = [min(m[i] for m in all_mins) for i in range(3)]
    agg_max = [max(m[i] for m in all_maxs) for i in range(3)]
    center = [round((agg_min[i] + agg_max[i]) / 2, 3) for i in range(3)]
    dimensions = [round(agg_max[i] - agg_min[i], 3) for i in range(3)]
    top_z = round(agg_max[2], 3)

    # Dominant material: pick from largest member (by coverage or dimensions volume)
    dominant_mat = None
    best_vol = 0
    for m in members:
        mat = m.get("material")
        if mat:
            dims = m.get("dimensions", [0, 0, 0])
            vol = dims[0] * dims[1] * dims[2]
            if vol > best_vol:
                best_vol = vol
                dominant_mat = mat

    # Facing: use first member that has one
    facing = None
    for m in members:
        if m.get("facing"):
            facing = m["facing"]
            break

    return {
        "center": center,
        "dimensions": dimensions,
        "top_z": top_z,
        "material": dominant_mat,
        "facing": facing,
    }


def _compute_semantic_groups(visible_objects, scene):
    """Collapse multi-mesh imports into single composite entries.

    Two grouping strategies:
    1. Sketchfab root: objects sharing a Sketchfab_model* parent
    2. Source base name: objects sharing the same src= base (catches duplicated imports)

    Returns list of {root, display_name, center, dimensions, top_z, member_count, members, material, facing}.
    """
    import re

    groups = []
    already_grouped = set()  # Track which objects are already in a group

    # ── Strategy 1: Sketchfab root grouping ──
    sketchfab_roots = {}
    for obj in scene.objects:
        if obj.name.startswith("Sketchfab_model") and obj.type == 'EMPTY':
            sketchfab_roots[obj.name] = obj

    obj_lookup = {od["name"]: od for od in visible_objects}

    if sketchfab_roots:
        root_members = {}
        for obj in scene.objects:
            if obj.name not in obj_lookup:
                continue
            current = obj.parent
            while current:
                if current.name in sketchfab_roots:
                    root_members.setdefault(current.name, []).append(obj_lookup[obj.name])
                    break
                current = current.parent

        for root_name, members in root_members.items():
            if len(members) < 2:
                continue

            root_obj = sketchfab_roots[root_name]

            # Extract display name
            display_name = None

            # Check user-assigned parent
            if root_obj.parent and not root_obj.parent.name.startswith("Sketchfab_"):
                display_name = root_obj.parent.name

            # Walk hierarchy for semantic name
            if not display_name:
                _generic = ("root.", "GLTF_", "Object_", "RootNode", "Sketchfab_")
                def _find_semantic(obj, depth=0):
                    if depth > 5:
                        return None
                    for child in obj.children:
                        name = child.name
                        if not any(name.startswith(p) for p in _generic):
                            if not re.search(r'\.(obj|fbx|gles|glb|gltf)\b', name, re.I):
                                return name
                        result = _find_semantic(child, depth + 1)
                        if result:
                            return result
                    return None
                display_name = _find_semantic(root_obj)

            # Fallback: src= from member
            if not display_name:
                for m in members:
                    src = m.get("source")
                    if src:
                        display_name = _src_base_name(src)
                        break

            if not display_name:
                for child in root_obj.children:
                    if not child.name.startswith("Sketchfab_"):
                        display_name = child.name
                        break

            if not display_name:
                display_name = root_name

            # Clean up
            display_name = re.sub(r'\.\d{3}$', '', display_name)
            display_name = re.sub(r'\.(obj|fbx|gles|glb|gltf).*$', '', display_name, flags=re.I)
            display_name = display_name.replace("_", " ").strip()

            # Reject generic names — use material or fallback
            _generic_names = {"root", "gltf scenerootnode", "rootnode", "scene", "mesh1.0 0", "mesh1.0"}
            if display_name.lower() in _generic_names:
                # Try dominant material from members
                mat_names = [m.get("material", "") for m in members if m.get("material")]
                if mat_names:
                    # Use most common material as group descriptor
                    from collections import Counter
                    common_mat = Counter(mat_names).most_common(1)[0][0]
                    common_mat = re.sub(r'\(.*\)', '', common_mat).strip()
                    display_name = f"{common_mat} group"
                else:
                    display_name = f"Group ({len(members)} objects)"

            agg = _aggregate_group(members)
            if not agg:
                continue

            member_names = [m["name"] for m in members]
            already_grouped.update(member_names)

            groups.append({
                "root": root_name,
                "display_name": display_name,
                "center": agg["center"],
                "dimensions": agg["dimensions"],
                "top_z": agg["top_z"],
                "material": agg["material"],
                "facing": agg["facing"],
                "member_count": len(members),
                "members": member_names,
            })

    # ── Strategy 2: Source base-name grouping ──
    # Group objects with matching src= base that aren't already in a Sketchfab group
    src_groups = {}  # base_name -> [obj_data]
    for od in visible_objects:
        if od["name"] in already_grouped:
            continue
        src = od.get("source")
        if not src:
            continue
        base = _src_base_name(src)
        if base:
            src_groups.setdefault(base, []).append(od)

    for base_name, members in src_groups.items():
        if len(members) < 2:
            continue

        # Check if all members are at the same position (same import)
        # vs spread around (duplicated furniture) — group either way
        display_name = base_name
        display_name = re.sub(r'\.(obj|fbx|gles|glb|gltf).*$', '', display_name, flags=re.I)
        display_name = display_name.replace("_", " ").strip()

        agg = _aggregate_group(members)
        if not agg:
            continue

        member_names = [m["name"] for m in members]
        already_grouped.update(member_names)

        groups.append({
            "root": f"src:{base_name}",
            "display_name": display_name,
            "center": agg["center"],
            "dimensions": agg["dimensions"],
            "top_z": agg["top_z"],
            "material": agg["material"],
            "facing": agg["facing"],
            "member_count": len(members),
            "members": member_names,
        })

    return groups




def capture_verify_state(object_names=None):
    """Capture pre-transform state for VERIFY comparison.

    Call this BEFORE a modifying tool executes. After the tool runs,
    compute_verify() compares pre/post state and reports failures.

    Args:
        object_names: List of object names to track. If None, tracks all visible mesh objects.
    """
    global _verify_pre_state
    import mathutils

    scene = bpy.context.scene
    state = {}

    objects_to_track = []
    if object_names:
        for name in object_names:
            obj = bpy.data.objects.get(name)
            if obj:
                objects_to_track.append(obj)
    else:
        for obj in scene.objects:
            if obj.visible_get() and obj.type in ('MESH', 'EMPTY'):
                objects_to_track.append(obj)

    for obj in objects_to_track:
        try:
            from ._utils import compute_world_aabb
            aabb_min, aabb_max, aabb_center = compute_world_aabb(obj)
            state[obj.name] = {
                "location": list(obj.location),
                "rotation": [math.degrees(r) for r in obj.rotation_euler],
                "scale": list(obj.scale),
                "aabb_center": [round(c, 4) for c in aabb_center] if aabb_center else None,
            }
        except Exception:
            state[obj.name] = {
                "location": list(obj.location),
                "rotation": [math.degrees(r) for r in obj.rotation_euler],
                "scale": list(obj.scale),
                "aabb_center": None,
            }

    _verify_pre_state = state


def compute_verify(object_names=None):
    """Compare post-transform state to pre-transform snapshot.

    Returns list of VERIFY failure dicts. Empty list = all transforms verified OK.
    Only emits on FAILURE — silent on success.

    Checks:
    - Did mesh world position actually change? (parent moved but mesh didn't = hierarchy bug)
    - Did mesh rotation actually change? (parent rotated but mesh unchanged)
    - Did transform produce NaN or degenerate values?
    """
    global _verify_pre_state
    import mathutils

    if _verify_pre_state is None:
        return []

    failures = []
    scene = bpy.context.scene

    objects_to_check = []
    if object_names:
        for name in object_names:
            obj = bpy.data.objects.get(name)
            if obj:
                objects_to_check.append(obj)
    else:
        for name in _verify_pre_state:
            obj = bpy.data.objects.get(name)
            if obj:
                objects_to_check.append(obj)

    for obj in objects_to_check:
        name = obj.name
        pre = _verify_pre_state.get(name)
        if not pre:
            continue

        try:
            # Current state
            cur_loc = list(obj.location)
            cur_rot = [math.degrees(r) for r in obj.rotation_euler]

            # Check for NaN/Inf
            all_values = cur_loc + cur_rot + list(obj.scale)
            if any(math.isnan(v) or math.isinf(v) for v in all_values):
                failures.append({
                    "result": "FAIL",
                    "object": name,
                    "message": f"transform produced NaN/Inf values loc={[round(v,2) for v in cur_loc]}",
                })
                continue

            # Check mesh AABB actually moved (catches Sketchfab hierarchy bugs)
            if pre["aabb_center"]:
                try:
                    from ._utils import compute_world_aabb
                    _, _, cur_center = compute_world_aabb(obj)
                    if cur_center:
                        cur_c = [round(cur_center[i], 4) for i in range(3)]
                        pre_c = pre["aabb_center"]
                        mesh_delta = sum(abs(cur_c[i] - pre_c[i]) for i in range(3))
                        parent_delta = sum(abs(cur_loc[i] - pre["location"][i]) for i in range(3))

                        # Parent moved but mesh didn't
                        if parent_delta > 0.01 and mesh_delta < 0.001:
                            failures.append({
                                "result": "FAIL",
                                "object": name,
                                "message": f"parent moved by {round(parent_delta,3)}m but mesh AABB unchanged (hierarchy transform bug)",
                            })

                        # Parent rotated but mesh didn't
                        rot_delta = sum(abs(cur_rot[i] - pre["rotation"][i]) for i in range(3))
                        if rot_delta > 1.0 and mesh_delta < 0.001:
                            failures.append({
                                "result": "WARN",
                                "object": name,
                                "message": f"parent rotated by {round(rot_delta,1)}° but mesh AABB unchanged (rotation may not have propagated)",
                            })
                except Exception:
                    pass

        except Exception:
            pass

    # Clear pre-state after verification
    _verify_pre_state = None
    return failures


def _resolve_zone(obj, scene):
    """Resolve zone for an object based on scene-level zone definitions.

    Zones are defined as custom properties on the scene:
        scene["blenderweave_zones"] = {
            "kitchen": {"min": [-5, -4, 0], "max": [0, 4, 3]},
            "dining": {"min": [0, -4, 0], "max": [5, 4, 3]},
        }

    Returns zone name if object center is within a zone's bounds, else None.
    """
    try:
        zones = scene.get("blenderweave_zones")
        if not zones:
            return None

        # Object center
        pos = obj.matrix_world.translation
        for zone_name, bounds in zones.items():
            zone_min = bounds.get("min", [-999, -999, -999])
            zone_max = bounds.get("max", [999, 999, 999])
            if (zone_min[0] <= pos.x <= zone_max[0] and
                    zone_min[1] <= pos.y <= zone_max[1] and
                    zone_min[2] <= pos.z <= zone_max[2]):
                return zone_name
    except Exception:
        pass
    return None
