"""Micro-render subsystem — tiny Cycles render for per-object brightness and palette.

Uses Cycles at 64x64 with minimal samples for accurate light transport including
emissive objects, GI, and caustics that EEVEE misses.
"""
import bpy
import math
import traceback

from ..perception_registry import register

_micro_render_cache = {"hash": None, "result": None}


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
                return "taupe"
            else:
                return "dark_gray"
        else:
            # Cool gray
            if lightness > 0.7:
                return "silver"
            elif lightness > 0.45:
                return "slate"
            elif lightness > 0.25:
                return "charcoal"
            else:
                return "dark_gray"

    # Full-saturation hue mapping
    if hue < 15:
        if lightness > 0.6:
            return "salmon"
        elif lightness > 0.3:
            return "red"
        else:
            return "dark_red"
    elif hue < 40:
        # Orange
        if lightness > 0.6:
            return "peach"
        elif lightness > 0.3:
            return "orange"
        else:
            return "brown"
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


def _scene_render_hash(scene):
    """Hash scene state relevant to micro-render output.

    Covers object transforms, visibility, materials, light energies/colors,
    world strength, and camera transform (position + rotation).
    """
    import hashlib
    h = hashlib.md5()
    for obj in scene.objects:
        vis = obj.visible_get()
        h.update(f"{obj.name}:v={vis}".encode())
        if not vis:
            continue
        m = obj.matrix_world
        h.update(f"{m[0][0]:.2f},{m[0][3]:.3f},{m[1][3]:.3f},{m[2][3]:.3f},{m[0][1]:.2f},{m[1][1]:.2f}".encode())
        if obj.type == 'LIGHT':
            light = obj.data
            h.update(f"L:{light.energy:.1f},{light.color[0]:.2f},{light.color[1]:.2f},{light.color[2]:.2f}".encode())
        elif obj.type == 'MESH' and obj.material_slots:
            for slot in obj.material_slots[:1]:  # first material only for speed
                mat = slot.material
                if mat and mat.use_nodes and mat.node_tree:
                    for node in mat.node_tree.nodes:
                        if node.type == 'BSDF_PRINCIPLED':
                            bc = node.inputs.get('Base Color')
                            if bc and not bc.links:
                                h.update(f"BC:{bc.default_value[0]:.2f},{bc.default_value[1]:.2f},{bc.default_value[2]:.2f}".encode())
                            r = node.inputs.get('Roughness')
                            if r and not r.links:
                                h.update(f"R:{r.default_value:.2f}".encode())
                            break
    world = scene.world
    if world and world.use_nodes:
        for node in world.node_tree.nodes:
            if node.type == 'BACKGROUND':
                s = node.inputs.get('Strength')
                if s:
                    h.update(f"WS:{s.default_value:.3f}".encode())
                break
    cam = scene.camera
    if cam:
        cm = cam.matrix_world
        h.update(f"CAM:{cm[0][0]:.2f},{cm[0][1]:.2f},{cm[0][2]:.2f},{cm[0][3]:.3f},{cm[1][3]:.3f},{cm[2][3]:.3f}".encode())
    return h.hexdigest()


def _micro_render(scene, cam, depsgraph, visible_objects, size=64, grid_res=None):
    """Render tiny Cycles frame, overlay ray grid for per-object brightness.

    Raycasts handle geometry. Cycles handles light transport (emissives, GI).
    Rays at grid positions identify which object each pixel region belongs to.
    Rendered pixel luminance is attributed to that object.

    grid_res adapts to mesh count: 8 (<=8), 12 (9-20), 16 (>20).
    """
    import mathutils

    # Adaptive grid resolution based on mesh count
    if grid_res is None:
        mesh_count = sum(1 for obj in scene.objects if obj.visible_get() and obj.type == 'MESH')
        if mesh_count <= 8:
            grid_res = 8
        elif mesh_count <= 20:
            grid_res = 12
        else:
            grid_res = 16

    try:
        # Check micro-render cache
        global _micro_render_cache
        scene_hash = _scene_render_hash(scene)
        if _micro_render_cache["hash"] == scene_hash and _micro_render_cache["result"] is not None:
            # Reuse cached result — still need to set brightness on visible_objects
            cached = _micro_render_cache["result"]
            obj_brightness = cached.get("_obj_brightness", {})
            for obj_data in visible_objects:
                if obj_data.get("type") not in ("MESH", None):
                    continue
                name = obj_data["name"]
                brightness = obj_brightness.get(name, 0)
                obj_data["brightness"] = round(brightness, 2)
            return {"luminance": cached["luminance"], "palette": cached["palette"]}

        render = scene.render

        # Save render settings
        orig = {
            "engine": render.engine,
            "res_x": render.resolution_x,
            "res_y": render.resolution_y,
            "res_pct": render.resolution_percentage,
            "filepath": render.filepath,
            "format": render.image_settings.file_format,
            "color_mode": render.image_settings.color_mode,
            "border": render.use_border,
            "crop": render.use_crop_to_border,
            "transparent": render.film_transparent,
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
        }
        orig_cycles_samples = scene.cycles.samples if hasattr(scene, 'cycles') else None
        orig_cycles_preview = scene.cycles.preview_samples if hasattr(scene, 'cycles') else None
        orig_cycles_denoiser = scene.cycles.use_denoising if hasattr(scene, 'cycles') else None

        try:
            # Render tiny Cycles frame — accurate light transport at 64x64
            render.engine = 'CYCLES'
            render.resolution_x = size
            render.resolution_y = size
            render.resolution_percentage = 100
            render.image_settings.file_format = 'PNG'
            render.image_settings.color_mode = 'RGB'
            render.use_border = False
            render.use_crop_to_border = False
            render.film_transparent = False
            scene.view_settings.view_transform = 'Standard'
            scene.view_settings.look = 'None'
            # 16 samples at 64x64 is fast and sufficient for luminance
            if hasattr(scene, 'cycles'):
                scene.cycles.samples = 16
                scene.cycles.use_denoising = False
                try:
                    scene.cycles.device = 'GPU'
                except Exception:
                    pass  # Falls back to CPU if no GPU available

            # Write to temp file — reading Render Result from a timer returns 0x0
            import tempfile, os
            tmp_path = os.path.join(tempfile.gettempdir(), "bw_micro_render.png")
            render.filepath = tmp_path

            bpy.ops.render.render(write_still=True)

            # Read pixels back from file
            if not os.path.exists(tmp_path):
                return None
            render_img = bpy.data.images.load(tmp_path)
            w, h = render_img.size
            pixels = list(render_img.pixels)  # flat RGBA
            bpy.data.images.remove(render_img)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        finally:
            # Restore settings individually — if one fails, others still restore
            _restore_attrs = [
                (render, "engine", orig["engine"]),
                (render, "resolution_x", orig["res_x"]),
                (render, "resolution_y", orig["res_y"]),
                (render, "resolution_percentage", orig["res_pct"]),
                (render, "filepath", orig["filepath"]),
                (render.image_settings, "file_format", orig["format"]),
                (render.image_settings, "color_mode", orig["color_mode"]),
                (render, "use_border", orig["border"]),
                (render, "use_crop_to_border", orig["crop"]),
                (render, "film_transparent", orig["transparent"]),
                (scene.view_settings, "view_transform", orig["view_transform"]),
                (scene.view_settings, "look", orig["look"]),
            ]
            for target, attr, value in _restore_attrs:
                try:
                    setattr(target, attr, value)
                except Exception:
                    pass
            if hasattr(scene, 'cycles'):
                try:
                    if orig_cycles_samples is not None:
                        scene.cycles.samples = orig_cycles_samples
                    if orig_cycles_preview is not None:
                        scene.cycles.preview_samples = orig_cycles_preview
                    if orig_cycles_denoiser is not None:
                        scene.cycles.use_denoising = orig_cycles_denoiser
                except Exception:
                    pass

        if not pixels or w == 0 or h == 0:
            return None

        # ── Ray-pixel overlay: attribute rendered brightness to objects ──
        cam_matrix = cam.matrix_world
        ray_origin = cam_matrix.translation
        rot_matrix = cam_matrix.to_3x3()
        cam_data = cam.data
        aspect = w / max(1, h)

        if cam_data.sensor_fit == 'VERTICAL':
            fy = 2 * math.atan(cam_data.sensor_height / (2 * cam_data.lens))
            fx = 2 * math.atan(math.tan(fy / 2) * aspect)
        else:
            fx = 2 * math.atan(cam_data.sensor_width / (2 * cam_data.lens))
            fy = 2 * math.atan(math.tan(fx / 2) / aspect)

        obj_lum_sum = {}
        obj_lum_count = {}
        total_lum = 0
        total_count = 0

        for gy in range(grid_res):
            for gx in range(grid_res):
                # Ray direction for this grid cell
                ndc_x = (gx + 0.5) / grid_res * 2 - 1
                ndc_y = (gy + 0.5) / grid_res * 2 - 1
                local_dir = mathutils.Vector((
                    math.tan(fx / 2) * ndc_x,
                    math.tan(fy / 2) * ndc_y,
                    -1,
                )).normalized()
                world_dir = (rot_matrix @ local_dir).normalized()

                # Which object does this cell belong to?
                try:
                    hit, loc, normal, idx, hit_obj, matrix = scene.ray_cast(
                        depsgraph, ray_origin, world_dir
                    )
                except Exception:
                    hit = False
                    hit_obj = None

                obj_name = hit_obj.name if hit and hit_obj else None

                # Sample rendered pixels in this cell's region
                px_s = int(gx * size / grid_res)
                py_s = int(gy * size / grid_res)
                px_e = int((gx + 1) * size / grid_res)
                py_e = int((gy + 1) * size / grid_res)

                cell_lum = 0
                cell_n = 0
                for py in range(py_s, min(py_e, h)):
                    for px in range(px_s, min(px_e, w)):
                        pi = (py * w + px) * 4
                        lum = 0.2126 * pixels[pi] + 0.7152 * pixels[pi+1] + 0.0722 * pixels[pi+2]
                        cell_lum += lum
                        cell_n += 1
                        total_lum += lum
                        total_count += 1

                if obj_name and cell_n > 0:
                    avg = cell_lum / cell_n
                    obj_lum_sum[obj_name] = obj_lum_sum.get(obj_name, 0) + avg
                    obj_lum_count[obj_name] = obj_lum_count.get(obj_name, 0) + 1

        # ── Small object fallback: sample rendered pixels in their bbox ──
        for obj_data in visible_objects:
            name = obj_data.get("name")
            if name in obj_lum_sum or not obj_data.get("screen_bbox"):
                continue
            if obj_data.get("type") not in ("MESH", None):
                continue
            bbox = obj_data["screen_bbox"]
            px_s = max(0, int(bbox[0] * w))
            py_s = max(0, int(bbox[1] * h))
            px_e = min(w, int(bbox[2] * w))
            py_e = min(h, int(bbox[3] * h))
            fb_lum = 0
            fb_n = 0
            for py in range(py_s, py_e):
                for px in range(px_s, px_e):
                    pi = (py * w + px) * 4
                    if pi + 2 < len(pixels):
                        fb_lum += 0.2126 * pixels[pi] + 0.7152 * pixels[pi+1] + 0.0722 * pixels[pi+2]
                        fb_n += 1
            if fb_n > 0:
                obj_lum_sum[name] = fb_lum / fb_n
                obj_lum_count[name] = 1

        # ── Set per-object brightness on visible_objects ──
        overall_lum = round(total_lum / max(total_count, 1), 3)
        obj_brightness = {}
        for name in obj_lum_sum:
            obj_brightness[name] = round(obj_lum_sum[name] / obj_lum_count[name], 3)

        for obj_data in visible_objects:
            if obj_data.get("type") not in ("MESH", None):
                continue
            name = obj_data["name"]
            brightness = obj_brightness.get(name, 0)
            # Emissive fallback: if ray grid missed this object but it has emission
            if brightness == 0:
                try:
                    obj = scene.objects.get(name)
                    if obj and obj.material_slots:
                        for slot in obj.material_slots[:1]:
                            mat = slot.material
                            if mat and mat.use_nodes:
                                for node in mat.node_tree.nodes:
                                    if node.type == 'BSDF_PRINCIPLED':
                                        es = node.inputs.get('Emission Strength')
                                        if es and not es.links and es.default_value > 0:
                                            brightness = min(1.0, es.default_value * 0.1)
                                        break
                except Exception:
                    pass
            obj_data["brightness"] = round(brightness, 2)

        # ── Dominant palette ──
        color_counts = {}
        for py in range(h):
            for px in range(w):
                pi = (py * w + px) * 4
                qr = round(pixels[pi] * 10) / 10
                qg = round(pixels[pi+1] * 10) / 10
                qb = round(pixels[pi+2] * 10) / 10
                color_counts[(qr, qg, qb)] = color_counts.get((qr, qg, qb), 0) + 1

        seen = set()
        palette = []
        for (r, g, b), _ in sorted(color_counts.items(), key=lambda x: -x[1])[:8]:
            name = _rgb_to_color_name(r, g, b)
            if name not in seen:
                seen.add(name)
                palette.append(name)
            if len(palette) >= 5:
                break

        result = {
            "luminance": overall_lum,
            "palette": palette,
        }

        # Cache result for reuse if scene hasn't changed
        _micro_render_cache["hash"] = scene_hash
        _micro_render_cache["result"] = {
            "luminance": overall_lum,
            "palette": palette,
            "_obj_brightness": obj_brightness,
        }

        return result

    except Exception as e:
        traceback.print_exc()
        return None


def compute(ctx):
    if not ctx.include_flags.get("micro_render", True) or not ctx.cam:
        for obj_data in ctx.visible_objects:
            if obj_data.get("type") not in ("MESH", None):
                continue
            obj_data["brightness"] = None
        return {}
    micro = _micro_render(ctx.scene, ctx.cam, ctx.depsgraph, ctx.visible_objects)
    return {"micro_render": micro} if micro else {}


register("micro_render", compute, emits=["micro_render"])
