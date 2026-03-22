import bpy
import traceback


def _find_view_layer_collection(layer_col, name):
    """Recursively find a LayerCollection by collection name."""
    if layer_col.collection.name == name:
        return layer_col
    for child in layer_col.children:
        result = _find_view_layer_collection(child, name)
        if result:
            return result
    return None


def manage_collections(action, collection_name=None, parent_collection=None,
                       object_name=None, hide_viewport=None, hide_render=None,
                       holdout=None, indirect_only=None):
    """Manage scene collections.

    Args:
        action: "create" | "delete" | "move_object" | "list" | "purge_orphans" |
                "set_visibility"
        collection_name: Name of collection to create/delete/target
        parent_collection: Parent collection name (for nesting)
        object_name: Object name (for move_object)
        hide_viewport: Toggle viewport visibility (for set_visibility)
        hide_render: Toggle render visibility (for set_visibility)
        holdout: Set holdout for render layer (for set_visibility)
        indirect_only: Set indirect only for render layer (for set_visibility)

    Returns:
        dict with success status
    """
    try:
        if action == "create":
            if not collection_name:
                return {"error": "collection_name is required for create"}
            if bpy.data.collections.get(collection_name):
                return {"error": f"Collection already exists: {collection_name}"}

            new_col = bpy.data.collections.new(collection_name)

            if parent_collection:
                parent = bpy.data.collections.get(parent_collection)
                if not parent:
                    return {"error": f"Parent collection not found: {parent_collection}"}
                parent.children.link(new_col)
            else:
                bpy.context.scene.collection.children.link(new_col)

            return {
                "success": True,
                "message": f"Created collection '{collection_name}'",
                "parent": parent_collection or "Scene Collection",
            }

        elif action == "delete":
            if not collection_name:
                return {"error": "collection_name is required for delete"}
            col = bpy.data.collections.get(collection_name)
            if not col:
                return {"error": f"Collection not found: {collection_name}"}

            # Move objects back to scene collection before deleting
            for obj in list(col.objects):
                if obj.name not in bpy.context.scene.collection.objects:
                    bpy.context.scene.collection.objects.link(obj)

            bpy.data.collections.remove(col)
            return {
                "success": True,
                "message": f"Deleted collection '{collection_name}'",
            }

        elif action == "move_object":
            if not object_name or not collection_name:
                return {"error": "object_name and collection_name are required for move_object"}
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            target_col = bpy.data.collections.get(collection_name)
            if not target_col:
                return {"error": f"Collection not found: {collection_name}"}

            # Remove from all current collections
            for col in obj.users_collection:
                col.objects.unlink(obj)

            # Add to target collection
            target_col.objects.link(obj)

            return {
                "success": True,
                "message": f"Moved '{object_name}' to collection '{collection_name}'",
            }

        elif action == "list":
            def _collect_tree(collection, depth=0):
                info = {
                    "name": collection.name,
                    "depth": depth,
                    "objects": [obj.name for obj in collection.objects],
                    "children": [],
                }
                for child in collection.children:
                    info["children"].append(_collect_tree(child, depth + 1))
                return info

            tree = _collect_tree(bpy.context.scene.collection)
            return {
                "success": True,
                "collections": tree,
            }

        elif action == "set_visibility":
            if not collection_name:
                return {"error": "collection_name is required for set_visibility"}
            col = bpy.data.collections.get(collection_name)
            if not col:
                return {"error": f"Collection not found: {collection_name}"}

            changed = []
            if hide_viewport is not None:
                col.hide_viewport = hide_viewport
                changed.append(f"hide_viewport={hide_viewport}")
            if hide_render is not None:
                col.hide_render = hide_render
                changed.append(f"hide_render={hide_render}")

            # Holdout and indirect_only are on the view layer collection
            vl_col = _find_view_layer_collection(
                bpy.context.view_layer.layer_collection, collection_name)
            if vl_col:
                if holdout is not None:
                    vl_col.holdout = holdout
                    changed.append(f"holdout={holdout}")
                if indirect_only is not None:
                    vl_col.indirect_only = indirect_only
                    changed.append(f"indirect_only={indirect_only}")

            return {
                "success": True,
                "message": f"Set visibility on '{collection_name}': {', '.join(changed)}",
                "changed": changed,
            }

        elif action == "purge_orphans":
            # Purge orphaned data blocks
            removed = 0
            for block_type in [bpy.data.meshes, bpy.data.materials, bpy.data.textures,
                              bpy.data.images, bpy.data.node_groups]:
                for block in list(block_type):
                    if block.users == 0:
                        block_type.remove(block)
                        removed += 1
            return {
                "success": True,
                "message": f"Purged {removed} orphaned data blocks",
                "removed_count": removed,
            }

        else:
            return {"error": f"Unknown action: {action}. Use create, delete, move_object, "
                    "list, set_visibility, or purge_orphans"}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Collection operation failed: {str(e)}"}
