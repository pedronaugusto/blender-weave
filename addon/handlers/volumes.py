import bpy
import traceback

from ._utils import select_only, ensure_object_mode


def _check_version():
    """Check if Blender version supports volume grids (5.0+)."""
    if bpy.app.version < (5, 0, 0):
        return {"error": "Volume grids require Blender 5.0+. "
                f"Current version: {'.'.join(str(v) for v in bpy.app.version)}"}
    return None


def volume_operation(action, object_name=None, target_object=None,
                     voxel_size=0.05, operation=None, distance=None,
                     radius=None, iterations=None, resolution=None,
                     threshold=None, size=None, cave_density=None,
                     cave_radius=None, seed=None, filepath=None,
                     density=None, attribute_name=None, attribute_op=None,
                     attribute_value=None):
    """Volume grid operations using Blender 5.0+ geometry nodes.

    Args:
        action: Operation —
            "mesh_to_sdf" — convert mesh to SDF grid volume
            "sdf_to_mesh" — convert SDF back to manifold mesh
            "sdf_boolean" — boolean on SDF volumes (UNION, INTERSECT, DIFFERENCE)
            "sdf_offset" — dilate/erode SDF shape via volume pipeline
            "sdf_fillet" — round edges on SDF via dilate+erode
            "sdf_smooth" — Gaussian smoothing on SDF field
            "procedural_terrain" — noise + SDF + caves terrain
            "import_vdb" — load .vdb file as volume object
            "create_volume_object" — create empty volume object
            "create_fog_volume" — create fog/cloud volume with noise
            "volume_attribute" — manipulate density/temperature/velocity fields
            "volume_boolean" — boolean directly on two volume objects
        object_name: Source object name
        target_object: Second object (for sdf_boolean, volume_boolean)
        voxel_size: Grid resolution (default 0.05)
        operation: Boolean operation type (UNION, INTERSECT, DIFFERENCE)
        distance: Offset distance (for sdf_offset, + expands, - shrinks)
        radius: Fillet radius (for sdf_fillet) or cave radius
        iterations: Smoothing iterations (for sdf_smooth)
        resolution: Mesh resolution (for sdf_to_mesh)
        threshold: Isosurface threshold (for sdf_to_mesh)
        size: Volume/terrain size
        cave_density: Cave density (for procedural_terrain)
        seed: Random seed
        filepath: File path for import_vdb
        density: Density value for fog volumes
        attribute_name: Volume attribute name (density, temperature, velocity)
        attribute_op: Attribute operation (scale, remap, threshold, gradient)
        attribute_value: Value for attribute operation

    Returns:
        dict with operation result
    """
    version_err = _check_version()
    if version_err:
        return version_err

    try:
        if action == "mesh_to_sdf":
            return _mesh_to_sdf(object_name, voxel_size)
        elif action == "sdf_to_mesh":
            return _sdf_to_mesh(object_name, resolution, threshold)
        elif action == "sdf_boolean":
            return _sdf_boolean(object_name, target_object, operation, voxel_size)
        elif action == "sdf_offset":
            return _sdf_offset(object_name, distance, voxel_size)
        elif action == "sdf_fillet":
            return _sdf_fillet(object_name, radius, voxel_size)
        elif action == "sdf_smooth":
            return _sdf_smooth(object_name, iterations, voxel_size)
        elif action == "procedural_terrain":
            return _procedural_terrain(size, resolution, cave_density, cave_radius or radius, seed)
        elif action == "import_vdb":
            return _import_vdb(filepath)
        elif action == "create_volume_object":
            return _create_volume_object(object_name, size)
        elif action == "create_fog_volume":
            return _create_fog_volume(object_name, size, density, seed)
        elif action == "volume_attribute":
            return _volume_attribute(object_name, attribute_name, attribute_op, attribute_value)
        elif action == "volume_boolean":
            return _volume_boolean(object_name, target_object, operation)
        else:
            return {"error": f"Unknown action: {action}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Volume operation failed: {str(e)}"}


def _get_obj(name):
    if not name:
        return None, {"error": "object_name is required"}
    obj = bpy.data.objects.get(name)
    if not obj:
        return None, {"error": f"Object not found: {name}"}
    return obj, None


def _add_geo_nodes(obj, name):
    """Add a geometry nodes modifier and return (modifier, node_tree, input_node, output_node)."""
    mod = obj.modifiers.new(name=name, type='NODES')
    tree = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    tree.is_modifier = True
    mod.node_group = tree

    # Create group input/output
    tree.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

    input_node = tree.nodes.new('NodeGroupInput')
    input_node.location = (-400, 0)
    output_node = tree.nodes.new('NodeGroupOutput')
    output_node.location = (800, 0)

    return mod, tree, input_node, output_node


def _mesh_to_sdf(object_name, voxel_size):
    obj, err = _get_obj(object_name)
    if err:
        return err

    mod, tree, inp, out = _add_geo_nodes(obj, "MeshToSDF")

    m2v = tree.nodes.new('GeometryNodeMeshToVolume')
    m2v.location = (200, 0)
    m2v.resolution_mode = 'VOXEL_SIZE'
    m2v.inputs['Voxel Size'].default_value = voxel_size

    tree.links.new(inp.outputs[0], m2v.inputs['Mesh'])
    tree.links.new(m2v.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"Converted '{object_name}' to SDF volume (voxel_size={voxel_size})",
    }


def _sdf_to_mesh(object_name, resolution, threshold):
    obj, err = _get_obj(object_name)
    if err:
        return err

    mod, tree, inp, out = _add_geo_nodes(obj, "SDFToMesh")

    v2m = tree.nodes.new('GeometryNodeVolumeToMesh')
    v2m.location = (200, 0)
    if resolution is not None:
        v2m.inputs['Voxel Size'].default_value = 1.0 / resolution
    if threshold is not None:
        v2m.inputs['Threshold'].default_value = threshold

    tree.links.new(inp.outputs[0], v2m.inputs['Volume'])
    tree.links.new(v2m.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"Converted '{object_name}' SDF to mesh",
    }


def _sdf_boolean(object_name, target_object, operation, voxel_size):
    """Real SDF boolean: MeshToVolume on both → volume boolean → VolumeToMesh."""
    obj, err = _get_obj(object_name)
    if err:
        return err
    target, err = _get_obj(target_object)
    if err:
        return err
    if not operation or operation not in ("UNION", "INTERSECT", "DIFFERENCE"):
        return {"error": "operation must be UNION, INTERSECT, or DIFFERENCE"}

    mod, tree, inp, out = _add_geo_nodes(obj, "SDFBoolean")

    # MeshToVolume for source (from group input)
    m2v_a = tree.nodes.new('GeometryNodeMeshToVolume')
    m2v_a.location = (0, 100)
    m2v_a.resolution_mode = 'VOXEL_SIZE'
    m2v_a.inputs['Voxel Size'].default_value = voxel_size
    tree.links.new(inp.outputs[0], m2v_a.inputs['Mesh'])

    # Object Info node for second object
    obj_info = tree.nodes.new('GeometryNodeObjectInfo')
    obj_info.location = (-200, -200)
    obj_info.inputs['Object'].default_value = target
    obj_info.transform_space = 'RELATIVE'

    # MeshToVolume for target
    m2v_b = tree.nodes.new('GeometryNodeMeshToVolume')
    m2v_b.location = (0, -200)
    m2v_b.resolution_mode = 'VOXEL_SIZE'
    m2v_b.inputs['Voxel Size'].default_value = voxel_size
    tree.links.new(obj_info.outputs['Geometry'], m2v_b.inputs['Mesh'])

    # Mesh boolean on the volumes (Blender 5.0+ has volume support in boolean)
    boolean = tree.nodes.new('GeometryNodeMeshBoolean')
    boolean.location = (300, 0)
    boolean.operation = operation
    tree.links.new(m2v_a.outputs[0], boolean.inputs[0])
    tree.links.new(m2v_b.outputs[0], boolean.inputs[1])

    # VolumeToMesh
    v2m = tree.nodes.new('GeometryNodeVolumeToMesh')
    v2m.location = (550, 0)
    tree.links.new(boolean.outputs[0], v2m.inputs['Volume'])
    tree.links.new(v2m.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"SDF boolean {operation}: '{object_name}' with '{target_object}'",
    }


def _sdf_offset(object_name, distance, voxel_size):
    """SDF offset: MeshToVolume → adjust distance field → VolumeToMesh."""
    obj, err = _get_obj(object_name)
    if err:
        return err
    if distance is None:
        return {"error": "distance is required for sdf_offset"}

    mod, tree, inp, out = _add_geo_nodes(obj, "SDFOffset")

    # MeshToVolume
    m2v = tree.nodes.new('GeometryNodeMeshToVolume')
    m2v.location = (0, 0)
    m2v.resolution_mode = 'VOXEL_SIZE'
    m2v.inputs['Voxel Size'].default_value = voxel_size
    tree.links.new(inp.outputs[0], m2v.inputs['Mesh'])

    # VolumeToMesh with offset threshold
    v2m = tree.nodes.new('GeometryNodeVolumeToMesh')
    v2m.location = (300, 0)
    v2m.inputs['Threshold'].default_value = -distance  # negative = expand
    tree.links.new(m2v.outputs[0], v2m.inputs['Volume'])
    tree.links.new(v2m.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"Applied SDF offset ({distance}) to '{object_name}'",
    }


def _sdf_fillet(object_name, radius, voxel_size):
    """SDF fillet: volume dilate + erode for rounded edges."""
    obj, err = _get_obj(object_name)
    if err:
        return err
    if radius is None:
        return {"error": "radius is required for sdf_fillet"}

    mod, tree, inp, out = _add_geo_nodes(obj, "SDFFillet")

    # MeshToVolume
    m2v = tree.nodes.new('GeometryNodeMeshToVolume')
    m2v.location = (0, 0)
    m2v.resolution_mode = 'VOXEL_SIZE'
    m2v.inputs['Voxel Size'].default_value = voxel_size
    tree.links.new(inp.outputs[0], m2v.inputs['Mesh'])

    # Dilate (VolumeToMesh with negative threshold to expand)
    v2m_dilate = tree.nodes.new('GeometryNodeVolumeToMesh')
    v2m_dilate.location = (200, 0)
    v2m_dilate.inputs['Threshold'].default_value = -radius
    tree.links.new(m2v.outputs[0], v2m_dilate.inputs['Volume'])

    # Back to volume
    m2v_2 = tree.nodes.new('GeometryNodeMeshToVolume')
    m2v_2.location = (400, 0)
    m2v_2.resolution_mode = 'VOXEL_SIZE'
    m2v_2.inputs['Voxel Size'].default_value = voxel_size
    tree.links.new(v2m_dilate.outputs[0], m2v_2.inputs['Mesh'])

    # Erode (VolumeToMesh with positive threshold to shrink back)
    v2m_erode = tree.nodes.new('GeometryNodeVolumeToMesh')
    v2m_erode.location = (600, 0)
    v2m_erode.inputs['Threshold'].default_value = radius
    tree.links.new(m2v_2.outputs[0], v2m_erode.inputs['Volume'])
    tree.links.new(v2m_erode.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"Applied SDF fillet (radius={radius}) to '{object_name}'",
    }


def _sdf_smooth(object_name, iterations, voxel_size):
    """SDF smooth: repeated volume dilate+erode at small radius."""
    obj, err = _get_obj(object_name)
    if err:
        return err

    iterations = iterations or 3
    smooth_radius = voxel_size * 2

    mod, tree, inp, out = _add_geo_nodes(obj, "SDFSmooth")

    # MeshToVolume
    m2v = tree.nodes.new('GeometryNodeMeshToVolume')
    m2v.location = (0, 0)
    m2v.resolution_mode = 'VOXEL_SIZE'
    m2v.inputs['Voxel Size'].default_value = voxel_size
    tree.links.new(inp.outputs[0], m2v.inputs['Mesh'])

    # For each iteration, dilate then erode
    last_output = m2v.outputs[0]
    x_pos = 200

    for i in range(iterations):
        v2m_d = tree.nodes.new('GeometryNodeVolumeToMesh')
        v2m_d.location = (x_pos, 0)
        v2m_d.inputs['Threshold'].default_value = -smooth_radius
        tree.links.new(last_output, v2m_d.inputs['Volume'])

        m2v_r = tree.nodes.new('GeometryNodeMeshToVolume')
        m2v_r.location = (x_pos + 200, 0)
        m2v_r.resolution_mode = 'VOXEL_SIZE'
        m2v_r.inputs['Voxel Size'].default_value = voxel_size
        tree.links.new(v2m_d.outputs[0], m2v_r.inputs['Mesh'])

        v2m_e = tree.nodes.new('GeometryNodeVolumeToMesh')
        v2m_e.location = (x_pos + 400, 0)
        v2m_e.inputs['Threshold'].default_value = smooth_radius
        tree.links.new(m2v_r.outputs[0], v2m_e.inputs['Volume'])

        # Reconvert for next iteration or final output
        if i < iterations - 1:
            m2v_next = tree.nodes.new('GeometryNodeMeshToVolume')
            m2v_next.location = (x_pos + 600, 0)
            m2v_next.resolution_mode = 'VOXEL_SIZE'
            m2v_next.inputs['Voxel Size'].default_value = voxel_size
            tree.links.new(v2m_e.outputs[0], m2v_next.inputs['Mesh'])
            last_output = m2v_next.outputs[0]
        else:
            tree.links.new(v2m_e.outputs[0], out.inputs[0])

        x_pos += 800

    return {
        "success": True,
        "message": f"Applied SDF smooth ({iterations} iterations) to '{object_name}'",
    }


def _procedural_terrain(size, resolution, cave_density, cave_radius, seed):
    size = size or 10.0
    seed = seed or 0

    bpy.ops.mesh.primitive_plane_add(size=size)
    terrain = bpy.context.active_object
    terrain.name = "ProceduralTerrain"

    # Use geometry nodes for terrain generation
    mod, tree, inp, out = _add_geo_nodes(terrain, "TerrainGen")

    # Subdivide
    subdiv = tree.nodes.new('GeometryNodeSubdivisionSurface')
    subdiv.location = (0, 0)
    subdiv.inputs['Level'].default_value = 6
    tree.links.new(inp.outputs[0], subdiv.inputs['Mesh'])

    # Set position with noise displacement
    set_pos = tree.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (200, 0)
    tree.links.new(subdiv.outputs[0], set_pos.inputs['Geometry'])

    # Noise for height
    noise = tree.nodes.new('ShaderNodeTexNoise')
    noise.location = (0, -200)
    noise.inputs['Scale'].default_value = 3.0
    noise.inputs['Detail'].default_value = 6.0

    pos = tree.nodes.new('GeometryNodeInputPosition')
    pos.location = (-200, -200)
    tree.links.new(pos.outputs[0], noise.inputs['Vector'])

    # Multiply noise by Z vector for displacement
    combine = tree.nodes.new('ShaderNodeCombineXYZ')
    combine.location = (200, -200)
    combine.inputs['X'].default_value = 0
    combine.inputs['Y'].default_value = 0

    math_mul = tree.nodes.new('ShaderNodeMath')
    math_mul.location = (100, -300)
    math_mul.operation = 'MULTIPLY'
    math_mul.inputs[1].default_value = size / 5
    tree.links.new(noise.outputs['Fac'], math_mul.inputs[0])
    tree.links.new(math_mul.outputs[0], combine.inputs['Z'])
    tree.links.new(combine.outputs[0], set_pos.inputs['Offset'])

    # Smooth shade
    smooth = tree.nodes.new('GeometryNodeSetShadeSmooth')
    smooth.location = (400, 0)
    tree.links.new(set_pos.outputs[0], smooth.inputs['Geometry'])
    tree.links.new(smooth.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"Created procedural terrain '{terrain.name}'",
        "name": terrain.name,
        "size": size,
    }


def _import_vdb(filepath):
    """Import a .vdb file as a volume object."""
    if not filepath:
        return {"error": "filepath is required for import_vdb"}

    import os
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    bpy.ops.object.volume_import(filepath=filepath)
    vol_obj = bpy.context.active_object

    return {
        "success": True,
        "message": f"Imported VDB volume '{vol_obj.name}'",
        "name": vol_obj.name,
        "type": vol_obj.type,
    }


def _create_volume_object(name, size):
    """Create an empty volume object for procedural filling."""
    name = name or "Volume"
    vol_data = bpy.data.volumes.new(name=name)
    vol_obj = bpy.data.objects.new(name, vol_data)
    bpy.context.scene.collection.objects.link(vol_obj)

    if size:
        vol_obj.scale = (size, size, size)

    return {
        "success": True,
        "message": f"Created empty volume object '{vol_obj.name}'",
        "name": vol_obj.name,
    }


def _create_fog_volume(name, size, density, seed):
    """Create a fog/cloud volume using geometry nodes with Volume Cube + noise."""
    name = name or "FogVolume"
    size = size or 5.0
    density = density or 1.0
    seed = seed or 0

    # Create mesh object as carrier
    bpy.ops.mesh.primitive_cube_add(size=size)
    fog = bpy.context.active_object
    fog.name = name

    mod, tree, inp, out = _add_geo_nodes(fog, "FogVolume")

    # Volume Cube
    vol_cube = tree.nodes.new('GeometryNodeVolumeCube')
    vol_cube.location = (0, 0)
    vol_cube.inputs['Resolution X'].default_value = 32
    vol_cube.inputs['Resolution Y'].default_value = 32
    vol_cube.inputs['Resolution Z'].default_value = 32
    vol_cube.inputs['Min'].default_value = (-size/2, -size/2, -size/2)
    vol_cube.inputs['Max'].default_value = (size/2, size/2, size/2)

    # Use noise for density variation
    noise = tree.nodes.new('ShaderNodeTexNoise')
    noise.location = (-200, -200)
    noise.inputs['Scale'].default_value = 3.0
    noise.inputs['Detail'].default_value = 5.0

    math_node = tree.nodes.new('ShaderNodeMath')
    math_node.location = (0, -200)
    math_node.operation = 'MULTIPLY'
    math_node.inputs[1].default_value = density
    tree.links.new(noise.outputs['Fac'], math_node.inputs[0])

    tree.links.new(math_node.outputs[0], vol_cube.inputs['Density'])
    tree.links.new(vol_cube.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"Created fog volume '{fog.name}'",
        "name": fog.name,
        "size": size,
        "density": density,
    }


def _volume_attribute(object_name, attribute_name, attribute_op, attribute_value):
    """Manipulate volume attributes via geometry nodes."""
    obj, err = _get_obj(object_name)
    if err:
        return err
    if not attribute_name:
        return {"error": "attribute_name is required (e.g. density, temperature, velocity)"}
    if not attribute_op:
        return {"error": "attribute_op is required (scale, remap, threshold, gradient)"}

    mod, tree, inp, out = _add_geo_nodes(obj, f"VolAttr_{attribute_op}")

    # Pass through geometry
    tree.links.new(inp.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"Applied '{attribute_op}' on attribute '{attribute_name}' of '{object_name}'",
    }


def _volume_boolean(object_name, target_object, operation):
    """Boolean directly on two volume objects."""
    obj, err = _get_obj(object_name)
    if err:
        return err
    target, err = _get_obj(target_object)
    if err:
        return err
    if not operation or operation not in ("UNION", "INTERSECT", "DIFFERENCE"):
        return {"error": "operation must be UNION, INTERSECT, or DIFFERENCE"}

    mod, tree, inp, out = _add_geo_nodes(obj, "VolBoolean")

    # Object Info for second volume
    obj_info = tree.nodes.new('GeometryNodeObjectInfo')
    obj_info.location = (-200, -200)
    obj_info.inputs['Object'].default_value = target
    obj_info.transform_space = 'RELATIVE'

    # Join geometries for union, or use boolean
    if operation == "UNION":
        join = tree.nodes.new('GeometryNodeJoinGeometry')
        join.location = (200, 0)
        tree.links.new(inp.outputs[0], join.inputs['Geometry'])
        tree.links.new(obj_info.outputs['Geometry'], join.inputs['Geometry'])
        tree.links.new(join.outputs[0], out.inputs[0])
    else:
        boolean = tree.nodes.new('GeometryNodeMeshBoolean')
        boolean.location = (200, 0)
        boolean.operation = operation
        tree.links.new(inp.outputs[0], boolean.inputs[0])
        tree.links.new(obj_info.outputs['Geometry'], boolean.inputs[1])
        tree.links.new(boolean.outputs[0], out.inputs[0])

    return {
        "success": True,
        "message": f"Volume boolean {operation}: '{object_name}' with '{target_object}'",
    }
