import bpy
import traceback


def manage_selection(action, object_name=None, object_type=None,
                     collection_name=None):
    """Manage object selection in the scene.

    Args:
        action: Operation —
            "select" — select a single object by name
            "deselect" — deselect a single object by name
            "select_all" — select all objects
            "deselect_all" — deselect all objects
            "select_by_type" — select all objects of a given type
            "select_by_collection" — select all objects in a collection
            "invert" — invert current selection
            "get_selected" — return list of currently selected objects
        object_name: Object name (for select, deselect)
        object_type: Object type filter (MESH, LIGHT, CAMERA, EMPTY, CURVE, etc.)
        collection_name: Collection name (for select_by_collection)

    Returns:
        dict with operation result
    """
    try:
        if action == "select":
            if not object_name:
                return {"error": "object_name is required for select"}
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            return {
                "success": True,
                "message": f"Selected '{object_name}'",
            }

        elif action == "deselect":
            if not object_name:
                return {"error": "object_name is required for deselect"}
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            obj.select_set(False)
            return {
                "success": True,
                "message": f"Deselected '{object_name}'",
            }

        elif action == "select_all":
            bpy.ops.object.select_all(action='SELECT')
            count = len([o for o in bpy.context.scene.objects if o.select_get()])
            return {
                "success": True,
                "message": f"Selected all objects ({count})",
                "selected_count": count,
            }

        elif action == "deselect_all":
            bpy.ops.object.select_all(action='DESELECT')
            return {
                "success": True,
                "message": "Deselected all objects",
            }

        elif action == "select_by_type":
            if not object_type:
                return {"error": "object_type is required (MESH, LIGHT, CAMERA, EMPTY, etc.)"}
            object_type = object_type.upper()
            selected = []
            for obj in bpy.context.scene.objects:
                if obj.type == object_type:
                    obj.select_set(True)
                    selected.append(obj.name)
            return {
                "success": True,
                "message": f"Selected {len(selected)} {object_type} objects",
                "selected": selected,
                "selected_count": len(selected),
            }

        elif action == "select_by_collection":
            if not collection_name:
                return {"error": "collection_name is required for select_by_collection"}
            col = bpy.data.collections.get(collection_name)
            if not col:
                return {"error": f"Collection not found: {collection_name}"}
            selected = []
            for obj in col.objects:
                obj.select_set(True)
                selected.append(obj.name)
            return {
                "success": True,
                "message": f"Selected {len(selected)} objects in collection '{collection_name}'",
                "selected": selected,
                "selected_count": len(selected),
            }

        elif action == "invert":
            bpy.ops.object.select_all(action='INVERT')
            selected = [o.name for o in bpy.context.scene.objects if o.select_get()]
            return {
                "success": True,
                "message": f"Inverted selection ({len(selected)} selected)",
                "selected_count": len(selected),
            }

        elif action == "get_selected":
            selected = []
            for obj in bpy.context.scene.objects:
                if obj.select_get():
                    selected.append({
                        "name": obj.name,
                        "type": obj.type,
                        "location": [obj.location.x, obj.location.y, obj.location.z],
                    })
            active = bpy.context.view_layer.objects.active
            return {
                "success": True,
                "selected": selected,
                "selected_count": len(selected),
                "active_object": active.name if active else None,
            }

        else:
            return {"error": f"Unknown action: {action}. Use: select, deselect, "
                    "select_all, deselect_all, select_by_type, select_by_collection, "
                    "invert, get_selected"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Selection operation failed: {str(e)}"}
