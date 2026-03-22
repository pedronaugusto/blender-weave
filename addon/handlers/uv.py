import bpy
import math
import traceback


def uv_operation(object_name, action, uv_layer_name=None,
                 island_margin=0.02, angle_limit=66.0):
    """UV mapping operations: unwrap, smart project, lightmap pack, layer management.

    Args:
        object_name: Name of the mesh object
        action: Operation —
            "smart_project" — Smart UV Project with angle_limit and island_margin
            "lightmap_pack" — Lightmap Pack UV (for baked lighting)
            "unwrap" — standard unwrap (assumes seams already marked)
            "create_layer" — create new UV layer with uv_layer_name
            "set_active" — set active UV layer by uv_layer_name
            "list" — list all UV layers on object
        uv_layer_name: Name for UV layer (create_layer, set_active)
        island_margin: Margin between UV islands (default 0.02)
        angle_limit: Angle limit in degrees for smart_project (default 66.0)

    Returns:
        dict with operation result
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != 'MESH':
            return {"error": f"Object '{object_name}' is not a mesh"}

        if action == "smart_project":
            return _smart_project(obj, island_margin, angle_limit)
        elif action == "lightmap_pack":
            return _lightmap_pack(obj, island_margin)
        elif action == "unwrap":
            return _unwrap(obj, island_margin)
        elif action == "create_layer":
            return _create_layer(obj, uv_layer_name)
        elif action == "set_active":
            return _set_active_layer(obj, uv_layer_name)
        elif action == "list":
            return _list_layers(obj)
        else:
            return {"error": f"Unknown action: {action}. Use: smart_project, "
                    "lightmap_pack, unwrap, create_layer, set_active, list"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"UV operation failed: {str(e)}"}


def _enter_edit_mode(obj):
    """Select only this object and enter edit mode with all selected."""
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')


def _exit_edit_mode():
    bpy.ops.object.mode_set(mode='OBJECT')


def _smart_project(obj, island_margin, angle_limit):
    _enter_edit_mode(obj)
    try:
        bpy.ops.uv.smart_project(
            angle_limit=math.radians(angle_limit),
            island_margin=island_margin,
        )
    finally:
        _exit_edit_mode()

    active_uv = obj.data.uv_layers.active.name if obj.data.uv_layers.active else None
    return {
        "success": True,
        "message": f"Smart UV Project applied on '{obj.name}'",
        "uv_layer": active_uv,
        "angle_limit": angle_limit,
        "island_margin": island_margin,
    }


def _lightmap_pack(obj, island_margin):
    _enter_edit_mode(obj)
    try:
        bpy.ops.uv.lightmap_pack(PREF_MARGIN_DIV=island_margin)
    finally:
        _exit_edit_mode()

    active_uv = obj.data.uv_layers.active.name if obj.data.uv_layers.active else None
    return {
        "success": True,
        "message": f"Lightmap Pack applied on '{obj.name}'",
        "uv_layer": active_uv,
    }


def _unwrap(obj, island_margin):
    _enter_edit_mode(obj)
    try:
        bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=island_margin)
    finally:
        _exit_edit_mode()

    active_uv = obj.data.uv_layers.active.name if obj.data.uv_layers.active else None
    return {
        "success": True,
        "message": f"UV Unwrap applied on '{obj.name}'",
        "uv_layer": active_uv,
    }


def _create_layer(obj, uv_layer_name):
    if not uv_layer_name:
        return {"error": "uv_layer_name is required for create_layer"}

    uv_layer = obj.data.uv_layers.new(name=uv_layer_name)
    return {
        "success": True,
        "message": f"Created UV layer '{uv_layer.name}' on '{obj.name}'",
        "uv_layer": uv_layer.name,
        "total_layers": len(obj.data.uv_layers),
    }


def _set_active_layer(obj, uv_layer_name):
    if not uv_layer_name:
        return {"error": "uv_layer_name is required for set_active"}

    uv_layer = obj.data.uv_layers.get(uv_layer_name)
    if not uv_layer:
        return {"error": f"UV layer not found: {uv_layer_name}"}

    obj.data.uv_layers.active = uv_layer
    return {
        "success": True,
        "message": f"Set active UV layer to '{uv_layer_name}' on '{obj.name}'",
    }


def _list_layers(obj):
    layers = []
    for uv in obj.data.uv_layers:
        layers.append({
            "name": uv.name,
            "active": uv == obj.data.uv_layers.active,
            "active_render": uv.active_render,
        })

    return {
        "success": True,
        "object_name": obj.name,
        "uv_layers": layers,
        "total": len(layers),
    }
