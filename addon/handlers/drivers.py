"""Driver automation — add/remove/list scripted drivers."""
import bpy
import traceback


def manage_drivers(action, object_name=None, data_path=None, expression=None,
                   variables=None, target_object=None, target_data_path=None,
                   multiplier=1.0, index=-1):
    """Manage scripted drivers on objects.

    Actions:
    - add: Add driver with expression and variables
    - add_simple: One-variable driver shortcut (target_object + target_data_path → expression)
    - remove: Remove driver from data_path
    - list: List all drivers on object
    - set_expression: Update expression on existing driver
    """
    try:
        if action == "add":
            return _add_driver(object_name, data_path, expression, variables, index)
        elif action == "add_simple":
            return _add_simple_driver(object_name, data_path, target_object,
                                      target_data_path, multiplier, index)
        elif action == "remove":
            return _remove_driver(object_name, data_path, index)
        elif action == "list":
            return _list_drivers(object_name)
        elif action == "set_expression":
            return _set_expression(object_name, data_path, expression, index)
        else:
            return {"error": f"Unknown action: {action}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def _add_driver(object_name, data_path, expression, variables, index):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if not data_path:
        return {"error": "data_path is required"}
    if not expression:
        return {"error": "expression is required"}

    try:
        if index >= 0:
            fcurve = obj.driver_add(data_path, index)
        else:
            fcurve = obj.driver_add(data_path)
    except Exception as e:
        return {"error": f"Failed to add driver on '{data_path}': {str(e)}"}

    # Handle both single FCurve and list
    if isinstance(fcurve, list):
        fcurve = fcurve[0]

    driver = fcurve.driver
    driver.type = 'SCRIPTED'
    driver.expression = expression

    # Add variables
    if variables:
        for var_def in variables:
            var = driver.variables.new()
            var.name = var_def.get("name", "var")
            var.type = 'SINGLE_PROP'
            target = var.targets[0]
            target_obj_name = var_def.get("target_object")
            if target_obj_name:
                target.id = bpy.data.objects.get(target_obj_name)
            target.data_path = var_def.get("target_data_path", "")

    return {
        "success": True,
        "message": f"Added driver on '{object_name}'.{data_path}: {expression}",
        "object": object_name,
        "data_path": data_path,
        "expression": expression,
    }


def _add_simple_driver(object_name, data_path, target_object, target_data_path,
                        multiplier, index):
    if not target_object or not target_data_path:
        return {"error": "target_object and target_data_path are required"}

    if multiplier == 1.0:
        expression = "var"
    else:
        expression = f"var * {multiplier}"

    variables = [{
        "name": "var",
        "target_object": target_object,
        "target_data_path": target_data_path,
    }]

    return _add_driver(object_name, data_path, expression, variables, index)


def _remove_driver(object_name, data_path, index):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if not data_path:
        return {"error": "data_path is required"}

    try:
        if index >= 0:
            result = obj.driver_remove(data_path, index)
        else:
            result = obj.driver_remove(data_path)
    except Exception as e:
        return {"error": f"Failed to remove driver: {str(e)}"}

    return {
        "success": True,
        "message": f"Removed driver from '{object_name}'.{data_path}",
        "removed": result,
    }


def _list_drivers(object_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    drivers = []
    if obj.animation_data and obj.animation_data.drivers:
        for fcurve in obj.animation_data.drivers:
            driver = fcurve.driver
            var_list = []
            for var in driver.variables:
                var_info = {
                    "name": var.name,
                    "type": var.type,
                }
                if var.targets:
                    t = var.targets[0]
                    var_info["target_object"] = t.id.name if t.id else None
                    var_info["target_data_path"] = t.data_path
                var_list.append(var_info)

            drivers.append({
                "data_path": fcurve.data_path,
                "array_index": fcurve.array_index,
                "expression": driver.expression,
                "type": driver.type,
                "variables": var_list,
            })

    return {
        "success": True,
        "object": object_name,
        "drivers": drivers,
        "count": len(drivers),
    }


def _set_expression(object_name, data_path, expression, index):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if not data_path or not expression:
        return {"error": "data_path and expression are required"}

    if not obj.animation_data or not obj.animation_data.drivers:
        return {"error": f"No drivers found on '{object_name}'"}

    for fcurve in obj.animation_data.drivers:
        if fcurve.data_path == data_path:
            if index >= 0 and fcurve.array_index != index:
                continue
            fcurve.driver.expression = expression
            return {
                "success": True,
                "message": f"Updated expression on '{object_name}'.{data_path}: {expression}",
            }

    return {"error": f"No driver found on '{object_name}'.{data_path}"}
