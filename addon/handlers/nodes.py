import bpy
import traceback

from ._utils import set_properties_safe


def build_node_graph(target, nodes, links, clear_existing=True, input_sockets=None):
    """Universal node graph builder for geometry, shader, and compositor nodes.

    Args:
        target: "geometry:<object_name>" | "shader:<material_name>" | "compositor"
        nodes: list of dicts with {type, name, location, label, inputs, properties}
        links: list of dicts with {from_node, from_socket, to_node, to_socket}
        clear_existing: whether to clear existing nodes
        input_sockets: optional list of {name, type} for geometry node group interface.
            Socket types: NodeSocketGeometry, NodeSocketFloat, NodeSocketVector,
            NodeSocketColor, NodeSocketBool, NodeSocketInt, NodeSocketMaterial

    Returns:
        dict with success status and details
    """
    try:
        node_tree, tree_name = _resolve_target(target, create=True, input_sockets=input_sockets)

        if clear_existing:
            for node in list(node_tree.nodes):
                node_tree.nodes.remove(node)

        # For geometry targets with input_sockets, auto-create input/output nodes
        is_geo = target.startswith("geometry:")
        if is_geo and clear_existing:
            _ensure_group_io(node_tree, input_sockets)

        # Create nodes
        created_nodes = {}
        name_map = {}  # name -> node for reference by name in links
        failed_inputs = []
        failed_properties = []

        for i, node_data in enumerate(nodes):
            node_type = node_data.get("type", "")
            if not node_type:
                continue
            try:
                node = node_tree.nodes.new(type=node_type)
                created_nodes[i] = node

                if "name" in node_data:
                    node.name = node_data["name"]
                if "label" in node_data:
                    node.label = node_data["label"]
                if "location" in node_data:
                    node.location = node_data["location"]

                # Register in name map
                name_map[node.name] = node

                # Set node inputs (default values)
                if "inputs" in node_data:
                    for input_name, value in node_data["inputs"].items():
                        socket = _resolve_socket(node.inputs, input_name)
                        if socket is not None:
                            try:
                                socket.default_value = value
                            except Exception as e:
                                failed_inputs.append({
                                    "node_index": i,
                                    "input": input_name,
                                    "error": str(e)
                                })
                        else:
                            available = [s.name for s in node.inputs]
                            failed_inputs.append({
                                "node_index": i,
                                "input": input_name,
                                "error": f"not found, available: {available}"
                            })

                # Set node properties (attributes on the node itself)
                if "properties" in node_data:
                    set_ok, set_fail = set_properties_safe(node, node_data["properties"])
                    for f in set_fail:
                        failed_properties.append({
                            "node_index": i,
                            "property": f["name"],
                            "error": f["error"]
                        })
            except Exception as e:
                return {"error": f"Failed to create node {node_type} at index {i}: {str(e)}"}

        # Create links
        links_created = 0
        links_failed = []
        for link_data in links:
            try:
                from_node_ref = link_data.get("from_node")
                to_node_ref = link_data.get("to_node")
                from_socket = link_data.get("from_socket")
                to_socket = link_data.get("to_socket")

                # Resolve node by index or name
                from_node = _resolve_node_ref(from_node_ref, created_nodes, name_map, node_tree)
                to_node = _resolve_node_ref(to_node_ref, created_nodes, name_map, node_tree)

                if from_node is None or to_node is None:
                    links_failed.append({
                        "from_node": from_node_ref,
                        "to_node": to_node_ref,
                        "error": f"Node not found: "
                                 f"{'from_node' if from_node is None else 'to_node'}"
                    })
                    continue

                # Resolve output socket with fallback
                from_output = _resolve_socket(from_node.outputs, from_socket)
                if from_output is None:
                    available = [s.name for s in from_node.outputs]
                    links_failed.append({
                        "from_node": from_node_ref,
                        "from_socket": from_socket,
                        "error": f"Output socket not found, available: {available}"
                    })
                    continue

                # Resolve input socket with fallback
                to_input = _resolve_socket(to_node.inputs, to_socket)
                if to_input is None:
                    available = [s.name for s in to_node.inputs]
                    links_failed.append({
                        "to_node": to_node_ref,
                        "to_socket": to_socket,
                        "error": f"Input socket not found, available: {available}"
                    })
                    continue

                node_tree.links.new(from_output, to_input)
                links_created += 1
            except Exception as e:
                links_failed.append({"error": str(e)})

        # Validate links after building
        dangling = []
        for link in node_tree.links:
            if not link.is_valid:
                dangling.append({
                    "from": f"{link.from_node.name}.{link.from_socket.name}",
                    "to": f"{link.to_node.name}.{link.to_socket.name}",
                })

        # Build full node tree structure for response
        tree_structure = _serialize_node_tree(node_tree)

        result = {
            "success": True,
            "message": f"Node graph built for {target}",
            "tree_name": tree_name,
            "nodes_created": len(created_nodes),
            "links_created": links_created,
            "tree_structure": tree_structure,
        }
        if failed_inputs:
            result["failed_inputs"] = failed_inputs
        if failed_properties:
            result["failed_properties"] = failed_properties
        if links_failed:
            result["links_failed"] = links_failed
        if dangling:
            result["dangling_links"] = dangling

        return result
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to build node graph: {str(e)}"}


def get_node_graph(target):
    """Read back a node graph as structured data.

    Args:
        target: "geometry:<object_name>" | "shader:<material_name>" | "compositor"

    Returns:
        dict with nodes and links
    """
    try:
        node_tree, tree_name = _resolve_target(target, create=False)
        tree_structure = _serialize_node_tree(node_tree)

        return {
            "success": True,
            "tree_name": tree_name,
            "target": target,
            **tree_structure,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to get node graph: {str(e)}"}


def list_node_types(category="geometry"):
    """List available node types for a given category.

    Args:
        category: "geometry" | "shader" | "compositor"
    """
    try:
        node_types = _get_node_types_for_category(category)
        return {
            "success": True,
            "category": category,
            "node_types": node_types,
        }
    except Exception as e:
        return {"error": str(e)}


def _serialize_node_tree(node_tree):
    """Serialize a node tree to structured data."""
    nodes_data = []
    for i, node in enumerate(node_tree.nodes):
        node_info = {
            "index": i,
            "type": node.bl_idname,
            "name": node.name,
            "label": node.label,
            "location": [node.location.x, node.location.y],
        }
        # Collect input default values
        inputs = {}
        for inp in node.inputs:
            if hasattr(inp, "default_value"):
                try:
                    val = inp.default_value
                    if hasattr(val, '__iter__') and not isinstance(val, str):
                        val = [float(v) for v in val]
                    elif hasattr(val, 'real'):
                        val = float(val) if isinstance(val, float) else val
                    inputs[inp.name] = val
                except Exception:
                    pass
        if inputs:
            node_info["inputs"] = inputs
        nodes_data.append(node_info)

    # Build name-to-index map
    name_to_idx = {node.name: i for i, node in enumerate(node_tree.nodes)}

    links_data = []
    for link in node_tree.links:
        links_data.append({
            "from_node": name_to_idx.get(link.from_node.name),
            "from_node_name": link.from_node.name,
            "from_socket": link.from_socket.name,
            "to_node": name_to_idx.get(link.to_node.name),
            "to_node_name": link.to_node.name,
            "to_socket": link.to_socket.name,
        })

    return {"nodes": nodes_data, "links": links_data}


def _resolve_socket(socket_collection, ref):
    """Resolve a socket by string name or integer index, with fallback name matching."""
    if isinstance(ref, int):
        if 0 <= ref < len(socket_collection):
            return socket_collection[ref]
        return None

    if isinstance(ref, str):
        # Try exact match first
        sock = socket_collection.get(ref)
        if sock is not None:
            return sock
        # Fallback: iterate and try case-insensitive name match
        ref_lower = ref.lower()
        for s in socket_collection:
            if s.name.lower() == ref_lower:
                return s
        # Fallback: try partial match
        for s in socket_collection:
            if ref_lower in s.name.lower():
                return s
    return None


def _resolve_node_ref(ref, created_nodes, name_map, node_tree):
    """Resolve a node reference — integer index, or string name."""
    if isinstance(ref, int):
        return created_nodes.get(ref)
    if isinstance(ref, str):
        # Check name_map from this build
        if ref in name_map:
            return name_map[ref]
        # Check node_tree directly (for pre-existing nodes)
        node = node_tree.nodes.get(ref)
        if node:
            return node
    return None


def _ensure_group_io(node_tree, input_sockets=None):
    """Ensure NodeGroupInput and NodeGroupOutput exist in a geometry node tree.
    Creates interface sockets if input_sockets is provided.
    """
    # Check if they already exist
    has_input = any(n.bl_idname == 'NodeGroupInput' for n in node_tree.nodes)
    has_output = any(n.bl_idname == 'NodeGroupOutput' for n in node_tree.nodes)

    if not has_input:
        inp = node_tree.nodes.new('NodeGroupInput')
        inp.location = (-300, 0)

    if not has_output:
        out = node_tree.nodes.new('NodeGroupOutput')
        out.location = (600, 0)


def _resolve_target(target, create=False, input_sockets=None):
    """Resolve a target string to a node_tree and tree_name.

    Returns (node_tree, tree_name) tuple.
    """
    if target.startswith("geometry:"):
        obj_name = target[len("geometry:"):]
        obj = bpy.data.objects.get(obj_name)
        if not obj and create:
            bpy.ops.mesh.primitive_cube_add()
            obj = bpy.context.active_object
            obj.name = obj_name
        if not obj:
            raise ValueError(f"Object not found: {obj_name}")

        # Find or create geometry nodes modifier
        geo_mod = None
        for mod in obj.modifiers:
            if mod.type == 'NODES':
                geo_mod = mod
                break

        if geo_mod and geo_mod.node_group and create:
            old_group = geo_mod.node_group
            geo_mod.node_group = None
            if old_group.users == 0:
                bpy.data.node_groups.remove(old_group)

        if not geo_mod:
            geo_mod = obj.modifiers.new(name="GeometryNodes", type='NODES')

        if not geo_mod.node_group or create:
            node_group = bpy.data.node_groups.new(
                name=f"{obj_name}_geometry", type='GeometryNodeTree'
            )
            node_group.is_modifier = True

            # Create interface sockets
            node_group.interface.new_socket(
                'Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
            node_group.interface.new_socket(
                'Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

            # Add custom input sockets if provided
            if input_sockets:
                for sock_def in input_sockets:
                    sock_name = sock_def.get("name", "Value")
                    sock_type = sock_def.get("type", "NodeSocketFloat")
                    node_group.interface.new_socket(
                        sock_name, in_out='INPUT', socket_type=sock_type)

            geo_mod.node_group = node_group

        return geo_mod.node_group, geo_mod.node_group.name

    elif target.startswith("shader:"):
        mat_name = target[len("shader:"):]
        mat = bpy.data.materials.get(mat_name)
        if not mat and create:
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
        if not mat:
            raise ValueError(f"Material not found: {mat_name}")
        if not mat.use_nodes:
            mat.use_nodes = True
        return mat.node_tree, mat.name

    elif target == "compositor":
        scene = bpy.context.scene
        scene.use_nodes = True
        return scene.node_tree, "Compositor"

    else:
        raise ValueError(
            f"Invalid target: {target}. "
            "Use 'geometry:<object>', 'shader:<material>', or 'compositor'"
        )


def _get_node_types_for_category(category):
    """Return commonly used node types for a given category.
    Uses Blender 4.2+ node names only.
    """
    if category == "geometry":
        return {
            "Input": [
                "NodeGroupInput",
                "GeometryNodeObjectInfo",
                "GeometryNodeCollectionInfo",
                "GeometryNodeInputPosition",
                "GeometryNodeInputNormal",
                "GeometryNodeInputIndex",
                "GeometryNodeInputID",
            ],
            "Output": [
                "NodeGroupOutput",
            ],
            "Geometry": [
                "GeometryNodeJoinGeometry",
                "GeometryNodeTransform",
                "GeometryNodeSetPosition",
                "GeometryNodeBoundBox",
                "GeometryNodeConvexHull",
                "GeometryNodeDeleteGeometry",
                "GeometryNodeDuplicateElements",
                "GeometryNodeMergeByDistance",
                "GeometryNodeSeparateGeometry",
            ],
            "Mesh": [
                "GeometryNodeMeshBoolean",
                "GeometryNodeMeshToCurve",
                "GeometryNodeSubdivisionSurface",
                "GeometryNodeTriangulate",
                "GeometryNodeExtrudeMesh",
                "GeometryNodeFlipFaces",
                "GeometryNodeSetShadeSmooth",
                "GeometryNodeScaleElements",
            ],
            "Mesh Primitives": [
                "GeometryNodeMeshCircle",
                "GeometryNodeMeshCone",
                "GeometryNodeMeshCube",
                "GeometryNodeMeshCylinder",
                "GeometryNodeMeshGrid",
                "GeometryNodeMeshIcoSphere",
                "GeometryNodeMeshLine",
                "GeometryNodeMeshUVSphere",
            ],
            "Curve": [
                "GeometryNodeCurvePrimitiveCircle",
                "GeometryNodeCurvePrimitiveLine",
                "GeometryNodeCurvePrimitiveBezierSegment",
                "GeometryNodeCurveToMesh",
                "GeometryNodeFillCurve",
                "GeometryNodeTrimCurve",
                "GeometryNodeResampleCurve",
                "GeometryNodeSetCurveRadius",
            ],
            "Instances": [
                "GeometryNodeInstanceOnPoints",
                "GeometryNodeRealizeInstances",
                "GeometryNodeRotateInstances",
                "GeometryNodeScaleInstances",
                "GeometryNodeTranslateInstances",
            ],
            "Material": [
                "GeometryNodeSetMaterial",
                "GeometryNodeSetMaterialIndex",
                "GeometryNodeReplaceMaterial",
            ],
            "Volume": [
                "GeometryNodeMeshToVolume",
                "GeometryNodeVolumeToMesh",
                "GeometryNodeVolumeCube",
            ],
            "Math": [
                "ShaderNodeMath",
                "ShaderNodeVectorMath",
                "FunctionNodeCompare",
                "ShaderNodeMapRange",
                "ShaderNodeClamp",
                "FunctionNodeRandomValue",
            ],
            "Utilities": [
                "GeometryNodeSwitch",
                "FunctionNodeBooleanMath",
                "GeometryNodeAccumulateField",
                "GeometryNodeSampleIndex",
                "GeometryNodeSampleNearest",
            ],
        }
    elif category == "shader":
        return {
            "Input": [
                "ShaderNodeTexCoord",
                "ShaderNodeObjectInfo",
                "ShaderNodeUVMap",
                "ShaderNodeVertexColor",
                "ShaderNodeValue",
                "ShaderNodeRGB",
                "ShaderNodeFresnel",
                "ShaderNodeLayerWeight",
                "ShaderNodeAmbientOcclusion",
            ],
            "Output": [
                "ShaderNodeOutputMaterial",
                "ShaderNodeOutputWorld",
            ],
            "Shader": [
                "ShaderNodeBsdfPrincipled",
                "ShaderNodeBsdfDiffuse",
                "ShaderNodeBsdfGlossy",
                "ShaderNodeBsdfGlass",
                "ShaderNodeBsdfTransparent",
                "ShaderNodeBsdfTranslucent",
                "ShaderNodeEmission",
                "ShaderNodeMixShader",
                "ShaderNodeAddShader",
                "ShaderNodeBackground",
                "ShaderNodeSubsurfaceScattering",
            ],
            "Texture": [
                "ShaderNodeTexImage",
                "ShaderNodeTexEnvironment",
                "ShaderNodeTexNoise",
                "ShaderNodeTexVoronoi",
                "ShaderNodeTexWave",
                "ShaderNodeTexBrick",
                "ShaderNodeTexChecker",
                "ShaderNodeTexGradient",
                "ShaderNodeTexMagic",
            ],
            "Color": [
                "ShaderNodeMix",
                "ShaderNodeInvert",
                "ShaderNodeHueSaturation",
                "ShaderNodeBrightContrast",
                "ShaderNodeGamma",
                "ShaderNodeSeparateColor",
                "ShaderNodeCombineColor",
            ],
            "Vector": [
                "ShaderNodeMapping",
                "ShaderNodeNormalMap",
                "ShaderNodeBump",
                "ShaderNodeDisplacement",
                "ShaderNodeVectorTransform",
                "ShaderNodeSeparateXYZ",
                "ShaderNodeCombineXYZ",
            ],
            "Math": [
                "ShaderNodeMath",
                "ShaderNodeVectorMath",
                "ShaderNodeMapRange",
                "ShaderNodeClamp",
                "ShaderNodeMix",
            ],
            "Converter": [
                "ShaderNodeColorRamp",
                "ShaderNodeRGBToBW",
                "ShaderNodeBlackbody",
                "ShaderNodeWavelength",
            ],
        }
    elif category == "compositor":
        return {
            "Input": [
                "CompositorNodeRLayers",
                "CompositorNodeImage",
                "CompositorNodeValue",
                "CompositorNodeRGB",
                "CompositorNodeMask",
            ],
            "Output": [
                "CompositorNodeComposite",
                "CompositorNodeViewer",
                "CompositorNodeOutputFile",
            ],
            "Filter": [
                "CompositorNodeBlur",
                "CompositorNodeGlare",
                "CompositorNodeDenoise",
                "CompositorNodeDespeckle",
                "CompositorNodeFilter",
                "CompositorNodeBilateralblur",
            ],
            "Color": [
                "CompositorNodeBrightContrast",
                "CompositorNodeHueSat",
                "CompositorNodeColorBalance",
                "CompositorNodeTonemap",
                "CompositorNodeExposure",
                "CompositorNodeMix",
                "CompositorNodeAlphaOver",
                "CompositorNodeInvert",
            ],
            "Converter": [
                "CompositorNodeSeparateColor",
                "CompositorNodeCombineColor",
                "CompositorNodeMath",
                "CompositorNodeSetAlpha",
                "CompositorNodeIDMask",
            ],
            "Distort": [
                "CompositorNodeLensdist",
                "CompositorNodeMapUV",
                "CompositorNodeScale",
                "CompositorNodeTranslate",
                "CompositorNodeRotate",
                "CompositorNodeCrop",
            ],
        }
    else:
        return {"error": f"Unknown category: {category}. Use 'geometry', 'shader', or 'compositor'"}
