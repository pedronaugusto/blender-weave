import bpy
import mathutils
import io
import traceback
from contextlib import redirect_stdout
from ._utils import compute_world_aabb


def _get_fcurves(action):
    """Get fcurves from an action, compatible with both Blender 4.x and 5.x.

    Blender 5 changed the Action API — fcurves may not be a direct attribute.
    """
    if hasattr(action, 'fcurves'):
        return action.fcurves
    # Blender 5: fcurves are on action layers/strips
    try:
        for layer in action.layers:
            for strip in layer.strips:
                return strip.channelbags[0].fcurves
    except (AttributeError, IndexError):
        pass
    return []


def _set_interpolation(action, data_path, frame, interpolation):
    """Set keyframe interpolation, compatible with Blender 4.x and 5.x."""
    try:
        for fc in _get_fcurves(action):
            if fc.data_path == data_path:
                for kp in fc.keyframe_points:
                    if abs(kp.co[0] - frame) < 0.5:
                        kp.interpolation = interpolation
    except Exception:
        pass  # Interpolation is optional — don't fail the keyframe operation


def get_aabb(obj):
    """Returns the world-space axis-aligned bounding box (AABB) of an object."""
    if obj.type != 'MESH':
        raise TypeError("Object must be a mesh")
    local_bbox_corners = [mathutils.Vector(corner) for corner in obj.bound_box]
    world_bbox_corners = [obj.matrix_world @ corner for corner in local_bbox_corners]
    min_corner = mathutils.Vector(map(min, zip(*world_bbox_corners)))
    max_corner = mathutils.Vector(map(max, zip(*world_bbox_corners)))
    return [[*min_corner], [*max_corner]]


def get_scene_info():
    """Get information about the current Blender scene.

    Returns ALL objects with name+type+location. For scenes >100 objects,
    includes full name list but detailed info only for first 50.
    """
    try:
        objects = list(bpy.context.scene.objects)
        total = len(objects)

        # Type counts and polygon totals
        type_counts = {}
        total_polys = 0
        for obj in objects:
            type_counts[obj.type] = type_counts.get(obj.type, 0) + 1
            if obj.type == 'MESH' and obj.data:
                total_polys += len(obj.data.polygons)

        # Detailed info — first 50 for large scenes, all otherwise
        detail_limit = 50 if total > 100 else total
        detailed_objects = []
        for i, obj in enumerate(objects):
            if i >= detail_limit:
                break
            obj_info = {
                "name": obj.name,
                "type": obj.type,
                "location": [round(float(obj.location.x), 3),
                            round(float(obj.location.y), 3),
                            round(float(obj.location.z), 3)],
            }
            if obj.type == 'MESH' and obj.data:
                obj_info["polygon_count"] = len(obj.data.polygons)
            if obj.material_slots:
                obj_info["material_count"] = len(obj.material_slots)
            detailed_objects.append(obj_info)

        scene_info = {
            "name": bpy.context.scene.name,
            "object_count": total,
            "type_counts": type_counts,
            "total_polygons": total_polys,
            "materials_count": len(bpy.data.materials),
            "objects": detailed_objects,
        }

        # For large scenes, add a full name+type list
        if total > detail_limit:
            scene_info["all_objects"] = [
                {"name": obj.name, "type": obj.type}
                for obj in objects
            ]

        return scene_info
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def get_object_info(name):
    """Get detailed information about a specific object."""
    obj = bpy.data.objects.get(name)
    if not obj:
        raise ValueError(f"Object not found: {name}")

    obj_info = {
        "name": obj.name,
        "type": obj.type,
        "location": [obj.location.x, obj.location.y, obj.location.z],
        "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
        "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
        "visible": obj.visible_get(),
        "materials": [],
    }

    if obj.type == "MESH":
        obj_info["world_bounding_box"] = get_aabb(obj)

    # Mesh world bounds — traverses hierarchy for non-MESH objects
    if obj.type != 'MESH' and obj.children:
        aabb_min, aabb_max, aabb_center = compute_world_aabb(obj)
        if aabb_min is not None:
            obj_info["mesh_world_bounds"] = [[aabb_min.x, aabb_min.y, aabb_min.z],
                                              [aabb_max.x, aabb_max.y, aabb_max.z]]
            obj_info["mesh_world_center"] = [aabb_center.x, aabb_center.y, aabb_center.z]
    elif obj.type == 'MESH':
        # Add mesh_world_center for consistency
        aabb = obj_info.get("world_bounding_box")
        if aabb:
            obj_info["mesh_world_center"] = [
                (aabb[0][0] + aabb[1][0]) / 2,
                (aabb[0][1] + aabb[1][1]) / 2,
                (aabb[0][2] + aabb[1][2]) / 2,
            ]

    for slot in obj.material_slots:
        if slot.material:
            obj_info["materials"].append(slot.material.name)

    if obj.type == 'MESH' and obj.data:
        mesh = obj.data
        obj_info["mesh"] = {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
        }

    # Modifier info
    if obj.modifiers:
        obj_info["modifiers"] = [
            {"name": mod.name, "type": mod.type}
            for mod in obj.modifiers
        ]

    # Constraints info
    if obj.constraints:
        obj_info["constraints"] = [
            {"name": con.name, "type": con.type}
            for con in obj.constraints
        ]

    # Collections
    obj_info["collections"] = [col.name for col in obj.users_collection]

    return obj_info


def get_viewport_screenshot(max_size=800, filepath=None, format="png"):
    """Capture a screenshot of the current 3D viewport."""
    try:
        if not filepath:
            return {"error": "No filepath provided"}

        area = None
        for a in bpy.context.screen.areas:
            if a.type == 'VIEW_3D':
                area = a
                break

        if not area:
            return {"error": "No 3D viewport found"}

        with bpy.context.temp_override(area=area):
            bpy.ops.screen.screenshot_area(filepath=filepath)

        img = bpy.data.images.load(filepath)
        width, height = img.size

        if max(width, height) > max_size:
            scale = max_size / max(width, height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            img.scale(new_width, new_height)
            img.file_format = format.upper()
            img.save()
            width, height = new_width, new_height

        bpy.data.images.remove(img)

        return {
            "success": True,
            "width": width,
            "height": height,
            "filepath": filepath
        }
    except Exception as e:
        return {"error": str(e)}


def execute_code(code):
    """Execute arbitrary Blender Python code."""
    try:
        namespace = {"bpy": bpy}
        capture_buffer = io.StringIO()
        with redirect_stdout(capture_buffer):
            exec(code, namespace)
        captured_output = capture_buffer.getvalue()
        return {"executed": True, "result": captured_output}
    except Exception as e:
        raise Exception(f"Code execution error: {str(e)}")


def set_keyframe(object_name, frame, property="location", value=None,
                 interpolation=None, data_path=None):
    """Set a keyframe on an object at a specific frame.

    Args:
        object_name: Name of the object to keyframe
        frame: Frame number
        property: Property name — "location", "rotation", "scale", or use data_path for custom
        value: Value to set (e.g. [0,0,5]). If None, keyframes current value.
        interpolation: Keyframe interpolation — BEZIER, LINEAR, CONSTANT (optional)
        data_path: Custom data path for arbitrary properties (e.g. 'modifiers["Displace"].strength',
                   'constraints["Track To"].influence'). Overrides property param.
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}

        bpy.context.scene.frame_set(frame)

        if data_path:
            # Custom data path keyframing
            if value is not None:
                try:
                    obj.path_resolve(data_path)
                except ValueError:
                    return {"error": f"Invalid data_path: {data_path}"}

                parts = data_path.rsplit(".", 1)
                if len(parts) == 2:
                    parent = obj.path_resolve(parts[0])
                    setattr(parent, parts[1], value)
                else:
                    setattr(obj, data_path, value)

            obj.keyframe_insert(data_path=data_path, frame=frame)

            if interpolation and obj.animation_data and obj.animation_data.action:
                _set_interpolation(obj.animation_data.action, data_path, frame, interpolation)

            return {
                "success": True,
                "message": f"Keyframe set on {object_name} data_path='{data_path}' at frame {frame}",
                "object_name": object_name,
                "frame": frame,
                "data_path": data_path,
            }

        # Standard property keyframing
        prop_map = {
            "location": "location",
            "rotation": "rotation_euler",
            "scale": "scale",
        }

        bl_data_path = prop_map.get(property)
        if not bl_data_path:
            return {"error": f"Unsupported property: {property}. Use data_path for custom properties."}

        if value is not None:
            setattr(obj, bl_data_path, value)

        obj.keyframe_insert(data_path=bl_data_path, frame=frame)

        if interpolation and obj.animation_data and obj.animation_data.action:
            _set_interpolation(obj.animation_data.action, bl_data_path, frame, interpolation)

        return {
            "success": True,
            "message": f"Keyframe set on {object_name}.{property} at frame {frame}",
            "object_name": object_name,
            "frame": frame,
            "property": property,
            "value": list(getattr(obj, bl_data_path)),
        }
    except Exception as e:
        return {"error": f"Failed to set keyframe: {str(e)}"}


def analyze_scene(focus="general", max_size=1200):
    """Gather scene data for analysis. Screenshot captured separately by server."""
    try:
        data = {
            "scene_name": bpy.context.scene.name,
            "render_engine": bpy.context.scene.render.engine,
            "frame_current": bpy.context.scene.frame_current,
            "frame_range": [bpy.context.scene.frame_start, bpy.context.scene.frame_end],
        }

        # Object stats
        objects = list(bpy.context.scene.objects)
        data["object_count"] = len(objects)
        type_counts = {}
        total_polys = 0
        for obj in objects:
            type_counts[obj.type] = type_counts.get(obj.type, 0) + 1
            if obj.type == 'MESH' and obj.data:
                total_polys += len(obj.data.polygons)
        data["object_types"] = type_counts
        data["total_polygons"] = total_polys
        data["materials_count"] = len(bpy.data.materials)

        if focus in ("general", "materials"):
            data["materials"] = []
            for mat in bpy.data.materials[:20]:
                mat_info = {"name": mat.name, "use_nodes": mat.use_nodes}
                if mat.use_nodes and mat.node_tree:
                    mat_info["node_count"] = len(mat.node_tree.nodes)
                data["materials"].append(mat_info)

        if focus in ("general", "lighting"):
            data["lights"] = []
            for obj in objects:
                if obj.type == 'LIGHT':
                    light = obj.data
                    data["lights"].append({
                        "name": obj.name,
                        "type": light.type,
                        "energy": light.energy,
                        "color": [light.color.r, light.color.g, light.color.b],
                        "location": [obj.location.x, obj.location.y, obj.location.z],
                    })
            if bpy.context.scene.world and bpy.context.scene.world.use_nodes:
                data["world_has_hdri"] = any(
                    n.type == 'TEX_ENVIRONMENT'
                    for n in bpy.context.scene.world.node_tree.nodes
                )

        if focus in ("general", "composition"):
            cam = bpy.context.scene.camera
            if cam and cam.data:
                cd = cam.data
                data["camera"] = {
                    "name": cam.name,
                    "location": [cam.location.x, cam.location.y, cam.location.z],
                    "rotation": [cam.rotation_euler.x, cam.rotation_euler.y, cam.rotation_euler.z],
                    "focal_length": cd.lens,
                    "sensor_width": cd.sensor_width,
                    "dof_enabled": cd.dof.use_dof if hasattr(cd.dof, 'use_dof') else False,
                }
            data["resolution"] = [
                bpy.context.scene.render.resolution_x,
                bpy.context.scene.render.resolution_y,
            ]

        if focus in ("general", "performance"):
            data["total_polygons"] = total_polys
            modifier_count = sum(len(obj.modifiers) for obj in objects)
            data["total_modifiers"] = modifier_count
            data["image_count"] = len(bpy.data.images)
            data["node_group_count"] = len(bpy.data.node_groups)

        return data
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}
