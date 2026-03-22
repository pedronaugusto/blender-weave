"""World/environment management for BlenderWeave."""
import bpy
import traceback


def manage_world(action, **kwargs):
    """Manage world/environment settings.

    Args:
        action: Operation —
            "set_color" — set world background color
            "set_hdri" — set HDRI environment texture
            "set_strength" — set environment light strength
            "get_properties" — get current world properties
            "set_properties" — set multiple world properties at once
        kwargs: Additional parameters:
            For set_color: color [r,g,b]
            For set_hdri: filepath (str), strength (float)
            For set_strength: strength (float)
            For set_properties: properties dict

    Returns:
        dict with operation result
    """
    try:
        if action == "set_color":
            return _set_color(kwargs.get("color"))
        elif action == "set_hdri":
            return _set_hdri(kwargs.get("filepath"), kwargs.get("strength", 1.0))
        elif action == "set_strength":
            return _set_strength(kwargs.get("strength", 1.0))
        elif action == "get_properties":
            return _get_properties()
        elif action == "set_properties":
            return _set_properties(kwargs.get("properties", {}))
        else:
            return {"error": f"Unknown action: {action}. Use: set_color, set_hdri, "
                    "set_strength, get_properties, set_properties"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"World operation failed: {str(e)}"}


def _ensure_world():
    """Ensure scene has a world with nodes enabled.

    Only enables use_nodes if currently False AND node_tree is empty/None,
    to avoid rebuilding the node tree and destroying existing nodes (e.g. HDRI).
    """
    scene = bpy.context.scene
    if not scene.world:
        scene.world = bpy.data.worlds.new("World")
    if not scene.world.use_nodes:
        # Only flip use_nodes if there's no existing node tree to preserve
        if not scene.world.node_tree or len(scene.world.node_tree.nodes) == 0:
            scene.world.use_nodes = True
    return scene.world


def _get_bg_node(world):
    """Find the Background node in the world node tree."""
    for node in world.node_tree.nodes:
        if node.type == 'BACKGROUND':
            return node
    return None


def _set_color(color):
    """Set world background color."""
    if not color or len(color) < 3:
        return {"error": "color [r,g,b] is required"}

    world = _ensure_world()
    bg = _get_bg_node(world)
    if not bg:
        return {"error": "No Background node found in world"}

    # Remove any connected environment texture
    color_input = bg.inputs.get('Color')
    if color_input and color_input.links:
        for link in list(color_input.links):
            world.node_tree.links.remove(link)

    bg.inputs['Color'].default_value = (color[0], color[1], color[2], 1.0)

    return {
        "success": True,
        "message": f"World color set to [{color[0]:.3f}, {color[1]:.3f}, {color[2]:.3f}]",
        "color": color[:3],
    }


def _set_hdri(filepath, strength):
    """Set HDRI environment map."""
    if not filepath:
        return {"error": "filepath is required for set_hdri"}

    import os
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    world = _ensure_world()
    tree = world.node_tree

    # Find or create environment texture node
    env_tex = None
    for node in tree.nodes:
        if node.type == 'TEX_ENVIRONMENT':
            env_tex = node
            break

    if not env_tex:
        env_tex = tree.nodes.new('ShaderNodeTexEnvironment')
        env_tex.location = (-300, 300)

    # Load image
    img = bpy.data.images.load(filepath, check_existing=True)
    env_tex.image = img

    # Connect to background — create full graph if nodes are missing
    bg = _get_bg_node(world)
    if not bg:
        bg = tree.nodes.new('ShaderNodeBackground')
        bg.location = (0, 300)
    # Ensure World Output exists and is connected
    output = None
    for node in tree.nodes:
        if node.type == 'OUTPUT_WORLD':
            output = node
            break
    if not output:
        output = tree.nodes.new('ShaderNodeOutputWorld')
        output.location = (300, 300)
    if not bg.outputs['Background'].links:
        tree.links.new(bg.outputs['Background'], output.inputs['Surface'])
    tree.links.new(env_tex.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = strength

    return {
        "success": True,
        "message": f"HDRI set: {os.path.basename(filepath)} at strength {strength}",
        "filepath": filepath,
        "strength": strength,
    }


def _set_strength(strength):
    """Set environment light strength.

    Finds Background node directly if world already has nodes,
    avoiding _ensure_world() which can rebuild the node tree.
    """
    scene = bpy.context.scene
    world = scene.world
    if world and world.use_nodes and world.node_tree:
        bg = _get_bg_node(world)
    else:
        world = _ensure_world()
        bg = _get_bg_node(world)
    if not bg:
        return {"error": "No Background node found"}

    bg.inputs['Strength'].default_value = strength

    return {
        "success": True,
        "message": f"World strength set to {strength}",
        "strength": strength,
    }


def _get_properties():
    """Get current world properties."""
    scene = bpy.context.scene
    if not scene.world:
        return {
            "success": True,
            "has_world": False,
            "message": "No world assigned to scene",
        }

    world = scene.world
    props = {
        "name": world.name,
        "use_nodes": world.use_nodes,
    }

    if world.use_nodes and world.node_tree:
        bg = _get_bg_node(world)
        if bg:
            color_input = bg.inputs.get('Color')
            props["bg_strength"] = bg.inputs['Strength'].default_value

            if color_input and color_input.links:
                from_node = color_input.links[0].from_node
                if from_node.type == 'TEX_ENVIRONMENT':
                    props["has_hdri"] = True
                    props["hdri_image"] = from_node.image.name if from_node.image else None
                    props["hdri_filepath"] = from_node.image.filepath if from_node.image else None
                else:
                    props["has_hdri"] = False
                    props["connected_node"] = from_node.type
            else:
                props["has_hdri"] = False
                props["bg_color"] = list(color_input.default_value[:3])

        props["node_count"] = len(world.node_tree.nodes)

    return {
        "success": True,
        "has_world": True,
        "properties": props,
    }


def _set_properties(properties):
    """Set multiple world properties."""
    if not properties:
        return {"error": "properties dict is required"}

    world = _ensure_world()
    changed = []

    bg = _get_bg_node(world)

    if "color" in properties and bg:
        c = properties["color"]
        color_input = bg.inputs.get('Color')
        if color_input and color_input.links:
            for link in list(color_input.links):
                world.node_tree.links.remove(link)
        bg.inputs['Color'].default_value = (c[0], c[1], c[2], 1.0)
        changed.append("color")

    if "strength" in properties and bg:
        bg.inputs['Strength'].default_value = properties["strength"]
        changed.append("strength")

    return {
        "success": True,
        "message": f"Updated {len(changed)} world properties",
        "changed": changed,
    }
