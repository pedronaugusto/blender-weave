import bpy
import math
import traceback


def procedural_generate(action, **params):
    """Dispatch procedural geometry generation.

    Args:
        action: "create_building" | "create_terrain" | "create_tree" | "create_road"
        **params: Action-specific parameters
    """
    dispatch = {
        "create_building": create_building,
        "create_terrain": create_terrain,
        "create_tree": create_tree,
        "create_road": create_road,
        "create_room": create_room,
    }
    handler = dispatch.get(action)
    if not handler:
        return {"error": f"Unknown procedural action: {action}. Use one of: {list(dispatch.keys())}"}
    try:
        return handler(**params)
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Procedural generation failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def create_building(floors=3, width=10.0, depth=8.0, floor_height=3.0,
                    window_rows=3, window_cols=4, balcony=False, name=None, **_kw):
    """Create a parametric building using geometry nodes.

    Args:
        floors: Number of floors
        width: Building width (X) in meters
        depth: Building depth (Y) in meters
        floor_height: Height of each floor in meters
        window_rows: Number of window rows per floor
        window_cols: Number of window columns per face
        balcony: Whether to add balcony extrusions
        name: Optional object name
    """
    total_height = floors * floor_height

    # Create base mesh
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    obj.name = name or "Building"
    obj.scale = (width, depth, total_height)
    obj.location = (0, 0, total_height / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Create geometry nodes modifier for window cutouts
    mod = obj.modifiers.new(name="BuildingGeoNodes", type='NODES')

    # Create a new geometry node group
    tree = bpy.data.node_groups.new("BuildingGenerator", 'GeometryNodeTree')
    mod.node_group = tree

    # Set up basic geo nodes: Group Input -> Group Output
    tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    input_node = tree.nodes.new('NodeGroupInput')
    input_node.location = (-400, 0)
    output_node = tree.nodes.new('NodeGroupOutput')
    output_node.location = (400, 0)

    # Add subdivide mesh for window detail
    subdiv = tree.nodes.new('GeometryNodeSubdivideMesh')
    subdiv.location = (-200, 0)
    subdiv.inputs['Level'].default_value = max(1, min(window_rows, 4))

    # Connect: Input -> Subdivide -> Output
    tree.links.new(input_node.outputs[0], subdiv.inputs['Mesh'])
    tree.links.new(subdiv.outputs['Mesh'], output_node.inputs[0])

    # Add window insets using extrude + scale
    extrude = tree.nodes.new('GeometryNodeExtrudeMesh')
    extrude.location = (0, 0)
    extrude.inputs['Offset Scale'].default_value = -0.05  # Inset windows

    # Reconnect through extrude
    tree.links.clear()
    tree.links.new(input_node.outputs[0], subdiv.inputs['Mesh'])
    tree.links.new(subdiv.outputs['Mesh'], extrude.inputs['Mesh'])
    tree.links.new(extrude.outputs['Mesh'], output_node.inputs[0])

    # Add balcony extrusions if requested
    if balcony:
        balcony_ext = tree.nodes.new('GeometryNodeExtrudeMesh')
        balcony_ext.location = (200, -200)
        balcony_ext.inputs['Offset Scale'].default_value = 0.8
        # Insert balcony extrude between window extrude and output
        tree.links.new(extrude.outputs['Mesh'], balcony_ext.inputs['Mesh'])
        tree.links.new(balcony_ext.outputs['Mesh'], output_node.inputs[0])

    # Create basic materials
    mat_facade = bpy.data.materials.new(name="Building_Facade")
    mat_facade.use_nodes = True
    bsdf = mat_facade.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.75, 0.72, 0.68, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.85

    mat_windows = bpy.data.materials.new(name="Building_Windows")
    mat_windows.use_nodes = True
    bsdf_w = mat_windows.node_tree.nodes.get("Principled BSDF")
    if bsdf_w:
        bsdf_w.inputs["Base Color"].default_value = (0.15, 0.2, 0.3, 1.0)
        bsdf_w.inputs["Roughness"].default_value = 0.1
        bsdf_w.inputs["Metallic"].default_value = 0.8

    obj.data.materials.append(mat_facade)
    obj.data.materials.append(mat_windows)

    return {
        "success": True,
        "name": obj.name,
        "floors": floors,
        "dimensions": [width, depth, total_height],
        "materials": ["Building_Facade", "Building_Windows"],
        "has_geo_nodes": True,
    }


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------

def create_terrain(size=50.0, resolution=64, height_scale=5.0, seed=0,
                   erosion=False, name=None, **_kw):
    """Create procedural terrain using geometry nodes.

    Args:
        size: Terrain size in meters (square)
        resolution: Grid resolution (vertices per side)
        height_scale: Maximum height displacement
        seed: Random seed for noise
        erosion: Apply erosion-like smoothing
        name: Optional object name
    """
    # Create grid
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=resolution,
        y_subdivisions=resolution,
        size=size,
    )
    obj = bpy.context.active_object
    obj.name = name or "Terrain"

    # Create geometry nodes for noise displacement
    mod = obj.modifiers.new(name="TerrainGeoNodes", type='NODES')
    tree = bpy.data.node_groups.new("TerrainGenerator", 'GeometryNodeTree')
    mod.node_group = tree

    # Interface
    tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    input_node = tree.nodes.new('NodeGroupInput')
    input_node.location = (-800, 0)
    output_node = tree.nodes.new('NodeGroupOutput')
    output_node.location = (400, 0)

    # Position node
    pos = tree.nodes.new('GeometryNodeInputPosition')
    pos.location = (-600, -200)

    # Offset position by seed to vary the noise pattern
    seed_offset = tree.nodes.new('ShaderNodeVectorMath')
    seed_offset.location = (-500, -200)
    seed_offset.operation = 'ADD'
    seed_offset.inputs[1].default_value = (seed * 100.0, seed * 100.0, 0.0)

    # Noise texture for terrain height
    noise = tree.nodes.new('ShaderNodeTexNoise')
    noise.location = (-400, -200)
    noise.inputs['Scale'].default_value = 3.0
    noise.inputs['Detail'].default_value = 8.0
    noise.inputs['Roughness'].default_value = 0.6
    noise.noise_dimensions = '3D'

    # Map noise to Z offset via combine/separate
    combine = tree.nodes.new('ShaderNodeCombineXYZ')
    combine.location = (-100, -200)

    # Multiply noise by height_scale
    multiply = tree.nodes.new('ShaderNodeMath')
    multiply.location = (-250, -200)
    multiply.operation = 'MULTIPLY'
    multiply.inputs[1].default_value = height_scale

    # Set Position node
    set_pos = tree.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (150, 0)

    # Connect
    tree.links.new(pos.outputs['Position'], seed_offset.inputs[0])
    tree.links.new(seed_offset.outputs['Vector'], noise.inputs['Vector'])
    tree.links.new(noise.outputs['Fac'], multiply.inputs[0])
    tree.links.new(multiply.outputs['Value'], combine.inputs['Z'])
    tree.links.new(input_node.outputs[0], set_pos.inputs['Geometry'])
    tree.links.new(combine.outputs['Vector'], set_pos.inputs['Offset'])
    tree.links.new(set_pos.outputs['Geometry'], output_node.inputs[0])

    # Smooth if erosion requested
    if erosion:
        smooth = tree.nodes.new('GeometryNodeSetShadeSmooth')
        smooth.location = (300, 0)
        tree.links.new(set_pos.outputs['Geometry'], smooth.inputs['Geometry'])
        tree.links.new(smooth.outputs['Geometry'], output_node.inputs[0])

    # Terrain material
    mat = bpy.data.materials.new(name="Terrain_Ground")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.25, 0.35, 0.15, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.95
    obj.data.materials.append(mat)

    return {
        "success": True,
        "name": obj.name,
        "size": size,
        "resolution": resolution,
        "height_scale": height_scale,
        "has_geo_nodes": True,
    }


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------

def create_tree(trunk_height=4.0, trunk_radius=0.2, branch_count=5,
                leaf_density=0.7, seed=0, name=None, **_kw):
    """Create a simple tree with trunk and leaf canopy.

    Args:
        trunk_height: Height of the trunk
        trunk_radius: Radius of the trunk
        branch_count: Number of branch levels (controls canopy complexity)
        leaf_density: Density of leaf particles (0-1)
        seed: Random seed
        name: Optional object name
    """
    import random
    rng = random.Random(seed)

    # Create trunk
    bpy.ops.mesh.primitive_cylinder_add(
        radius=trunk_radius,
        depth=trunk_height,
        vertices=8,
    )
    trunk = bpy.context.active_object
    trunk.name = name or "Tree"
    trunk.location.z = trunk_height / 2

    # Trunk material
    mat_trunk = bpy.data.materials.new(name="Tree_Bark")
    mat_trunk.use_nodes = True
    bsdf = mat_trunk.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.25, 0.15, 0.08, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.95
    trunk.data.materials.append(mat_trunk)

    # Create leaf canopy as ico sphere — branch_count controls subdivision
    canopy_subdivisions = max(1, min(branch_count, 5))
    canopy_radius = trunk_height * 0.4 * (1 + leaf_density * 0.5)
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=canopy_subdivisions,
        radius=canopy_radius,
    )
    canopy = bpy.context.active_object
    canopy.name = f"{trunk.name}_Canopy"
    canopy.location.z = trunk_height * 0.85

    # Randomize canopy vertices for organic look
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.transform.vertex_random(offset=canopy_radius * 0.15, seed=seed)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Leaf material
    mat_leaves = bpy.data.materials.new(name="Tree_Leaves")
    mat_leaves.use_nodes = True
    bsdf_l = mat_leaves.node_tree.nodes.get("Principled BSDF")
    if bsdf_l:
        green = 0.3 + rng.random() * 0.2
        bsdf_l.inputs["Base Color"].default_value = (0.1, green, 0.05, 1.0)
        bsdf_l.inputs["Roughness"].default_value = 0.7
        bsdf_l.inputs["Subsurface Weight"].default_value = 0.3
    canopy.data.materials.append(mat_leaves)

    # Parent canopy to trunk
    canopy.parent = trunk

    # Smooth shading on canopy
    for poly in canopy.data.polygons:
        poly.use_smooth = True

    return {
        "success": True,
        "name": trunk.name,
        "canopy_name": canopy.name,
        "trunk_height": trunk_height,
        "canopy_radius": canopy_radius,
        "materials": ["Tree_Bark", "Tree_Leaves"],
    }


# ---------------------------------------------------------------------------
# Road
# ---------------------------------------------------------------------------

def create_road(curve_name=None, width=6.0, sidewalk_width=1.5,
                curb_height=0.15, name=None, **_kw):
    """Create a road from a curve using geometry nodes.

    If no curve_name is given, creates a straight default road curve.

    Args:
        curve_name: Name of existing curve object to use as road path
        width: Road surface width in meters
        sidewalk_width: Width of sidewalk on each side
        curb_height: Height of curb
        name: Optional object name
    """
    # Get or create curve
    if curve_name:
        curve_obj = bpy.data.objects.get(curve_name)
        if not curve_obj or curve_obj.type != 'CURVE':
            return {"error": f"Curve not found or not a curve: {curve_name}"}
    else:
        # Create a default straight road curve
        bpy.ops.curve.primitive_bezier_curve_add()
        curve_obj = bpy.context.active_object
        curve_obj.name = name or "Road_Curve"
        # Extend the curve to be 20m long
        spline = curve_obj.data.splines[0]
        spline.bezier_points[0].co = (-10, 0, 0)
        spline.bezier_points[0].handle_right = (-5, 0, 0)
        spline.bezier_points[0].handle_left = (-15, 0, 0)
        spline.bezier_points[1].co = (10, 0, 0)
        spline.bezier_points[1].handle_left = (5, 0, 0)
        spline.bezier_points[1].handle_right = (15, 0, 0)

    # Add geometry nodes to convert curve to road mesh
    mod = curve_obj.modifiers.new(name="RoadGeoNodes", type='NODES')
    tree = bpy.data.node_groups.new("RoadGenerator", 'GeometryNodeTree')
    mod.node_group = tree

    # Interface
    tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    input_node = tree.nodes.new('NodeGroupInput')
    input_node.location = (-600, 0)
    output_node = tree.nodes.new('NodeGroupOutput')
    output_node.location = (600, 0)

    # Curve to Mesh for road surface
    curve_to_mesh = tree.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (-200, 0)

    # Profile curve (road cross-section) — a simple line
    curve_line = tree.nodes.new('GeometryNodeCurvePrimitiveLine')
    curve_line.location = (-400, -200)
    total_width = width + 2 * sidewalk_width
    curve_line.inputs['Start'].default_value = (-total_width / 2, 0, 0)
    curve_line.inputs['End'].default_value = (total_width / 2, 0, 0)

    # Resample profile for detail
    resample = tree.nodes.new('GeometryNodeResampleCurve')
    resample.location = (-200, -200)
    resample.inputs['Count'].default_value = 8

    tree.links.new(input_node.outputs[0], curve_to_mesh.inputs['Curve'])
    tree.links.new(curve_line.outputs['Curve'], resample.inputs['Curve'])
    tree.links.new(resample.outputs['Curve'], curve_to_mesh.inputs['Profile Curve'])
    tree.links.new(curve_to_mesh.outputs['Mesh'], output_node.inputs[0])

    # Road material
    mat_road = bpy.data.materials.new(name="Road_Asphalt")
    mat_road.use_nodes = True
    bsdf = mat_road.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.08, 0.08, 0.08, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9

    # Ensure the curve object has material slots
    if not curve_obj.data.materials:
        curve_obj.data.materials.append(mat_road)
    else:
        curve_obj.data.materials[0] = mat_road

    if name and curve_obj.name != name:
        curve_obj.name = name

    return {
        "success": True,
        "name": curve_obj.name,
        "width": width,
        "sidewalk_width": sidewalk_width,
        "total_width": total_width,
        "curb_height": curb_height,
        "materials": ["Road_Asphalt"],
        "has_geo_nodes": True,
    }


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------

def create_room(width=10.0, depth=8.0, height=3.0, wall_thickness=0.15,
                openings=None, name=None, **_kw):
    """Create a watertight interior room with optional door/window openings.

    Args:
        width: Room width (X) in meters
        depth: Room depth (Y) in meters
        height: Room height (Z) in meters
        wall_thickness: Wall thickness in meters
        openings: List of opening dicts:
            wall: "+x", "-x", "+y", "-y"
            type: "door" or "window"
            width: Opening width in meters
            height: Opening height in meters
            offset: Horizontal offset from wall center (meters)
            sill_height: Window sill height from floor (windows only)
        name: Optional object name
    """
    import bmesh

    if openings is None:
        openings = []

    obj_name = name or "Room"

    # Create outer box
    bpy.ops.mesh.primitive_cube_add(size=1)
    outer = bpy.context.active_object
    outer.name = obj_name
    outer.scale = (width, depth, height)
    outer.location = (0, 0, height / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Create inner box (hollow interior)
    bpy.ops.mesh.primitive_cube_add(size=1)
    inner = bpy.context.active_object
    inner.name = f"{obj_name}_inner_tmp"
    iw = width - 2 * wall_thickness
    id_ = depth - 2 * wall_thickness
    ih = height - wall_thickness  # floor thickness, open top inside
    inner.scale = (iw, id_, ih)
    inner.location = (0, 0, height / 2 + wall_thickness / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Boolean difference: outer - inner = hollow shell
    bool_mod = outer.modifiers.new(name="Hollow", type='BOOLEAN')
    bool_mod.operation = 'DIFFERENCE'
    bool_mod.object = inner
    bpy.context.view_layer.objects.active = outer
    bpy.ops.object.modifier_apply(modifier="Hollow")
    bpy.data.objects.remove(inner, do_unlink=True)

    # Cut openings
    cut_names = []
    for i, opening in enumerate(openings):
        wall = opening.get("wall", "+x")
        o_type = opening.get("type", "door")
        o_width = opening.get("width", 1.0)
        o_height = opening.get("height", 2.2 if o_type == "door" else 1.2)
        o_offset = opening.get("offset", 0.0)
        sill_height = opening.get("sill_height", 0.0 if o_type == "door" else 0.9)

        # Create cutter box
        bpy.ops.mesh.primitive_cube_add(size=1)
        cutter = bpy.context.active_object
        cutter.name = f"{obj_name}_cut_{i}"

        # Position cutter based on wall direction
        # Cutter must be thick enough to go through the wall
        cut_depth = wall_thickness * 3

        if wall in ("+x", "-x"):
            cutter.scale = (cut_depth, o_width, o_height)
            cx = (width / 2) if wall == "+x" else -(width / 2)
            cutter.location = (cx, o_offset, sill_height + o_height / 2)
        else:  # +y, -y
            cutter.scale = (o_width, cut_depth, o_height)
            cy = (depth / 2) if wall == "+y" else -(depth / 2)
            cutter.location = (o_offset, cy, sill_height + o_height / 2)

        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        # Boolean cut
        bool_mod = outer.modifiers.new(name=f"Opening_{i}", type='BOOLEAN')
        bool_mod.operation = 'DIFFERENCE'
        bool_mod.object = cutter
        bpy.context.view_layer.objects.active = outer
        bpy.ops.object.modifier_apply(modifier=f"Opening_{i}")
        bpy.data.objects.remove(cutter, do_unlink=True)
        cut_names.append(f"{wall} {o_type}")

    # Flip normals inward for interior rendering
    bpy.context.view_layer.objects.active = outer
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.flip_normals()
    # Clean up mesh
    bpy.ops.mesh.remove_doubles(threshold=0.001)
    bpy.ops.mesh.normals_make_consistent(inside=True)
    bpy.ops.object.mode_set(mode='OBJECT')

    # UV unwrap (smart project)
    bpy.context.view_layer.objects.active = outer
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Move origin to floor center
    # The room bottom is at Z=0, so cursor at (0,0,0) is floor center
    saved_cursor = list(bpy.context.scene.cursor.location)
    bpy.context.scene.cursor.location = (0, 0, 0)
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    bpy.context.scene.cursor.location = saved_cursor

    return {
        "success": True,
        "name": outer.name,
        "width": width,
        "depth": depth,
        "height": height,
        "wall_thickness": wall_thickness,
        "openings": cut_names,
        "has_uvs": True,
    }
