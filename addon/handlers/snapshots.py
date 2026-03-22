"""Scene state snapshots for comparison and rollback."""
import bpy
import traceback
import time
import json

# In-memory snapshot storage
_snapshots = {}


def manage_snapshots(action, name=None, compare_to=None):
    """Lightweight scene state capture for comparison and rollback.

    Captures transforms, materials, lights, camera — NOT geometry.

    Args:
        action: Operation —
            "save" — capture current scene state with a name
            "list" — list all saved snapshots
            "compare" — compare two snapshots or current state vs snapshot
            "restore" — restore scene to a snapshot state
            "delete" — delete a snapshot
        name: Snapshot name (for save, compare, restore, delete)
        compare_to: Second snapshot name for compare (if None, compares to current)

    Returns:
        dict with operation result
    """
    try:
        if action == "save":
            return _save_snapshot(name)
        elif action == "list":
            return _list_snapshots()
        elif action == "compare":
            return _compare_snapshots(name, compare_to)
        elif action == "restore":
            return _restore_snapshot(name)
        elif action == "delete":
            return _delete_snapshot(name)
        else:
            return {"error": f"Unknown action: {action}. Use: save, list, compare, restore, delete"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Snapshot operation failed: {str(e)}"}


def _capture_state():
    """Capture current scene state (no geometry, just transforms/materials/lights/camera)."""
    scene = bpy.context.scene
    state = {
        "objects": {},
        "materials": {},
        "lights": {},
        "camera": None,
        "world": None,
        "render_engine": scene.render.engine,
        "frame": scene.frame_current,
    }

    for obj in scene.objects:
        obj_state = {
            "type": obj.type,
            "location": list(obj.location),
            "rotation": list(obj.rotation_euler),
            "scale": list(obj.scale),
            "visible": obj.visible_get(),
            "materials": [slot.material.name if slot.material else None
                         for slot in obj.material_slots],
        }
        state["objects"][obj.name] = obj_state

        if obj.type == 'LIGHT':
            light = obj.data
            state["lights"][obj.name] = {
                "type": light.type,
                "energy": light.energy,
                "color": list(light.color),
            }

    # Camera
    cam = scene.camera
    if cam and cam.data:
        state["camera"] = {
            "name": cam.name,
            "location": list(cam.location),
            "rotation": list(cam.rotation_euler),
            "focal_length": cam.data.lens,
            "dof_enabled": cam.data.dof.use_dof,
        }

    # Materials
    for mat in bpy.data.materials:
        mat_state = {"use_nodes": mat.use_nodes}
        if mat.use_nodes and mat.node_tree:
            bsdf = None
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    bsdf = node
                    break
            if bsdf:
                mat_state["base_color"] = list(bsdf.inputs['Base Color'].default_value)
                mat_state["metallic"] = bsdf.inputs['Metallic'].default_value
                mat_state["roughness"] = bsdf.inputs['Roughness'].default_value
        state["materials"][mat.name] = mat_state

    # World
    if scene.world and scene.world.use_nodes:
        bg = None
        for node in scene.world.node_tree.nodes:
            if node.type == 'BACKGROUND':
                bg = node
                break
        if bg:
            state["world"] = {
                "strength": bg.inputs['Strength'].default_value,
                "color": list(bg.inputs['Color'].default_value[:3]),
            }

    return state


def _save_snapshot(name):
    """Save current scene state."""
    if not name:
        return {"error": "name is required"}

    state = _capture_state()
    _snapshots[name] = {
        "state": state,
        "timestamp": time.time(),
        "object_count": len(state["objects"]),
        "light_count": len(state["lights"]),
        "material_count": len(state["materials"]),
    }

    return {
        "success": True,
        "message": f"Snapshot '{name}' saved ({len(state['objects'])} objects, "
                   f"{len(state['lights'])} lights, {len(state['materials'])} materials)",
        "name": name,
    }


def _list_snapshots():
    """List all saved snapshots."""
    snapshots = []
    for name, data in _snapshots.items():
        snapshots.append({
            "name": name,
            "timestamp": data["timestamp"],
            "object_count": data["object_count"],
            "light_count": data["light_count"],
            "material_count": data["material_count"],
        })

    return {
        "success": True,
        "snapshots": snapshots,
        "count": len(snapshots),
    }


def _compare_snapshots(name, compare_to):
    """Compare snapshot to current state or another snapshot."""
    if not name:
        return {"error": "name is required"}
    if name not in _snapshots:
        return {"error": f"Snapshot '{name}' not found"}

    state_a = _snapshots[name]["state"]

    if compare_to:
        if compare_to not in _snapshots:
            return {"error": f"Snapshot '{compare_to}' not found"}
        state_b = _snapshots[compare_to]["state"]
        label_b = compare_to
    else:
        state_b = _capture_state()
        label_b = "current"

    changes = []

    # Compare objects
    all_objs = set(list(state_a["objects"].keys()) + list(state_b["objects"].keys()))
    for obj_name in all_objs:
        if obj_name not in state_a["objects"]:
            changes.append(f"Object added: {obj_name}")
            continue
        if obj_name not in state_b["objects"]:
            changes.append(f"Object removed: {obj_name}")
            continue

        a = state_a["objects"][obj_name]
        b = state_b["objects"][obj_name]

        if a["location"] != b["location"]:
            changes.append(f"{obj_name} moved: {_fmt_vec(a['location'])} → {_fmt_vec(b['location'])}")
        if a["rotation"] != b["rotation"]:
            changes.append(f"{obj_name} rotated")
        if a["scale"] != b["scale"]:
            changes.append(f"{obj_name} scaled: {_fmt_vec(a['scale'])} → {_fmt_vec(b['scale'])}")
        if a["visible"] != b["visible"]:
            changes.append(f"{obj_name} visibility: {a['visible']} → {b['visible']}")

    # Compare lights
    all_lights = set(list(state_a["lights"].keys()) + list(state_b["lights"].keys()))
    for light_name in all_lights:
        if light_name not in state_a["lights"]:
            changes.append(f"Light added: {light_name}")
            continue
        if light_name not in state_b["lights"]:
            changes.append(f"Light removed: {light_name}")
            continue

        a = state_a["lights"][light_name]
        b = state_b["lights"][light_name]

        if a["energy"] != b["energy"]:
            changes.append(f"{light_name} energy: {a['energy']} → {b['energy']}")
        if a["color"] != b["color"]:
            changes.append(f"{light_name} color changed")
        if a["type"] != b["type"]:
            changes.append(f"{light_name} type: {a['type']} → {b['type']}")

    # Compare camera
    cam_a = state_a.get("camera", {})
    cam_b = state_b.get("camera", {})
    if cam_a and cam_b:
        if cam_a.get("location") != cam_b.get("location"):
            changes.append("Camera moved")
        if cam_a.get("focal_length") != cam_b.get("focal_length"):
            changes.append(f"Focal length: {cam_a.get('focal_length')} → {cam_b.get('focal_length')}")

    return {
        "success": True,
        "comparing": f"'{name}' vs '{label_b}'",
        "changes": changes,
        "change_count": len(changes),
        "message": "; ".join(changes) if changes else "No changes",
    }


def _restore_snapshot(name):
    """Restore scene to a snapshot state."""
    if not name:
        return {"error": "name is required"}
    if name not in _snapshots:
        return {"error": f"Snapshot '{name}' not found"}

    state = _snapshots[name]["state"]
    restored = []

    # Restore object transforms
    for obj_name, obj_state in state["objects"].items():
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            continue

        obj.location = obj_state["location"]
        obj.rotation_euler = obj_state["rotation"]
        obj.scale = obj_state["scale"]
        obj.hide_set(not obj_state["visible"])
        restored.append(obj_name)

    # Restore light properties
    for light_name, light_state in state["lights"].items():
        obj = bpy.data.objects.get(light_name)
        if not obj or obj.type != 'LIGHT':
            continue
        obj.data.energy = light_state["energy"]
        obj.data.color = light_state["color"]

    # Restore camera
    cam_state = state.get("camera")
    if cam_state:
        cam = bpy.data.objects.get(cam_state["name"])
        if cam:
            cam.location = cam_state["location"]
            cam.rotation_euler = cam_state["rotation"]
            if cam.data:
                cam.data.lens = cam_state["focal_length"]

    # Restore material BSDF properties
    for mat_name, mat_state in state["materials"].items():
        mat = bpy.data.materials.get(mat_name)
        if not mat or not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                if "base_color" in mat_state:
                    node.inputs['Base Color'].default_value = mat_state["base_color"]
                if "metallic" in mat_state:
                    node.inputs['Metallic'].default_value = mat_state["metallic"]
                if "roughness" in mat_state:
                    node.inputs['Roughness'].default_value = mat_state["roughness"]
                break

    # Restore world
    world_state = state.get("world")
    if world_state and bpy.context.scene.world and bpy.context.scene.world.use_nodes:
        for node in bpy.context.scene.world.node_tree.nodes:
            if node.type == 'BACKGROUND':
                node.inputs['Strength'].default_value = world_state["strength"]
                c = world_state["color"]
                node.inputs['Color'].default_value = (c[0], c[1], c[2], 1.0)
                break

    return {
        "success": True,
        "message": f"Restored snapshot '{name}' ({len(restored)} objects)",
        "restored_objects": len(restored),
    }


def _delete_snapshot(name):
    """Delete a snapshot."""
    if not name:
        return {"error": "name is required"}
    if name not in _snapshots:
        return {"error": f"Snapshot '{name}' not found"}

    del _snapshots[name]
    return {
        "success": True,
        "message": f"Deleted snapshot '{name}'",
    }


def _fmt_vec(v):
    """Format a vector for display."""
    return f"[{v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f}]"
