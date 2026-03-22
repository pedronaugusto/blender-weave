"""Viewport control operations for BlenderWeave."""
import bpy
import traceback


def set_viewport(action, **kwargs):
    """Control viewport state.

    Args:
        action: Operation —
            "lock_camera" — lock/unlock viewport to camera view
            "set_view" — set viewport to preset view (FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, CAMERA)
            "frame_selected" — frame selected objects in viewport
            "frame_all" — frame all objects in viewport
            "toggle_overlays" — toggle viewport overlays on/off
            "set_overlays" — set specific overlay properties
            "get_state" — get current viewport state
        kwargs: Additional parameters per action:
            For lock_camera: locked (bool)
            For set_view: view (str)
            For set_overlays: properties dict (show_floor, show_axis_x, show_axis_y, show_axis_z,
                             show_wireframes, show_face_orientation, show_bones, etc.)

    Returns:
        dict with operation result
    """
    try:
        area = None
        for a in bpy.context.screen.areas:
            if a.type == 'VIEW_3D':
                area = a
                break
        if not area:
            return {"error": "No 3D viewport found"}

        space = area.spaces[0]
        region = None
        for r in area.regions:
            if r.type == 'WINDOW':
                region = r
                break

        if action == "lock_camera":
            locked = kwargs.get("locked", True)
            space.lock_camera = locked
            return {
                "success": True,
                "message": f"Camera {'locked' if locked else 'unlocked'} to viewport",
                "locked": locked,
            }

        elif action == "set_view":
            view = kwargs.get("view", "CAMERA").upper()
            view_map = {
                "FRONT": 'FRONT',
                "BACK": 'BACK',
                "LEFT": 'LEFT',
                "RIGHT": 'RIGHT',
                "TOP": 'TOP',
                "BOTTOM": 'BOTTOM',
                "CAMERA": 'CAMERA',
            }
            if view not in view_map:
                return {"error": f"Unknown view: {view}. Options: {', '.join(view_map.keys())}"}

            with bpy.context.temp_override(area=area, region=region):
                if view == 'CAMERA':
                    bpy.ops.view3d.view_camera()
                else:
                    bpy.ops.view3d.view_axis(type=view)

            return {
                "success": True,
                "message": f"Viewport set to {view} view",
                "view": view,
            }

        elif action == "frame_selected":
            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.view3d.view_selected()
            return {
                "success": True,
                "message": "Viewport framed to selected objects",
            }

        elif action == "frame_all":
            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.view3d.view_all()
            return {
                "success": True,
                "message": "Viewport framed to all objects",
            }

        elif action == "toggle_overlays":
            space.overlay.show_overlays = not space.overlay.show_overlays
            return {
                "success": True,
                "message": f"Overlays {'enabled' if space.overlay.show_overlays else 'disabled'}",
                "overlays_enabled": space.overlay.show_overlays,
            }

        elif action == "set_overlays":
            properties = kwargs.get("properties", {})
            if not properties:
                return {"error": "properties dict required for set_overlays"}

            changed = []
            overlay = space.overlay
            for key, val in properties.items():
                if hasattr(overlay, key):
                    setattr(overlay, key, val)
                    changed.append(key)

            return {
                "success": True,
                "message": f"Updated {len(changed)} overlay properties",
                "changed": changed,
            }

        elif action == "get_state":
            rv3d = space.region_3d
            state = {
                "shading_type": space.shading.type,
                "lock_camera": space.lock_camera,
                "overlays_enabled": space.overlay.show_overlays,
                "show_gizmo": space.show_gizmo,
                "view_perspective": rv3d.view_perspective if rv3d else None,
                "is_camera_view": rv3d.view_perspective == 'CAMERA' if rv3d else False,
            }
            return {
                "success": True,
                "state": state,
            }

        else:
            return {"error": f"Unknown action: {action}. Use: lock_camera, set_view, "
                    "frame_selected, frame_all, toggle_overlays, set_overlays, get_state"}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Viewport operation failed: {str(e)}"}
