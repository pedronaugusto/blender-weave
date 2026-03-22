import bpy
import traceback

from ._utils import select_only, ensure_object_mode, ensure_edit_mode, require_mesh


def mesh_operation(action, object_names=None, target_object=None,
                   boolean_object=None, boolean_mode=None,
                   voxel_size=0.1, separate_mode="LOOSE",
                   boolean_list=None, delete_tool_object=False):
    """Perform mesh operations: join, separate, boolean, shading, transforms, origin, remesh, batch_boolean.

    Args:
        action: Operation to perform —
            "join" — merge object_names into target_object
            "separate" — separate target_object by LOOSE parts or MATERIAL
            "boolean" — boolean target_object with boolean_object
            "batch_boolean" — apply multiple booleans sequentially
            "shade_smooth" — set smooth shading on target_object
            "shade_flat" — set flat shading on target_object
            "apply_transforms" — apply location/rotation/scale
            "origin_to_geometry" — move origin to geometry center
            "origin_to_center" — move origin to bounding box center
            "remesh" — voxel remesh at given voxel_size
        object_names: List of object names (for join)
        target_object: Primary object name
        boolean_object: Second object for boolean operations
        boolean_mode: Boolean mode — UNION, DIFFERENCE, INTERSECT
        voxel_size: Voxel size for remesh (default 0.1)
        separate_mode: Separation mode — LOOSE or MATERIAL
        boolean_list: List of {boolean_object, boolean_mode} dicts (for batch_boolean)
        delete_tool_object: Delete boolean tool objects after operation (default False)

    Returns:
        dict with operation result
    """
    try:
        if action == "join":
            return _join(object_names, target_object)
        elif action == "separate":
            return _separate(target_object, separate_mode)
        elif action == "boolean":
            return _boolean(target_object, boolean_object, boolean_mode, delete_tool_object)
        elif action == "batch_boolean":
            return _batch_boolean(target_object, boolean_list, delete_tool_object)
        elif action == "shade_smooth":
            return _set_shading(target_object, smooth=True)
        elif action == "shade_flat":
            return _set_shading(target_object, smooth=False)
        elif action == "apply_transforms":
            return _apply_transforms(target_object)
        elif action == "origin_to_geometry":
            return _set_origin(target_object, "ORIGIN_GEOMETRY")
        elif action == "origin_to_center":
            return _set_origin(target_object, "ORIGIN_CENTER_OF_VOLUME")
        elif action == "remesh":
            return _remesh(target_object, voxel_size)
        else:
            return {"error": f"Unknown action: {action}. Use: join, separate, boolean, "
                    "batch_boolean, shade_smooth, shade_flat, apply_transforms, "
                    "origin_to_geometry, origin_to_center, remesh"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Mesh operation failed: {str(e)}"}


def _join(object_names, target_object):
    if not object_names or not target_object:
        return {"error": "object_names and target_object are required for join"}

    target = bpy.data.objects.get(target_object)
    if not target:
        return {"error": f"Target object not found: {target_object}"}

    bpy.ops.object.select_all(action='DESELECT')
    for name in object_names:
        obj = bpy.data.objects.get(name)
        if obj:
            obj.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target

    with ensure_object_mode(target):
        bpy.ops.object.join()

    poly_count = len(target.data.polygons) if target.data else 0
    return {
        "success": True,
        "message": f"Joined {len(object_names)} objects into '{target.name}'",
        "result_name": target.name,
        "polygon_count": poly_count,
    }


def _separate(target_object, mode):
    if not target_object:
        return {"error": "target_object is required for separate"}
    obj = bpy.data.objects.get(target_object)
    if not obj:
        return {"error": f"Object not found: {target_object}"}

    before = set(bpy.data.objects.keys())

    with ensure_edit_mode(obj):
        if mode == "LOOSE":
            bpy.ops.mesh.separate(type='LOOSE')
        elif mode == "MATERIAL":
            bpy.ops.mesh.separate(type='MATERIAL')
        else:
            return {"error": f"Unknown separate_mode: {mode}. Use LOOSE or MATERIAL"}

    after = set(bpy.data.objects.keys())
    new_names = list(after - before)

    return {
        "success": True,
        "message": f"Separated '{target_object}' by {mode}",
        "new_objects": new_names,
        "total_parts": len(new_names) + 1,
    }


def _boolean(target_object, boolean_object, boolean_mode, delete_tool=False):
    if not target_object or not boolean_object:
        return {"error": "target_object and boolean_object are required for boolean"}
    if not boolean_mode or boolean_mode not in ("UNION", "DIFFERENCE", "INTERSECT"):
        return {"error": "boolean_mode must be UNION, DIFFERENCE, or INTERSECT"}

    target = bpy.data.objects.get(target_object)
    if not target:
        return {"error": f"Target object not found: {target_object}"}
    bool_obj = bpy.data.objects.get(boolean_object)
    if not bool_obj:
        return {"error": f"Boolean object not found: {boolean_object}"}

    mod = target.modifiers.new(name="Boolean", type='BOOLEAN')
    mod.operation = boolean_mode
    mod.object = bool_obj

    with ensure_object_mode(target):
        select_only(target)
        bpy.ops.object.modifier_apply(modifier=mod.name)

    if delete_tool:
        bpy.data.objects.remove(bool_obj, do_unlink=True)

    poly_count = len(target.data.polygons) if target.data else 0
    return {
        "success": True,
        "message": f"Boolean {boolean_mode} applied: '{target_object}' with '{boolean_object}'",
        "result_name": target.name,
        "polygon_count": poly_count,
    }


def _batch_boolean(target_object, boolean_list, delete_tool=False):
    if not target_object:
        return {"error": "target_object is required for batch_boolean"}
    if not boolean_list or not isinstance(boolean_list, list):
        return {"error": "boolean_list is required: [{boolean_object, boolean_mode}, ...]"}

    target = bpy.data.objects.get(target_object)
    if not target:
        return {"error": f"Target object not found: {target_object}"}

    results = []
    for i, entry in enumerate(boolean_list):
        bool_obj_name = entry.get("boolean_object")
        bool_mode = entry.get("boolean_mode")
        if not bool_obj_name or not bool_mode:
            results.append({"index": i, "error": "boolean_object and boolean_mode required"})
            continue
        if bool_mode not in ("UNION", "DIFFERENCE", "INTERSECT"):
            results.append({"index": i, "error": f"Invalid boolean_mode: {bool_mode}"})
            continue

        bool_obj = bpy.data.objects.get(bool_obj_name)
        if not bool_obj:
            results.append({"index": i, "error": f"Object not found: {bool_obj_name}"})
            continue

        mod = target.modifiers.new(name=f"Boolean_{i}", type='BOOLEAN')
        mod.operation = bool_mode
        mod.object = bool_obj

        with ensure_object_mode(target):
            select_only(target)
            bpy.ops.object.modifier_apply(modifier=mod.name)

        poly_count = len(target.data.polygons) if target.data else 0

        if delete_tool:
            bpy.data.objects.remove(bool_obj, do_unlink=True)

        results.append({
            "index": i,
            "boolean_object": bool_obj_name,
            "boolean_mode": bool_mode,
            "polygon_count": poly_count,
        })

    final_polys = len(target.data.polygons) if target.data else 0
    return {
        "success": True,
        "message": f"Applied {len(boolean_list)} boolean operations on '{target_object}'",
        "result_name": target.name,
        "polygon_count": final_polys,
        "operations": results,
    }


def _set_shading(target_object, smooth=True):
    if not target_object:
        return {"error": "target_object is required"}
    obj, err = require_mesh(target_object)
    if err:
        return err

    with ensure_object_mode(obj):
        select_only(obj)
        if smooth:
            bpy.ops.object.shade_smooth()
        else:
            bpy.ops.object.shade_flat()

    return {
        "success": True,
        "message": f"Set {'smooth' if smooth else 'flat'} shading on '{target_object}'",
    }


def _apply_transforms(target_object):
    if not target_object:
        return {"error": "target_object is required"}
    obj = bpy.data.objects.get(target_object)
    if not obj:
        return {"error": f"Object not found: {target_object}"}

    with ensure_object_mode(obj):
        select_only(obj)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    return {
        "success": True,
        "message": f"Applied transforms on '{target_object}'",
        "location": list(obj.location),
        "rotation": list(obj.rotation_euler),
        "scale": list(obj.scale),
    }


def _set_origin(target_object, origin_type):
    if not target_object:
        return {"error": "target_object is required"}
    obj = bpy.data.objects.get(target_object)
    if not obj:
        return {"error": f"Object not found: {target_object}"}

    with ensure_object_mode(obj):
        select_only(obj)
        bpy.ops.object.origin_set(type=origin_type)

    return {
        "success": True,
        "message": f"Set origin ({origin_type}) on '{target_object}'",
        "location": list(obj.location),
    }


def _remesh(target_object, voxel_size):
    if not target_object:
        return {"error": "target_object is required"}
    obj, err = require_mesh(target_object)
    if err:
        return err

    with ensure_object_mode(obj):
        select_only(obj)
        obj.data.remesh_voxel_size = voxel_size
        bpy.ops.object.voxel_remesh()

    poly_count = len(obj.data.polygons)
    return {
        "success": True,
        "message": f"Voxel remesh applied on '{target_object}' (voxel_size={voxel_size})",
        "polygon_count": poly_count,
    }
