import bpy
import traceback

from ._utils import ensure_object_mode, select_only, set_properties_safe


def modify_object(object_name, action, modifier_type=None, modifier_name=None, properties=None):
    """Unified modifier operations: add, remove, apply, set properties, list.

    Args:
        object_name: Name of the Blender object
        action: "add_modifier" | "remove_modifier" | "apply_modifier" | "set_modifier" | "list_modifiers"
        modifier_type: Blender modifier type (e.g. SUBSURF, BOOLEAN, ARRAY, MIRROR, BEVEL, SOLIDIFY)
        modifier_name: Name of existing modifier (for remove/apply/set)
        properties: dict of modifier properties to set

    Returns:
        dict with success status
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}

        if action == "add_modifier":
            if not modifier_type:
                return {"error": "modifier_type is required for add_modifier"}
            name = modifier_name or modifier_type.title()
            mod = obj.modifiers.new(name=name, type=modifier_type)
            result = {
                "success": True,
                "message": f"Added {modifier_type} modifier '{mod.name}' to {object_name}",
                "modifier_name": mod.name,
            }
            if properties:
                set_props, failed = set_properties_safe(mod, properties)
                result["properties_set"] = set_props
                if failed:
                    result["properties_failed"] = failed
            return result

        elif action == "remove_modifier":
            if not modifier_name:
                return {"error": "modifier_name is required for remove_modifier"}
            mod = obj.modifiers.get(modifier_name)
            if not mod:
                return {"error": f"Modifier not found: {modifier_name}"}
            obj.modifiers.remove(mod)
            return {
                "success": True,
                "message": f"Removed modifier '{modifier_name}' from {object_name}",
            }

        elif action == "apply_modifier":
            if not modifier_name:
                return {"error": "modifier_name is required for apply_modifier"}
            mod = obj.modifiers.get(modifier_name)
            if not mod:
                return {"error": f"Modifier not found: {modifier_name}"}
            with ensure_object_mode(obj):
                select_only(obj)
                bpy.ops.object.modifier_apply(modifier=modifier_name)
            return {
                "success": True,
                "message": f"Applied modifier '{modifier_name}' on {object_name}",
            }

        elif action == "set_modifier":
            if not modifier_name:
                return {"error": "modifier_name is required for set_modifier"}
            mod = obj.modifiers.get(modifier_name)
            if not mod:
                return {"error": f"Modifier not found: {modifier_name}"}
            if not properties:
                return {"error": "properties dict is required for set_modifier"}
            set_props, failed = set_properties_safe(mod, properties)
            result = {
                "success": True,
                "message": f"Updated modifier '{modifier_name}' on {object_name}",
                "properties_set": set_props,
            }
            if failed:
                result["properties_failed"] = failed
            return result

        elif action == "list_modifiers":
            modifiers_list = []
            for i, mod in enumerate(obj.modifiers):
                mod_info = {
                    "index": i,
                    "name": mod.name,
                    "type": mod.type,
                    "show_viewport": mod.show_viewport,
                    "show_render": mod.show_render,
                }
                # Collect modifier-specific properties
                props = {}
                for prop in mod.bl_rna.properties:
                    if prop.identifier in ('rna_type', 'name', 'type',
                                           'show_viewport', 'show_render',
                                           'show_expanded', 'is_active',
                                           'show_in_editmode', 'show_on_cage'):
                        continue
                    if prop.is_readonly:
                        continue
                    try:
                        val = getattr(mod, prop.identifier)
                        if hasattr(val, '__iter__') and not isinstance(val, str):
                            val = list(val)
                        # Skip non-serializable
                        if isinstance(val, (int, float, bool, str, list, type(None))):
                            props[prop.identifier] = val
                        elif hasattr(val, 'name'):
                            props[prop.identifier] = val.name
                    except Exception:
                        pass
                if props:
                    mod_info["properties"] = props
                modifiers_list.append(mod_info)
            return {
                "success": True,
                "object_name": object_name,
                "modifiers": modifiers_list,
                "total": len(modifiers_list),
            }

        else:
            return {"error": f"Unknown action: {action}. Use add_modifier, remove_modifier, "
                    "apply_modifier, set_modifier, or list_modifiers"}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Modifier operation failed: {str(e)}"}
