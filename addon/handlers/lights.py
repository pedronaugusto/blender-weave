"""Dedicated light management for BlenderWeave."""
import bpy
import traceback


def manage_lights(action, light_name=None, **kwargs):
    """Manage scene lights with full control.

    Args:
        action: Operation —
            "list" — list all lights with properties
            "set_properties" — set light properties (energy, color, type, shadow, size, etc.)
            "change_type" — change light type without delete+recreate
            "get_properties" — get all properties of a light
        light_name: Name of the light object
        kwargs: Additional parameters:
            For set_properties:
                energy (float), color [r,g,b], shadow_soft_size (float),
                use_shadow (bool), spot_size (float), spot_blend (float),
                spread (float), size (float)
            For change_type:
                new_type: POINT, SUN, SPOT, AREA

    Returns:
        dict with operation result
    """
    try:
        if action == "list":
            return _list_lights()
        elif action == "set_properties":
            return _set_light_properties(light_name, kwargs)
        elif action == "change_type":
            return _change_light_type(light_name, kwargs.get("new_type"))
        elif action == "get_properties":
            return _get_light_properties(light_name)
        else:
            return {"error": f"Unknown action: {action}. Use: list, set_properties, change_type, get_properties"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Light operation failed: {str(e)}"}


def _list_lights():
    """List all lights in the scene with key properties."""
    lights = []
    for obj in bpy.context.scene.objects:
        if obj.type != 'LIGHT':
            continue
        light = obj.data
        info = {
            "name": obj.name,
            "type": light.type,
            "energy": light.energy,
            "color": [round(c, 3) for c in light.color],
            "location": [round(v, 3) for v in obj.location],
            "use_shadow": light.use_shadow,
            "visible": obj.visible_get(),
        }
        if light.type == 'SPOT':
            info["spot_size"] = light.spot_size
            info["spot_blend"] = light.spot_blend
        elif light.type == 'AREA':
            info["shape"] = light.shape
            info["size"] = light.size
        elif light.type == 'SUN':
            info["angle"] = light.angle
        elif light.type == 'POINT':
            info["shadow_soft_size"] = light.shadow_soft_size
        lights.append(info)

    return {
        "success": True,
        "lights": lights,
        "count": len(lights),
    }


def _get_light_properties(light_name):
    """Get all properties of a specific light."""
    if not light_name:
        return {"error": "light_name is required"}

    obj = bpy.data.objects.get(light_name)
    if not obj or obj.type != 'LIGHT':
        return {"error": f"Light not found: {light_name}"}

    light = obj.data
    props = {
        "name": obj.name,
        "type": light.type,
        "energy": light.energy,
        "color": [round(c, 3) for c in light.color],
        "use_shadow": light.use_shadow,
        "location": [round(v, 3) for v in obj.location],
        "rotation": [round(v, 3) for v in obj.rotation_euler],
        "visible": obj.visible_get(),
    }

    if light.type == 'SPOT':
        props.update({
            "spot_size": light.spot_size,
            "spot_blend": light.spot_blend,
            "shadow_soft_size": light.shadow_soft_size,
            "show_cone": light.show_cone,
        })
    elif light.type == 'AREA':
        props.update({
            "shape": light.shape,
            "size": light.size,
            "size_y": light.size_y if light.shape in ('RECTANGLE', 'ELLIPSE') else None,
            "spread": light.spread,
        })
    elif light.type == 'SUN':
        props.update({
            "angle": light.angle,
        })
    elif light.type == 'POINT':
        props.update({
            "shadow_soft_size": light.shadow_soft_size,
        })

    return {
        "success": True,
        "properties": props,
    }


def _set_light_properties(light_name, props):
    """Set properties on a light object."""
    if not light_name:
        return {"error": "light_name is required"}

    obj = bpy.data.objects.get(light_name)
    if not obj or obj.type != 'LIGHT':
        return {"error": f"Light not found: {light_name}"}

    light = obj.data
    changed = []

    if "energy" in props:
        light.energy = props["energy"]
        changed.append("energy")

    if "color" in props:
        c = props["color"]
        light.color = (c[0], c[1], c[2])
        changed.append("color")

    if "use_shadow" in props:
        light.use_shadow = props["use_shadow"]
        changed.append("use_shadow")

    if "shadow_soft_size" in props:
        light.shadow_soft_size = props["shadow_soft_size"]
        changed.append("shadow_soft_size")

    if "spot_size" in props and light.type == 'SPOT':
        light.spot_size = props["spot_size"]
        changed.append("spot_size")

    if "spot_blend" in props and light.type == 'SPOT':
        light.spot_blend = props["spot_blend"]
        changed.append("spot_blend")

    if "size" in props and light.type == 'AREA':
        light.size = props["size"]
        changed.append("size")

    if "size_y" in props and light.type == 'AREA':
        light.size_y = props["size_y"]
        changed.append("size_y")

    if "spread" in props and light.type == 'AREA':
        light.spread = props["spread"]
        changed.append("spread")

    if "angle" in props and light.type == 'SUN':
        light.angle = props["angle"]
        changed.append("angle")

    if "shape" in props and light.type == 'AREA':
        light.shape = props["shape"]
        changed.append("shape")

    return {
        "success": True,
        "message": f"Updated {len(changed)} properties on '{light_name}'",
        "changed": changed,
    }


def _change_light_type(light_name, new_type):
    """Change a light's type without deleting and recreating."""
    if not light_name:
        return {"error": "light_name is required"}
    if not new_type:
        return {"error": "new_type is required (POINT, SUN, SPOT, AREA)"}

    new_type = new_type.upper()
    valid_types = ('POINT', 'SUN', 'SPOT', 'AREA')
    if new_type not in valid_types:
        return {"error": f"Invalid light type: {new_type}. Options: {', '.join(valid_types)}"}

    obj = bpy.data.objects.get(light_name)
    if not obj or obj.type != 'LIGHT':
        return {"error": f"Light not found: {light_name}"}

    old_type = obj.data.type
    obj.data.type = new_type

    return {
        "success": True,
        "message": f"Changed '{light_name}' from {old_type} to {new_type}",
        "old_type": old_type,
        "new_type": new_type,
    }
