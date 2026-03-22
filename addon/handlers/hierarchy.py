"""Parent/child hierarchy management."""
import bpy
import traceback


def manage_hierarchy(action, object_name=None, parent_name=None,
                     keep_transform=True, parent_type="OBJECT", bone_name=None):
    """Manage object parent/child relationships.

    Actions:
    - parent: Parent object_name to parent_name
    - unparent: Clear parent from object_name
    - list_children: Return direct children of object_name
    - get_parent: Return parent info for object_name
    - list_tree: Return full hierarchy tree (recursive)
    """
    try:
        if action == "parent":
            return _parent(object_name, parent_name, keep_transform, parent_type, bone_name)
        elif action == "unparent":
            return _unparent(object_name, keep_transform)
        elif action == "list_children":
            return _list_children(object_name)
        elif action == "get_parent":
            return _get_parent(object_name)
        elif action == "list_tree":
            return _list_tree(object_name)
        else:
            return {"error": f"Unknown action: {action}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def _parent(object_name, parent_name, keep_transform, parent_type, bone_name):
    obj = bpy.data.objects.get(object_name)
    parent_obj = bpy.data.objects.get(parent_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if not parent_obj:
        return {"error": f"Parent object '{parent_name}' not found"}

    if keep_transform:
        # Store world matrix before parenting
        world_matrix = obj.matrix_world.copy()

    obj.parent = parent_obj
    obj.parent_type = parent_type

    if parent_type == "BONE" and bone_name:
        obj.parent_bone = bone_name

    if keep_transform:
        obj.matrix_parent_inverse = parent_obj.matrix_world.inverted()
        obj.matrix_world = world_matrix

    return {
        "success": True,
        "message": f"Parented '{object_name}' to '{parent_name}' (type={parent_type})",
        "object": object_name,
        "parent": parent_name,
        "parent_type": parent_type,
    }


def _unparent(object_name, keep_transform):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if not obj.parent:
        return {"error": f"Object '{object_name}' has no parent"}

    old_parent = obj.parent.name

    if keep_transform:
        world_matrix = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world_matrix
    else:
        obj.parent = None

    return {
        "success": True,
        "message": f"Unparented '{object_name}' from '{old_parent}'",
        "object": object_name,
        "old_parent": old_parent,
    }


def _list_children(object_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    children = []
    for child in obj.children:
        children.append({
            "name": child.name,
            "type": child.type,
            "parent_type": child.parent_type,
        })

    return {
        "success": True,
        "object": object_name,
        "children": children,
        "count": len(children),
    }


def _get_parent(object_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    if not obj.parent:
        return {
            "success": True,
            "object": object_name,
            "parent": None,
        }

    return {
        "success": True,
        "object": object_name,
        "parent": obj.parent.name,
        "parent_type": obj.parent_type,
        "parent_bone": obj.parent_bone if obj.parent_type == "BONE" else None,
        "parent_object_type": obj.parent.type,
    }


def _list_tree(object_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    def build_tree(o):
        node = {
            "name": o.name,
            "type": o.type,
            "children": [],
        }
        for child in o.children:
            node["children"].append(build_tree(child))
        return node

    tree = build_tree(obj)
    return {
        "success": True,
        "tree": tree,
    }
