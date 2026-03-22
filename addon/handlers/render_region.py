"""Render region analysis — render a specific region at high quality.

10-50x faster than full-frame for material/detail checks.
"""
import bpy
import traceback
import tempfile
import os
import uuid
import base64
import math


def render_region(object_name=None, bbox=None, resolution=512,
                  samples=None, format="JPEG", quality=80):
    """Render just a region of the frame at high quality.

    Args:
        object_name: Name of object to render around (auto-computes bbox)
        bbox: Manual region [x1, y1, x2, y2] in 0-1 NDC coordinates
        resolution: Max dimension of the rendered region in pixels (default 512)
        samples: Override render samples (None = use scene default)
        format: Output format — JPEG or PNG (default JPEG)
        quality: JPEG quality 1-100 (default 80)

    Returns:
        dict with base64 image and telemetry for the region
    """
    try:
        scene = bpy.context.scene
        cam = scene.camera
        if not cam:
            return {"error": "No active camera in scene"}

        # Compute region bbox
        if object_name:
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            bbox = _object_screen_bbox(obj, scene)
            if not bbox:
                return {"error": f"Object '{object_name}' not visible from camera"}
            # Add padding (10%)
            pad_x = (bbox[2] - bbox[0]) * 0.1
            pad_y = (bbox[3] - bbox[1]) * 0.1
            bbox = [
                max(0, bbox[0] - pad_x),
                max(0, bbox[1] - pad_y),
                min(1, bbox[2] + pad_x),
                min(1, bbox[3] + pad_y),
            ]
        elif bbox:
            if len(bbox) != 4:
                return {"error": "bbox must be [x1, y1, x2, y2] in 0-1 NDC"}
        else:
            return {"error": "Either object_name or bbox is required"}

        # Store original render settings
        render = scene.render
        orig_border = render.use_border
        orig_crop = render.use_crop_to_border
        orig_min_x = render.border_min_x
        orig_min_y = render.border_min_y
        orig_max_x = render.border_max_x
        orig_max_y = render.border_max_y
        orig_res_x = render.resolution_x
        orig_res_y = render.resolution_y
        orig_filepath = render.filepath
        orig_format = render.image_settings.file_format
        orig_quality = render.image_settings.quality

        try:
            # Set border region
            render.use_border = True
            render.use_crop_to_border = True
            render.border_min_x = bbox[0]
            render.border_min_y = bbox[1]
            render.border_max_x = bbox[2]
            render.border_max_y = bbox[3]

            # Scale resolution to fit the region
            region_w = bbox[2] - bbox[0]
            region_h = bbox[3] - bbox[1]
            aspect = region_w / max(region_h, 0.001)

            if aspect >= 1:
                render.resolution_x = resolution
                render.resolution_y = max(1, int(resolution / aspect))
            else:
                render.resolution_y = resolution
                render.resolution_x = max(1, int(resolution * aspect))

            # Set output
            temp_path = os.path.join(
                tempfile.gettempdir(),
                f"blenderweave_region_{uuid.uuid4().hex[:8]}"
            )
            if format.upper() == "JPEG":
                temp_path += ".jpg"
                render.image_settings.file_format = 'JPEG'
                render.image_settings.quality = quality
            else:
                temp_path += ".png"
                render.image_settings.file_format = 'PNG'

            render.filepath = temp_path

            # Override samples if requested
            orig_samples = None
            if samples is not None:
                if render.engine == 'CYCLES':
                    orig_samples = scene.cycles.samples
                    scene.cycles.samples = samples
                elif hasattr(scene, 'eevee') and hasattr(scene.eevee, 'taa_render_samples'):
                    orig_samples = scene.eevee.taa_render_samples
                    scene.eevee.taa_render_samples = samples

            # Render
            bpy.ops.render.render(write_still=True)

            # Read result
            if os.path.exists(temp_path):
                with open(temp_path, 'rb') as f:
                    img_data = f.read()
                img_b64 = base64.b64encode(img_data).decode('ascii')
                os.remove(temp_path)
            else:
                img_b64 = None

            result = {
                "success": True,
                "message": f"Region rendered ({render.resolution_x}x{render.resolution_y})",
                "region": bbox,
                "resolution": [render.resolution_x, render.resolution_y],
                "format": format.upper(),
            }

            if img_b64:
                result["image"] = img_b64
                result["size_bytes"] = len(img_data)

            if object_name:
                result["object_name"] = object_name

            return result

        finally:
            # Restore all settings
            render.use_border = orig_border
            render.use_crop_to_border = orig_crop
            render.border_min_x = orig_min_x
            render.border_min_y = orig_min_y
            render.border_max_x = orig_max_x
            render.border_max_y = orig_max_y
            render.resolution_x = orig_res_x
            render.resolution_y = orig_res_y
            render.filepath = orig_filepath
            render.image_settings.file_format = orig_format
            render.image_settings.quality = orig_quality

            if orig_samples is not None:
                if render.engine == 'CYCLES':
                    scene.cycles.samples = orig_samples
                elif hasattr(scene, 'eevee'):
                    scene.eevee.taa_render_samples = orig_samples

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Region render failed: {str(e)}"}


def _object_screen_bbox(obj, scene):
    """Get object's screen-space bounding box [x1, y1, x2, y2] in 0-1 NDC."""
    cam = scene.camera
    if not cam:
        return None

    try:
        import mathutils
        from bpy_extras.object_utils import world_to_camera_view

        corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
        screen_coords = []
        for corner in corners:
            co = world_to_camera_view(scene, cam, corner)
            if co.z > 0:
                screen_coords.append((co.x, co.y))

        if not screen_coords:
            return None

        xs = [c[0] for c in screen_coords]
        ys = [c[1] for c in screen_coords]

        return [
            max(0, min(xs)),
            max(0, min(ys)),
            min(1, max(xs)),
            min(1, max(ys)),
        ]
    except Exception:
        return None
