"""Custom property management on Blender objects."""
import bpy
import traceback


def manage_custom_properties(action, object_name=None, prop_name=None,
                              value=None, description=""):
    """Manage custom properties on objects.

    Actions:
    - set: Set/create a custom property
    - get: Get a custom property value
    - list: List all custom properties
    - remove: Delete a custom property
    """
    try:
        if action == "set":
            return _set_prop(object_name, prop_name, value, description)
        elif action == "get":
            return _get_prop(object_name, prop_name)
        elif action == "list":
            return _list_props(object_name)
        elif action == "remove":
            return _remove_prop(object_name, prop_name)
        else:
            return {"error": f"Unknown action: {action}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def _set_prop(object_name, prop_name, value, description):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if not prop_name:
        return {"error": "prop_name is required"}

    obj[prop_name] = value

    # Set description if provided
    if description:
        try:
            obj.id_properties_ui(prop_name).update(description=description)
        except Exception:
            pass  # id_properties_ui may not exist for all types

    return {
        "success": True,
        "message": f"Set '{prop_name}' = {value} on '{object_name}'",
        "object": object_name,
        "property": prop_name,
        "value": value,
    }


def _get_prop(object_name, prop_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if not prop_name:
        return {"error": "prop_name is required"}

    if prop_name not in obj:
        return {"error": f"Property '{prop_name}' not found on '{object_name}'"}

    value = obj[prop_name]
    # Convert IDPropertyArray to list for JSON serialization
    try:
        value = list(value)
    except (TypeError, ValueError):
        pass

    return {
        "success": True,
        "object": object_name,
        "property": prop_name,
        "value": value,
    }


def _list_props(object_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    props = {}
    for key in obj.keys():
        # Skip internal RNA properties
        if key.startswith("_"):
            continue
        value = obj[key]
        try:
            value = list(value)
        except (TypeError, ValueError):
            pass
        props[key] = value

    return {
        "success": True,
        "object": object_name,
        "properties": props,
        "count": len(props),
    }


def _remove_prop(object_name, prop_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if not prop_name:
        return {"error": "prop_name is required"}

    if prop_name not in obj:
        return {"error": f"Property '{prop_name}' not found on '{object_name}'"}

    del obj[prop_name]

    return {
        "success": True,
        "message": f"Removed property '{prop_name}' from '{object_name}'",
        "object": object_name,
        "property": prop_name,
    }
