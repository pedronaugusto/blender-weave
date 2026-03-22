import bpy
import math
import traceback


def manage_armature(action, armature_name=None, object_name=None,
                    bone_name=None, bone_data=None, constraint_data=None,
                    parent_bone=None, mode="AUTO",
                    head=None, tail=None, roll=None, use_deform=None, use_connect=None):
    """Manage armatures: create, add/modify bones, parent meshes, IK, constraints.

    Args:
        action: Operation —
            "create" — create armature with bones from bone_data list
            "add_bone" — add single bone to existing armature
            "set_bone" — modify bone properties (head, tail, roll, use_deform)
            "parent_mesh" — parent object_name to armature_name
            "add_ik" — add IK constraint to bone via constraint_data
            "add_bone_constraint" — add constraint to bone via constraint_data
            "remove_bone_constraint" — remove constraint by name from bone
            "list_bones" — list bones with hierarchy and positions
        armature_name: Name of the armature object
        object_name: Name of mesh object (for parent_mesh)
        bone_name: Name of a specific bone
        bone_data: List of bone dicts for create: [{name, head, tail, parent, use_connect}]
        constraint_data: Dict with constraint info:
            For add_ik: {target, subtarget, pole_target, pole_subtarget, chain_count}
            For add_bone_constraint: {type, target, subtarget, properties}
        parent_bone: Parent bone name (for add_bone)
        mode: Parenting mode — "AUTO" (auto weights) or "MANUAL" (for parent_mesh)
        head: [x,y,z] bone head position (for add_bone, set_bone)
        tail: [x,y,z] bone tail position (for add_bone, set_bone)
        roll: Bone roll in degrees (for set_bone)
        use_deform: Whether bone deforms mesh (for set_bone)
        use_connect: Whether bone connects to parent (for add_bone)

    Returns:
        dict with operation result
    """
    try:
        if action == "create":
            return _create_armature(armature_name, bone_data)
        elif action == "add_bone":
            return _add_bone(armature_name, bone_name, head, tail, parent_bone, use_connect)
        elif action == "set_bone":
            return _set_bone(armature_name, bone_name, head, tail, roll, use_deform)
        elif action == "parent_mesh":
            return _parent_mesh(armature_name, object_name, mode)
        elif action == "add_ik":
            return _add_ik(armature_name, bone_name, constraint_data)
        elif action == "add_bone_constraint":
            return _add_bone_constraint(armature_name, bone_name, constraint_data)
        elif action == "remove_bone_constraint":
            return _remove_bone_constraint(armature_name, bone_name, constraint_data)
        elif action == "list_bones":
            return _list_bones(armature_name)
        else:
            return {"error": f"Unknown action: {action}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Armature operation failed: {str(e)}"}


def _create_armature(armature_name, bone_data):
    if not bone_data:
        return {"error": "bone_data list is required for create"}

    name = armature_name or "Armature"
    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')

    bone_map = {}
    for bd in bone_data:
        bone = arm_data.edit_bones.new(bd["name"])
        bone.head = tuple(bd.get("head", [0, 0, 0]))
        bone.tail = tuple(bd.get("tail", [0, 0, 1]))
        if bd.get("use_connect"):
            bone.use_connect = True
        bone_map[bd["name"]] = bone

    # Set parents after all bones exist
    for bd in bone_data:
        if bd.get("parent") and bd["parent"] in bone_map:
            bone_map[bd["name"]].parent = bone_map[bd["parent"]]

    bpy.ops.object.mode_set(mode='OBJECT')

    return {
        "success": True,
        "message": f"Created armature '{arm_obj.name}' with {len(bone_data)} bones",
        "armature_name": arm_obj.name,
        "bone_count": len(bone_data),
    }


def _add_bone(armature_name, bone_name, head, tail, parent_bone, use_connect):
    if not armature_name or not bone_name:
        return {"error": "armature_name and bone_name are required"}

    arm_obj = bpy.data.objects.get(armature_name)
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return {"error": f"Armature not found: {armature_name}"}

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    bone = arm_obj.data.edit_bones.new(bone_name)
    bone.head = tuple(head or [0, 0, 0])
    bone.tail = tuple(tail or [0, 0, 1])
    if use_connect:
        bone.use_connect = True
    if parent_bone:
        parent = arm_obj.data.edit_bones.get(parent_bone)
        if parent:
            bone.parent = parent

    bpy.ops.object.mode_set(mode='OBJECT')

    return {
        "success": True,
        "message": f"Added bone '{bone_name}' to '{armature_name}'",
    }


def _set_bone(armature_name, bone_name, head, tail, roll, use_deform):
    if not armature_name or not bone_name:
        return {"error": "armature_name and bone_name are required"}

    arm_obj = bpy.data.objects.get(armature_name)
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return {"error": f"Armature not found: {armature_name}"}

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    bone = arm_obj.data.edit_bones.get(bone_name)
    if not bone:
        bpy.ops.object.mode_set(mode='OBJECT')
        return {"error": f"Bone not found: {bone_name}"}

    changed = []
    if head is not None:
        bone.head = tuple(head)
        changed.append("head")
    if tail is not None:
        bone.tail = tuple(tail)
        changed.append("tail")
    if roll is not None:
        bone.roll = math.radians(roll)
        changed.append("roll")
    if use_deform is not None:
        bone.use_deform = use_deform
        changed.append("use_deform")

    bpy.ops.object.mode_set(mode='OBJECT')

    return {
        "success": True,
        "message": f"Updated bone '{bone_name}': {', '.join(changed)}",
        "changed": changed,
    }


def _parent_mesh(armature_name, object_name, mode):
    if not armature_name or not object_name:
        return {"error": "armature_name and object_name are required"}

    arm_obj = bpy.data.objects.get(armature_name)
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return {"error": f"Armature not found: {armature_name}"}

    mesh_obj = bpy.data.objects.get(object_name)
    if not mesh_obj:
        return {"error": f"Object not found: {object_name}"}

    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj

    if mode == "AUTO":
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    else:
        bpy.ops.object.parent_set(type='ARMATURE')

    return {
        "success": True,
        "message": f"Parented '{object_name}' to '{armature_name}' (mode={mode})",
    }


def _add_ik(armature_name, bone_name, constraint_data):
    if not armature_name or not bone_name or not constraint_data:
        return {"error": "armature_name, bone_name, and constraint_data are required"}

    arm_obj = bpy.data.objects.get(armature_name)
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return {"error": f"Armature not found: {armature_name}"}

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')

    pose_bone = arm_obj.pose.bones.get(bone_name)
    if not pose_bone:
        bpy.ops.object.mode_set(mode='OBJECT')
        return {"error": f"Bone not found: {bone_name}"}

    ik = pose_bone.constraints.new('IK')
    if constraint_data.get("target"):
        ik.target = bpy.data.objects.get(constraint_data["target"])
    if constraint_data.get("subtarget"):
        ik.subtarget = constraint_data["subtarget"]
    if constraint_data.get("pole_target"):
        ik.pole_target = bpy.data.objects.get(constraint_data["pole_target"])
    if constraint_data.get("pole_subtarget"):
        ik.pole_subtarget = constraint_data["pole_subtarget"]
    if constraint_data.get("chain_count") is not None:
        ik.chain_count = constraint_data["chain_count"]

    bpy.ops.object.mode_set(mode='OBJECT')

    return {
        "success": True,
        "message": f"Added IK constraint to bone '{bone_name}'",
        "constraint_name": ik.name,
    }


def _add_bone_constraint(armature_name, bone_name, constraint_data):
    if not armature_name or not bone_name or not constraint_data:
        return {"error": "armature_name, bone_name, and constraint_data are required"}

    arm_obj = bpy.data.objects.get(armature_name)
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return {"error": f"Armature not found: {armature_name}"}

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')

    pose_bone = arm_obj.pose.bones.get(bone_name)
    if not pose_bone:
        bpy.ops.object.mode_set(mode='OBJECT')
        return {"error": f"Bone not found: {bone_name}"}

    con_type = constraint_data.get("type")
    if not con_type:
        bpy.ops.object.mode_set(mode='OBJECT')
        return {"error": "constraint_data must include 'type'"}

    con = pose_bone.constraints.new(con_type)
    if constraint_data.get("target"):
        con.target = bpy.data.objects.get(constraint_data["target"])
    if constraint_data.get("subtarget"):
        con.subtarget = constraint_data["subtarget"]

    props = constraint_data.get("properties", {})
    for key, val in props.items():
        if hasattr(con, key):
            setattr(con, key, val)

    bpy.ops.object.mode_set(mode='OBJECT')

    return {
        "success": True,
        "message": f"Added {con_type} constraint to bone '{bone_name}'",
        "constraint_name": con.name,
    }


def _remove_bone_constraint(armature_name, bone_name, constraint_data):
    if not armature_name or not bone_name or not constraint_data:
        return {"error": "armature_name, bone_name, and constraint_data are required"}

    constraint_name = constraint_data.get("name")
    if not constraint_name:
        return {"error": "constraint_data must include 'name'"}

    arm_obj = bpy.data.objects.get(armature_name)
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return {"error": f"Armature not found: {armature_name}"}

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')

    pose_bone = arm_obj.pose.bones.get(bone_name)
    if not pose_bone:
        bpy.ops.object.mode_set(mode='OBJECT')
        return {"error": f"Bone not found: {bone_name}"}

    con = pose_bone.constraints.get(constraint_name)
    if not con:
        bpy.ops.object.mode_set(mode='OBJECT')
        return {"error": f"Constraint not found: {constraint_name}"}

    pose_bone.constraints.remove(con)
    bpy.ops.object.mode_set(mode='OBJECT')

    return {
        "success": True,
        "message": f"Removed constraint '{constraint_name}' from bone '{bone_name}'",
    }


def _list_bones(armature_name):
    if not armature_name:
        return {"error": "armature_name is required"}

    arm_obj = bpy.data.objects.get(armature_name)
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return {"error": f"Armature not found: {armature_name}"}

    bones = []
    for bone in arm_obj.data.bones:
        bone_info = {
            "name": bone.name,
            "head": list(bone.head_local),
            "tail": list(bone.tail_local),
            "parent": bone.parent.name if bone.parent else None,
            "use_connect": bone.use_connect,
            "use_deform": bone.use_deform,
            "children": [c.name for c in bone.children],
        }

        # Add pose bone constraints
        pose_bone = arm_obj.pose.bones.get(bone.name)
        if pose_bone and pose_bone.constraints:
            bone_info["constraints"] = [
                {"name": c.name, "type": c.type} for c in pose_bone.constraints
            ]

        bones.append(bone_info)

    return {
        "success": True,
        "armature_name": arm_obj.name,
        "bone_count": len(bones),
        "bones": bones,
    }


def manage_weights(object_name, action, group_name=None,
                   vertex_indices=None, weight=1.0):
    """Manage vertex groups and weights on a mesh.

    Args:
        action: Operation —
            "assign" — assign weight to vertices in vertex group
            "auto" — automatic weights from parent armature
            "normalize" — normalize all vertex group weights
            "list" — list all vertex groups with vertex counts
            "remove" — remove vertex group by name
        object_name: Name of the mesh object
        group_name: Vertex group name (for assign, remove)
        vertex_indices: List of vertex indices (for assign)
        weight: Weight value 0-1 (for assign, default 1.0)

    Returns:
        dict with operation result
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}

        if action == "assign":
            if not group_name:
                return {"error": "group_name is required for assign"}
            vg = obj.vertex_groups.get(group_name)
            if not vg:
                vg = obj.vertex_groups.new(name=group_name)
            indices = vertex_indices or list(range(len(obj.data.vertices)))
            vg.add(indices, weight, 'REPLACE')
            return {
                "success": True,
                "message": f"Assigned weight {weight} to {len(indices)} vertices in '{group_name}'",
            }

        elif action == "auto":
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            if obj.parent and obj.parent.type == 'ARMATURE':
                bpy.ops.object.parent_set(type='ARMATURE_AUTO')
                return {
                    "success": True,
                    "message": f"Applied automatic weights to '{object_name}' from armature",
                }
            return {"error": "Object must be parented to an armature for auto weights"}

        elif action == "normalize":
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_normalize_all()
            bpy.ops.object.mode_set(mode='OBJECT')
            return {
                "success": True,
                "message": f"Normalized all vertex groups on '{object_name}'",
            }

        elif action == "list":
            groups = []
            for vg in obj.vertex_groups:
                # Count vertices in this group
                count = 0
                for v in obj.data.vertices:
                    for g in v.groups:
                        if g.group == vg.index:
                            count += 1
                            break
                groups.append({
                    "name": vg.name,
                    "index": vg.index,
                    "vertex_count": count,
                })
            return {
                "success": True,
                "object_name": obj.name,
                "groups": groups,
                "total": len(groups),
            }

        elif action == "remove":
            if not group_name:
                return {"error": "group_name is required for remove"}
            vg = obj.vertex_groups.get(group_name)
            if not vg:
                return {"error": f"Vertex group not found: {group_name}"}
            obj.vertex_groups.remove(vg)
            return {
                "success": True,
                "message": f"Removed vertex group '{group_name}' from '{object_name}'",
            }

        else:
            return {"error": f"Unknown action: {action}. Use: assign, auto, normalize, list, remove"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Weight operation failed: {str(e)}"}


def manage_shape_keys(object_name, action, key_name=None, value=None, frame=None):
    """Manage shape keys on a mesh.

    Args:
        action: Operation —
            "add" — create shape key from current mesh state (first = Basis)
            "set_value" — set blend value 0.0-1.0
            "keyframe" — keyframe value at frame
            "list" — list all shape keys with values
            "remove" — remove shape key by name
        object_name: Name of the mesh object
        key_name: Shape key name
        value: Blend value 0.0-1.0 (for set_value)
        frame: Frame number (for keyframe)

    Returns:
        dict with operation result
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj or obj.type != 'MESH':
            return {"error": f"Mesh object not found: {object_name}"}

        if action == "add":
            if not obj.data.shape_keys:
                # First key is always Basis
                obj.shape_key_add(name="Basis")
            sk = obj.shape_key_add(name=key_name or "Key")
            return {
                "success": True,
                "message": f"Added shape key '{sk.name}' to '{object_name}'",
                "key_name": sk.name,
            }

        elif action == "set_value":
            if not key_name:
                return {"error": "key_name is required for set_value"}
            if not obj.data.shape_keys:
                return {"error": f"No shape keys on '{object_name}'"}
            sk = obj.data.shape_keys.key_blocks.get(key_name)
            if not sk:
                return {"error": f"Shape key not found: {key_name}"}
            sk.value = value if value is not None else 0.0
            return {
                "success": True,
                "message": f"Set '{key_name}' value to {sk.value}",
            }

        elif action == "keyframe":
            if not key_name:
                return {"error": "key_name is required for keyframe"}
            if frame is None:
                return {"error": "frame is required for keyframe"}
            if not obj.data.shape_keys:
                return {"error": f"No shape keys on '{object_name}'"}
            sk = obj.data.shape_keys.key_blocks.get(key_name)
            if not sk:
                return {"error": f"Shape key not found: {key_name}"}
            if value is not None:
                sk.value = value
            sk.keyframe_insert(data_path="value", frame=frame)
            return {
                "success": True,
                "message": f"Keyframed '{key_name}' at frame {frame} (value={sk.value})",
            }

        elif action == "list":
            if not obj.data.shape_keys:
                return {
                    "success": True,
                    "object_name": obj.name,
                    "keys": [],
                    "total": 0,
                }
            keys = []
            for sk in obj.data.shape_keys.key_blocks:
                keys.append({
                    "name": sk.name,
                    "value": sk.value,
                    "slider_min": sk.slider_min,
                    "slider_max": sk.slider_max,
                })
            return {
                "success": True,
                "object_name": obj.name,
                "keys": keys,
                "total": len(keys),
            }

        elif action == "remove":
            if not key_name:
                return {"error": "key_name is required for remove"}
            if not obj.data.shape_keys:
                return {"error": f"No shape keys on '{object_name}'"}
            sk = obj.data.shape_keys.key_blocks.get(key_name)
            if not sk:
                return {"error": f"Shape key not found: {key_name}"}
            obj.shape_key_remove(sk)
            return {
                "success": True,
                "message": f"Removed shape key '{key_name}' from '{object_name}'",
            }

        else:
            return {"error": f"Unknown action: {action}. Use: add, set_value, keyframe, list, remove"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Shape key operation failed: {str(e)}"}
