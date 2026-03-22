import bpy
import traceback


def manage_materials(action, object_name=None, material_name=None,
                     slot_index=None, color=None, metallic=None,
                     roughness=None, properties=None, preset=None,
                     node_name=None, input_name=None, value=None,
                     node_type=None, location=None, node_settings=None,
                     from_node=None, from_socket=None, to_node=None,
                     to_socket=None, stops=None):
    """Manage materials: create, assign, remove, list, set/get properties, procedural presets.

    Args:
        action: Operation —
            "create" — create new material with optional PBR properties
            "assign" — assign material to object (optionally to specific slot_index)
            "remove_slot" — remove material slot from object at slot_index
            "list" — list all scene materials with user counts
            "list_object" — list material slots on a specific object
            "set_properties" — set PBR properties on existing material
            "get_properties" — get all Principled BSDF values for a material
            "create_procedural" — create a procedural material preset
        object_name: Object name (for assign, remove_slot, list_object)
        material_name: Material name (for create, assign, set_properties, get_properties)
        slot_index: Material slot index (for assign to specific slot, remove_slot)
        color: Base color [r, g, b, a] or [r, g, b] (0-1 range)
        metallic: Metallic value (0-1)
        roughness: Roughness value (0-1)
        properties: Dict of Principled BSDF properties. Supports all inputs:
            color, metallic, roughness, specular, specular_tint, ior,
            transmission, subsurface_weight, subsurface_radius, subsurface_color,
            emission_color, emission_strength, alpha, coat_weight, coat_roughness,
            sheen_weight, sheen_tint, normal_strength
        preset: Procedural preset name for create_procedural:
            "wood", "marble", "metal_brushed", "glass", "fabric", "concrete", "water"

    Returns:
        dict with operation result
    """
    try:
        if action == "create":
            return _create_material(material_name, color, metallic, roughness, properties)
        elif action == "assign":
            return _assign_material(object_name, material_name, slot_index)
        elif action == "remove_slot":
            return _remove_slot(object_name, slot_index)
        elif action == "list":
            return _list_materials()
        elif action == "list_object":
            return _list_object_materials(object_name)
        elif action == "set_properties":
            return _set_properties(material_name, color, metallic, roughness, properties)
        elif action == "get_properties":
            return _get_properties(material_name)
        elif action == "create_procedural":
            return _create_procedural(material_name, preset)
        elif action == "edit_node":
            return _edit_node(material_name, node_name, input_name, value)
        elif action == "add_node":
            return _add_node(material_name, node_type, location, node_settings)
        elif action == "connect":
            return _connect_nodes(material_name, from_node, from_socket, to_node, to_socket)
        elif action == "disconnect":
            return _disconnect_nodes(material_name, from_node, from_socket, to_node, to_socket)
        elif action == "edit_color_ramp":
            return _edit_color_ramp(material_name, node_name, stops)
        elif action == "get_node_info":
            return _get_node_info(material_name, node_name)
        else:
            return {"error": f"Unknown action: {action}. Use: create, assign, "
                    "remove_slot, list, list_object, set_properties, get_properties, "
                    "create_procedural, edit_node, add_node, connect, disconnect, "
                    "edit_color_ramp, get_node_info"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Material operation failed: {str(e)}"}


# Mapping from friendly property names to Principled BSDF input names
_BSDF_INPUT_MAP = {
    "color": "Base Color",
    "base_color": "Base Color",
    "metallic": "Metallic",
    "roughness": "Roughness",
    "specular": "Specular IOR Level",
    "specular_tint": "Specular Tint",
    "ior": "IOR",
    "transmission": "Transmission Weight",
    "subsurface_weight": "Subsurface Weight",
    "subsurface_radius": "Subsurface Radius",
    "subsurface_color": "Subsurface Color" if hasattr(bpy, 'app') else "",
    "emission_color": "Emission Color",
    "emission_strength": "Emission Strength",
    "alpha": "Alpha",
    "coat_weight": "Coat Weight",
    "coat_roughness": "Coat Roughness",
    "sheen_weight": "Sheen Weight",
    "sheen_tint": "Sheen Tint",
}


def _find_bsdf(mat):
    """Find the Principled BSDF node in a material."""
    if not mat.use_nodes or not mat.node_tree:
        return None
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    return None


def _set_bsdf_props(bsdf, color=None, metallic=None, roughness=None, properties=None):
    """Set Principled BSDF properties. Returns (changed, failed) lists."""
    changed = []
    failed = []

    # Legacy direct params
    if color is not None:
        if len(color) == 3:
            color = list(color) + [1.0]
        try:
            bsdf.inputs["Base Color"].default_value = tuple(color)
            changed.append("color")
        except Exception as e:
            failed.append({"name": "color", "error": str(e)})

    if metallic is not None:
        try:
            bsdf.inputs["Metallic"].default_value = metallic
            changed.append("metallic")
        except Exception as e:
            failed.append({"name": "metallic", "error": str(e)})

    if roughness is not None:
        try:
            bsdf.inputs["Roughness"].default_value = roughness
            changed.append("roughness")
        except Exception as e:
            failed.append({"name": "roughness", "error": str(e)})

    # Extended properties dict
    if properties:
        for prop_name, value in properties.items():
            # Skip if already handled above
            if prop_name in ("color", "base_color") and color is not None:
                continue
            if prop_name == "metallic" and metallic is not None:
                continue
            if prop_name == "roughness" and roughness is not None:
                continue

            # Special: normal_strength creates/updates Normal Map node
            if prop_name == "normal_strength":
                try:
                    _set_normal_strength(bsdf, value)
                    changed.append("normal_strength")
                except Exception as e:
                    failed.append({"name": "normal_strength", "error": str(e)})
                continue

            # Map to BSDF input name
            input_name = _BSDF_INPUT_MAP.get(prop_name, prop_name)

            # Handle color values
            if "color" in prop_name.lower() and isinstance(value, (list, tuple)):
                if len(value) == 3:
                    value = list(value) + [1.0]
                value = tuple(value)

            sock = bsdf.inputs.get(input_name)
            if sock is None:
                # Try case-insensitive
                for s in bsdf.inputs:
                    if s.name.lower() == input_name.lower():
                        sock = s
                        break

            if sock is not None:
                try:
                    sock.default_value = value
                    changed.append(prop_name)
                except Exception as e:
                    failed.append({"name": prop_name, "error": str(e)})
            else:
                available = [s.name for s in bsdf.inputs]
                failed.append({"name": prop_name,
                              "error": f"Input '{input_name}' not found. Available: {available}"})

    return changed, failed


def _set_normal_strength(bsdf, strength):
    """Create or update a Normal Map node connected to Principled BSDF."""
    tree = bsdf.id_data
    # Check if normal map already connected
    normal_input = bsdf.inputs.get("Normal")
    if normal_input and normal_input.links:
        normal_node = normal_input.links[0].from_node
        if normal_node.type == 'NORMAL_MAP':
            normal_node.inputs['Strength'].default_value = strength
            return
    # Create new normal map node
    normal_map = tree.nodes.new('ShaderNodeNormalMap')
    normal_map.location = (bsdf.location.x - 200, bsdf.location.y - 300)
    normal_map.inputs['Strength'].default_value = strength
    tree.links.new(normal_map.outputs['Normal'], bsdf.inputs['Normal'])


def _create_material(material_name, color, metallic, roughness, properties):
    if not material_name:
        return {"error": "material_name is required for create"}

    mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True

    bsdf = _find_bsdf(mat)
    result = {
        "success": True,
        "message": f"Created material '{mat.name}'",
        "material_name": mat.name,
    }

    if bsdf:
        changed, failed = _set_bsdf_props(bsdf, color, metallic, roughness, properties)
        if changed:
            result["properties_set"] = changed
        if failed:
            result["properties_failed"] = failed

    return result


def _assign_material(object_name, material_name, slot_index):
    if not object_name or not material_name:
        return {"error": "object_name and material_name are required for assign"}

    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    mat = bpy.data.materials.get(material_name)
    if not mat:
        return {"error": f"Material not found: {material_name}"}

    if not hasattr(obj, 'data') or obj.data is None or not hasattr(obj.data, 'materials'):
        return {"error": f"Object '{object_name}' (type={obj.type}) does not support materials"}

    if slot_index is not None:
        if slot_index < len(obj.material_slots):
            obj.material_slots[slot_index].material = mat
        else:
            return {"error": f"Slot index {slot_index} out of range (object has {len(obj.material_slots)} slots)"}
    else:
        obj.data.materials.append(mat)

    return {
        "success": True,
        "message": f"Assigned '{material_name}' to '{object_name}'",
        "slot_count": len(obj.material_slots),
    }


def _remove_slot(object_name, slot_index):
    if not object_name:
        return {"error": "object_name is required for remove_slot"}

    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    if slot_index is None:
        slot_index = len(obj.material_slots) - 1

    if slot_index < 0 or slot_index >= len(obj.material_slots):
        return {"error": f"Slot index {slot_index} out of range"}

    obj.active_material_index = slot_index
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.material_slot_remove()

    return {
        "success": True,
        "message": f"Removed material slot {slot_index} from '{object_name}'",
        "remaining_slots": len(obj.material_slots),
    }


def _list_materials():
    materials = []
    for mat in bpy.data.materials:
        mat_info = {
            "name": mat.name,
            "users": mat.users,
            "use_nodes": mat.use_nodes,
        }
        if mat.use_nodes and mat.node_tree:
            mat_info["node_count"] = len(mat.node_tree.nodes)
        materials.append(mat_info)

    return {
        "success": True,
        "total_count": len(materials),
        "materials": materials,
    }


def _list_object_materials(object_name):
    if not object_name:
        return {"error": "object_name is required for list_object"}

    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    slots = []
    for i, slot in enumerate(obj.material_slots):
        slots.append({
            "index": i,
            "material_name": slot.material.name if slot.material else None,
            "link": slot.link,
        })

    return {
        "success": True,
        "object_name": obj.name,
        "slot_count": len(slots),
        "slots": slots,
    }


def _set_properties(material_name, color, metallic, roughness, properties):
    if not material_name:
        return {"error": "material_name is required for set_properties"}

    mat = bpy.data.materials.get(material_name)
    if not mat:
        return {"error": f"Material not found: {material_name}"}

    bsdf = _find_bsdf(mat)
    if not bsdf:
        return {"error": f"No Principled BSDF found in material '{material_name}'"}

    changed, failed = _set_bsdf_props(bsdf, color, metallic, roughness, properties)

    result = {
        "success": True,
        "message": f"Updated properties on '{material_name}': {', '.join(changed)}",
        "changed": changed,
    }
    if failed:
        result["failed"] = failed
    return result


def _get_properties(material_name):
    """Get all current Principled BSDF values for a material."""
    if not material_name:
        return {"error": "material_name is required for get_properties"}

    mat = bpy.data.materials.get(material_name)
    if not mat:
        return {"error": f"Material not found: {material_name}"}

    bsdf = _find_bsdf(mat)
    if not bsdf:
        return {"error": f"No Principled BSDF found in material '{material_name}'"}

    props = {}
    for inp in bsdf.inputs:
        if hasattr(inp, 'default_value'):
            try:
                val = inp.default_value
                if hasattr(val, '__iter__') and not isinstance(val, str):
                    val = list(val)
                props[inp.name] = val
            except Exception:
                pass

    return {
        "success": True,
        "material_name": material_name,
        "properties": props,
    }


def _create_procedural(material_name, preset):
    """Create a procedural material preset with full node graph."""
    if not material_name:
        return {"error": "material_name is required for create_procedural"}
    if not preset:
        return {"error": "preset is required. Options: wood, marble, metal_brushed, "
                "glass, fabric, concrete, water"}

    preset = preset.lower()
    builders = {
        "wood": _build_wood,
        "marble": _build_marble,
        "metal_brushed": _build_metal_brushed,
        "glass": _build_glass,
        "fabric": _build_fabric,
        "concrete": _build_concrete,
        "water": _build_water,
    }

    builder = builders.get(preset)
    if not builder:
        return {"error": f"Unknown preset: {preset}. Options: {', '.join(builders.keys())}"}

    mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    tree = mat.node_tree

    # Clear default nodes
    for node in list(tree.nodes):
        tree.nodes.remove(node)

    builder(tree)

    return {
        "success": True,
        "message": f"Created procedural '{preset}' material '{mat.name}'",
        "material_name": mat.name,
        "preset": preset,
        "node_count": len(tree.nodes),
    }


def _build_wood(tree):
    """Wood material: noise texture + color ramp for grain."""
    nodes = tree.nodes
    links = tree.links

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (600, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    links.new(bsdf.outputs[0], output.inputs[0])

    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-800, 0)
    mapping = nodes.new('ShaderNodeMapping')
    mapping.location = (-600, 0)
    mapping.inputs['Scale'].default_value = (1, 1, 10)
    links.new(tex_coord.outputs['Object'], mapping.inputs['Vector'])

    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-400, 0)
    noise.inputs['Scale'].default_value = 8.0
    noise.inputs['Detail'].default_value = 6.0
    noise.inputs['Distortion'].default_value = 2.0
    links.new(mapping.outputs['Vector'], noise.inputs['Vector'])

    ramp = nodes.new('ShaderNodeColorRamp')
    ramp.location = (-100, 0)
    ramp.color_ramp.elements[0].color = (0.15, 0.08, 0.03, 1)
    ramp.color_ramp.elements[1].color = (0.35, 0.18, 0.08, 1)
    links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])

    bsdf.inputs['Roughness'].default_value = 0.4
    bsdf.inputs['Specular IOR Level'].default_value = 0.3


def _build_marble(tree):
    """Marble material: wave texture + noise for veining."""
    nodes = tree.nodes
    links = tree.links

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (600, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    links.new(bsdf.outputs[0], output.inputs[0])

    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-800, 0)

    wave = nodes.new('ShaderNodeTexWave')
    wave.location = (-400, 0)
    wave.inputs['Scale'].default_value = 3.0
    wave.inputs['Distortion'].default_value = 8.0
    wave.inputs['Detail'].default_value = 4.0
    links.new(tex_coord.outputs['Object'], wave.inputs['Vector'])

    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-400, -200)
    noise.inputs['Scale'].default_value = 6.0
    noise.inputs['Detail'].default_value = 8.0
    links.new(tex_coord.outputs['Object'], noise.inputs['Vector'])

    mix = nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.location = (0, 0)
    mix.inputs['Factor'].default_value = 0.5
    links.new(wave.outputs['Fac'], mix.inputs['Factor'])

    # White base with grey veins
    mix.inputs['A'].default_value = (0.9, 0.88, 0.85, 1.0)
    mix.inputs['B'].default_value = (0.3, 0.28, 0.25, 1.0)

    links.new(mix.outputs['Result'], bsdf.inputs['Base Color'])

    bsdf.inputs['Roughness'].default_value = 0.15
    bsdf.inputs['Specular IOR Level'].default_value = 0.5


def _build_metal_brushed(tree):
    """Brushed metal: anisotropic roughness via noise."""
    nodes = tree.nodes
    links = tree.links

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (600, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    links.new(bsdf.outputs[0], output.inputs[0])

    bsdf.inputs['Base Color'].default_value = (0.7, 0.7, 0.72, 1.0)
    bsdf.inputs['Metallic'].default_value = 1.0
    bsdf.inputs['Roughness'].default_value = 0.3

    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-800, 0)
    mapping = nodes.new('ShaderNodeMapping')
    mapping.location = (-600, 0)
    mapping.inputs['Scale'].default_value = (1, 200, 1)
    links.new(tex_coord.outputs['Object'], mapping.inputs['Vector'])

    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-400, 0)
    noise.inputs['Scale'].default_value = 50.0
    noise.inputs['Detail'].default_value = 2.0
    links.new(mapping.outputs['Vector'], noise.inputs['Vector'])

    ramp = nodes.new('ShaderNodeColorRamp')
    ramp.location = (-100, -200)
    ramp.color_ramp.elements[0].position = 0.4
    ramp.color_ramp.elements[0].color = (0.2, 0.2, 0.2, 1)
    ramp.color_ramp.elements[1].position = 0.6
    ramp.color_ramp.elements[1].color = (0.4, 0.4, 0.4, 1)
    links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], bsdf.inputs['Roughness'])


def _build_glass(tree):
    """Glass material: transmission=1, configurable IOR."""
    nodes = tree.nodes
    links = tree.links

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (400, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (100, 0)
    links.new(bsdf.outputs[0], output.inputs[0])

    bsdf.inputs['Base Color'].default_value = (0.95, 0.95, 0.95, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.0
    bsdf.inputs['Transmission Weight'].default_value = 1.0
    bsdf.inputs['IOR'].default_value = 1.45


def _build_fabric(tree):
    """Fabric material: subsurface + noise roughness variation."""
    nodes = tree.nodes
    links = tree.links

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (600, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    links.new(bsdf.outputs[0], output.inputs[0])

    bsdf.inputs['Base Color'].default_value = (0.3, 0.15, 0.1, 1.0)
    bsdf.inputs['Subsurface Weight'].default_value = 0.1
    bsdf.inputs['Sheen Weight'].default_value = 0.5

    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-600, 0)

    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-300, -200)
    noise.inputs['Scale'].default_value = 30.0
    noise.inputs['Detail'].default_value = 4.0
    links.new(tex_coord.outputs['Object'], noise.inputs['Vector'])

    ramp = nodes.new('ShaderNodeColorRamp')
    ramp.location = (0, -200)
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = (0.6, 0.6, 0.6, 1)
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = (0.9, 0.9, 0.9, 1)
    links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], bsdf.inputs['Roughness'])


def _build_concrete(tree):
    """Concrete material: noise displacement + rough diffuse."""
    nodes = tree.nodes
    links = tree.links

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (600, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    links.new(bsdf.outputs[0], output.inputs[0])

    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-800, 0)

    # Color variation
    noise_color = nodes.new('ShaderNodeTexNoise')
    noise_color.location = (-400, 100)
    noise_color.inputs['Scale'].default_value = 5.0
    noise_color.inputs['Detail'].default_value = 6.0
    links.new(tex_coord.outputs['Object'], noise_color.inputs['Vector'])

    ramp = nodes.new('ShaderNodeColorRamp')
    ramp.location = (-100, 100)
    ramp.color_ramp.elements[0].color = (0.35, 0.33, 0.3, 1)
    ramp.color_ramp.elements[1].color = (0.5, 0.48, 0.45, 1)
    links.new(noise_color.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])

    bsdf.inputs['Roughness'].default_value = 0.85

    # Bump for surface texture
    noise_bump = nodes.new('ShaderNodeTexNoise')
    noise_bump.location = (-400, -200)
    noise_bump.inputs['Scale'].default_value = 20.0
    noise_bump.inputs['Detail'].default_value = 8.0
    links.new(tex_coord.outputs['Object'], noise_bump.inputs['Vector'])

    bump = nodes.new('ShaderNodeBump')
    bump.location = (100, -200)
    bump.inputs['Strength'].default_value = 0.3
    links.new(noise_bump.outputs['Fac'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])


def _build_water(tree):
    """Water material: glass BSDF + noise normal for ripples."""
    nodes = tree.nodes
    links = tree.links

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (600, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    links.new(bsdf.outputs[0], output.inputs[0])

    bsdf.inputs['Base Color'].default_value = (0.05, 0.15, 0.2, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.0
    bsdf.inputs['Transmission Weight'].default_value = 0.8
    bsdf.inputs['IOR'].default_value = 1.33
    bsdf.inputs['Specular IOR Level'].default_value = 0.5

    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-800, 0)

    noise1 = nodes.new('ShaderNodeTexNoise')
    noise1.location = (-400, -200)
    noise1.inputs['Scale'].default_value = 8.0
    noise1.inputs['Detail'].default_value = 4.0
    links.new(tex_coord.outputs['Object'], noise1.inputs['Vector'])

    bump = nodes.new('ShaderNodeBump')
    bump.location = (100, -200)
    bump.inputs['Strength'].default_value = 0.15
    links.new(noise1.outputs['Fac'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])


def _edit_node(material_name, node_name, input_name, value):
    """Change any node input value."""
    if not material_name:
        return {"error": "material_name is required"}
    if not node_name:
        return {"error": "node_name is required"}
    if not input_name:
        return {"error": "input_name is required"}

    mat = bpy.data.materials.get(material_name)
    if not mat or not mat.use_nodes:
        return {"error": f"Material not found or has no nodes: {material_name}"}

    node = mat.node_tree.nodes.get(node_name)
    if not node:
        available = [n.name for n in mat.node_tree.nodes]
        return {"error": f"Node '{node_name}' not found. Available: {available}"}

    # Try as input socket first
    sock = node.inputs.get(input_name)
    if sock is None:
        # Case-insensitive fallback
        for s in node.inputs:
            if s.name.lower() == input_name.lower():
                sock = s
                break

    if sock is not None:
        try:
            if isinstance(value, list):
                if len(value) == 3 and "color" in input_name.lower():
                    value = value + [1.0]
                value = tuple(value)
            sock.default_value = value
            return {
                "success": True,
                "message": f"Set {node_name}.{input_name} = {value}",
            }
        except Exception as e:
            return {"error": f"Failed to set value: {str(e)}"}

    # Try as node property
    if hasattr(node, input_name):
        try:
            setattr(node, input_name, value)
            return {
                "success": True,
                "message": f"Set {node_name}.{input_name} = {value}",
            }
        except Exception as e:
            return {"error": f"Failed to set property: {str(e)}"}

    available_inputs = [s.name for s in node.inputs]
    return {"error": f"Input/property '{input_name}' not found on '{node_name}'. "
            f"Available inputs: {available_inputs}"}


def _add_node(material_name, node_type, location, node_settings):
    """Add a single node to a material's node tree."""
    if not material_name:
        return {"error": "material_name is required"}
    if not node_type:
        return {"error": "node_type is required (e.g. ShaderNodeColorRamp, ShaderNodeMixRGB)"}

    mat = bpy.data.materials.get(material_name)
    if not mat:
        return {"error": f"Material not found: {material_name}"}
    if not mat.use_nodes:
        mat.use_nodes = True

    try:
        node = mat.node_tree.nodes.new(node_type)
    except Exception as e:
        return {"error": f"Failed to create node type '{node_type}': {str(e)}"}

    if location:
        node.location = (location[0], location[1])

    if node_settings:
        for key, val in node_settings.items():
            if hasattr(node, key):
                try:
                    setattr(node, key, val)
                except Exception:
                    pass

    return {
        "success": True,
        "message": f"Added {node_type} node '{node.name}' to '{material_name}'",
        "node_name": node.name,
        "node_type": node.type,
    }


def _connect_nodes(material_name, from_node, from_socket, to_node, to_socket):
    """Link two nodes in a material."""
    if not all([material_name, from_node, to_node]):
        return {"error": "material_name, from_node, and to_node are required"}
    from_socket = from_socket or 0
    to_socket = to_socket or 0

    mat = bpy.data.materials.get(material_name)
    if not mat or not mat.use_nodes:
        return {"error": f"Material not found or has no nodes: {material_name}"}

    tree = mat.node_tree
    src = tree.nodes.get(from_node)
    dst = tree.nodes.get(to_node)
    if not src:
        return {"error": f"Source node '{from_node}' not found"}
    if not dst:
        return {"error": f"Destination node '{to_node}' not found"}

    # Resolve sockets
    if isinstance(from_socket, int):
        if from_socket >= len(src.outputs):
            return {"error": f"Output index {from_socket} out of range on '{from_node}' "
                    f"(has {len(src.outputs)} outputs)"}
        out = src.outputs[from_socket]
    else:
        out = src.outputs.get(from_socket)
        if not out:
            available = [s.name for s in src.outputs]
            return {"error": f"Output '{from_socket}' not found on '{from_node}'. Available: {available}"}

    if isinstance(to_socket, int):
        if to_socket >= len(dst.inputs):
            return {"error": f"Input index {to_socket} out of range on '{to_node}' "
                    f"(has {len(dst.inputs)} inputs)"}
        inp = dst.inputs[to_socket]
    else:
        inp = dst.inputs.get(to_socket)
        if not inp:
            available = [s.name for s in dst.inputs]
            return {"error": f"Input '{to_socket}' not found on '{to_node}'. Available: {available}"}

    tree.links.new(out, inp)

    return {
        "success": True,
        "message": f"Connected {from_node}[{out.name}] → {to_node}[{inp.name}]",
    }


def _disconnect_nodes(material_name, from_node, from_socket, to_node, to_socket):
    """Unlink nodes in a material."""
    if not all([material_name, from_node, to_node]):
        return {"error": "material_name, from_node, and to_node are required"}

    mat = bpy.data.materials.get(material_name)
    if not mat or not mat.use_nodes:
        return {"error": f"Material not found or has no nodes: {material_name}"}

    tree = mat.node_tree
    removed = 0

    for link in list(tree.links):
        match = True
        if from_node and link.from_node.name != from_node:
            match = False
        if to_node and link.to_node.name != to_node:
            match = False
        if from_socket is not None:
            if isinstance(from_socket, str) and link.from_socket.name != from_socket:
                match = False
            elif isinstance(from_socket, int) and list(link.from_node.outputs).index(link.from_socket) != from_socket:
                match = False
        if to_socket is not None:
            if isinstance(to_socket, str) and link.to_socket.name != to_socket:
                match = False
            elif isinstance(to_socket, int) and list(link.to_node.inputs).index(link.to_socket) != to_socket:
                match = False
        if match:
            tree.links.remove(link)
            removed += 1

    return {
        "success": True,
        "message": f"Removed {removed} link(s) between '{from_node}' and '{to_node}'",
        "removed": removed,
    }


def _edit_color_ramp(material_name, node_name, stops):
    """Set color ramp stops directly.

    stops: list of dicts, each with:
        - position: float 0-1
        - color: [r, g, b, a] or [r, g, b]
    """
    if not material_name or not node_name:
        return {"error": "material_name and node_name are required"}
    if not stops:
        return {"error": "stops list is required"}

    mat = bpy.data.materials.get(material_name)
    if not mat or not mat.use_nodes:
        return {"error": f"Material not found or has no nodes: {material_name}"}

    node = mat.node_tree.nodes.get(node_name)
    if not node:
        return {"error": f"Node '{node_name}' not found"}
    if not hasattr(node, 'color_ramp'):
        return {"error": f"Node '{node_name}' is not a ColorRamp"}

    ramp = node.color_ramp
    elements = ramp.elements

    # Ensure enough elements
    while len(elements) < len(stops):
        elements.new(0.5)
    # Remove excess elements (can't remove below 2)
    while len(elements) > max(len(stops), 2):
        elements.remove(elements[-1])

    for i, stop in enumerate(stops):
        if i >= len(elements):
            break
        elements[i].position = stop["position"]
        c = stop.get("color", [0, 0, 0, 1])
        if len(c) == 3:
            c = list(c) + [1.0]
        elements[i].color = tuple(c)

    return {
        "success": True,
        "message": f"Updated {len(stops)} color ramp stops on '{node_name}'",
        "stops_set": len(stops),
    }


def _get_node_info(material_name, node_name):
    """Get detailed info about a single node."""
    if not material_name or not node_name:
        return {"error": "material_name and node_name are required"}

    mat = bpy.data.materials.get(material_name)
    if not mat or not mat.use_nodes:
        return {"error": f"Material not found or has no nodes: {material_name}"}

    node = mat.node_tree.nodes.get(node_name)
    if not node:
        available = [n.name for n in mat.node_tree.nodes]
        return {"error": f"Node '{node_name}' not found. Available: {available}"}

    info = {
        "name": node.name,
        "type": node.type,
        "bl_idname": node.bl_idname,
        "label": node.label,
        "location": [node.location.x, node.location.y],
        "inputs": {},
        "outputs": {},
    }

    for inp in node.inputs:
        inp_info = {"type": inp.type, "linked": bool(inp.links)}
        if hasattr(inp, 'default_value') and not inp.links:
            val = inp.default_value
            if hasattr(val, '__iter__') and not isinstance(val, str):
                val = list(val)
            inp_info["value"] = val
        if inp.links:
            inp_info["from_node"] = inp.links[0].from_node.name
            inp_info["from_socket"] = inp.links[0].from_socket.name
        info["inputs"][inp.name] = inp_info

    for out in node.outputs:
        out_info = {"type": out.type, "linked": bool(out.links)}
        if out.links:
            out_info["connections"] = [
                {"to_node": l.to_node.name, "to_socket": l.to_socket.name}
                for l in out.links
            ]
        info["outputs"][out.name] = out_info

    # Special properties
    if hasattr(node, 'color_ramp'):
        info["color_ramp"] = [
            {"position": e.position, "color": list(e.color)}
            for e in node.color_ramp.elements
        ]
    if hasattr(node, 'operation'):
        info["operation"] = node.operation
    if hasattr(node, 'blend_type'):
        info["blend_type"] = node.blend_type
    if hasattr(node, 'data_type'):
        info["data_type"] = node.data_type

    return {
        "success": True,
        "node": info,
    }
