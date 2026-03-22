import bpy
import math
import mathutils
import traceback

from ._utils import compute_world_aabb


def create_object(type, name=None, location=None, rotation=None, scale=None,
                  size=1.0, dimensions=None, segments=None, ring_count=None,
                  vertices=None, depth=None, radius=None,
                  major_radius=None, minor_radius=None,
                  energy=None, color=None, spot_size=None, spot_blend=None):
    """Create a new object in the scene.

    Args:
        type: Object type — CUBE, SPHERE, CYLINDER, PLANE, CONE, TORUS,
              UV_SPHERE, ICO_SPHERE, CIRCLE, GRID,
              EMPTY, EMPTY_ARROWS, EMPTY_SPHERE, EMPTY_CUBE,
              POINT_LIGHT, SUN_LIGHT, SPOT_LIGHT, AREA_LIGHT, CAMERA
        name: Optional display name
        location: [x, y, z] position
        rotation: [x, y, z] rotation in degrees
        scale: [x, y, z] scale
        size: Base size for primitives (default 1.0). Note: Blender's cube
              primitive extends ±size/2, so size=1.0 creates a 1m cube.
        dimensions: [width, height, depth] in meters. Alternative to size+scale
              that creates an object with exact world dimensions. Overrides size
              and scale parameters. E.g. dimensions=[0.5, 0.5, 0.04] creates a
              0.5m x 0.5m x 0.04m object.
        segments: Segment count for cylinders, cones, circles, UV spheres
        ring_count: Ring count for UV spheres
        vertices: Subdivision count for ico spheres
        depth: Depth/height for cylinders and cones
        radius: Radius for cylinders, cones, circles
        major_radius: Major radius for torus
        minor_radius: Minor radius for torus
        energy: Light energy/power
        color: Light color [r, g, b] (0-1 range)
        spot_size: Spot light cone angle in degrees
        spot_blend: Spot light edge softness (0-1)

    Returns:
        dict with name, type, location, rotation, scale, dimensions
    """
    try:
        loc = tuple(location) if location else (0, 0, 0)
        rot = tuple(math.radians(r) for r in rotation) if rotation else (0, 0, 0)

        # Handle dimensions parameter — compute scale from desired dimensions
        if dimensions and len(dimensions) == 3:
            # Create unit-size primitive, then scale to exact dimensions
            # Blender primitives have size=2 by default (±1 on each axis)
            size = 1.0
            scl = (dimensions[0], dimensions[1], dimensions[2])
        else:
            scl = tuple(scale) if scale else (1, 1, 1)

        obj = None
        mesh_types = {
            "CUBE": _create_cube,
            "SPHERE": _create_uv_sphere,
            "UV_SPHERE": _create_uv_sphere,
            "ICO_SPHERE": _create_ico_sphere,
            "CYLINDER": _create_cylinder,
            "PLANE": _create_plane,
            "CONE": _create_cone,
            "TORUS": _create_torus,
            "CIRCLE": _create_circle,
            "GRID": _create_grid,
        }

        type_upper = type.upper()

        if type_upper in mesh_types:
            obj = mesh_types[type_upper](
                size=size, segments=segments, ring_count=ring_count,
                vertices=vertices, depth=depth, radius=radius,
                major_radius=major_radius, minor_radius=minor_radius,
            )
        elif type_upper.startswith("EMPTY") or type_upper == "EMPTY":
            empty_type = "PLAIN_AXES"
            if type_upper == "EMPTY_ARROWS":
                empty_type = "ARROWS"
            elif type_upper == "EMPTY_SPHERE":
                empty_type = "SPHERE"
            elif type_upper == "EMPTY_CUBE":
                empty_type = "CUBE"
            obj = bpy.data.objects.new(name or "Empty", None)
            obj.empty_display_type = empty_type
            obj.empty_display_size = size
            bpy.context.scene.collection.objects.link(obj)
        elif type_upper in ("POINT_LIGHT", "SUN_LIGHT", "SPOT_LIGHT", "AREA_LIGHT"):
            light_type = type_upper.replace("_LIGHT", "").replace("POINT", "POINT")
            light_map = {"POINT": "POINT", "SUN": "SUN", "SPOT": "SPOT", "AREA": "AREA"}
            lt = light_map.get(light_type, "POINT")
            light_data = bpy.data.lights.new(name=name or f"{lt.title()}Light", type=lt)
            if energy is not None:
                light_data.energy = energy
            if color is not None:
                light_data.color = tuple(color[:3])
            if lt == "SPOT":
                if spot_size is not None:
                    light_data.spot_size = math.radians(spot_size)
                if spot_blend is not None:
                    light_data.spot_blend = spot_blend
            obj = bpy.data.objects.new(name or light_data.name, light_data)
            bpy.context.scene.collection.objects.link(obj)
        elif type_upper == "CAMERA":
            cam_data = bpy.data.cameras.new(name=name or "Camera")
            obj = bpy.data.objects.new(name or cam_data.name, cam_data)
            bpy.context.scene.collection.objects.link(obj)
        else:
            return {"error": f"Unknown object type: {type}"}

        if obj is None:
            return {"error": "Failed to create object"}

        if name and obj.name != name:
            obj.name = name

        obj.location = loc
        obj.rotation_euler = rot
        obj.scale = scl

        result = {
            "success": True,
            "name": obj.name,
            "type": obj.type,
            "location": list(obj.location),
            "rotation": [math.degrees(r) for r in obj.rotation_euler],
            "scale": list(obj.scale),
        }
        # Report actual world dimensions for mesh objects
        if obj.type == 'MESH' and obj.data:
            result["dimensions"] = list(obj.dimensions)
        return result
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to create object: {str(e)}"}


def _create_cube(size=1.0, **_kwargs):
    bpy.ops.mesh.primitive_cube_add(size=size)
    return bpy.context.active_object


def _create_uv_sphere(size=1.0, segments=None, ring_count=None, radius=None, **_kwargs):
    kwargs = {"radius": radius or size / 2}
    if segments is not None:
        kwargs["segments"] = segments
    if ring_count is not None:
        kwargs["ring_count"] = ring_count
    bpy.ops.mesh.primitive_uv_sphere_add(**kwargs)
    return bpy.context.active_object


def _create_ico_sphere(size=1.0, vertices=None, radius=None, **_kwargs):
    kwargs = {"radius": radius or size / 2}
    if vertices is not None:
        kwargs["subdivisions"] = vertices
    bpy.ops.mesh.primitive_ico_sphere_add(**kwargs)
    return bpy.context.active_object


def _create_cylinder(size=1.0, segments=None, depth=None, radius=None, **_kwargs):
    kwargs = {"radius": radius or size / 2, "depth": depth or size}
    if segments is not None:
        kwargs["vertices"] = segments
    bpy.ops.mesh.primitive_cylinder_add(**kwargs)
    return bpy.context.active_object


def _create_plane(size=1.0, **_kwargs):
    bpy.ops.mesh.primitive_plane_add(size=size)
    return bpy.context.active_object


def _create_cone(size=1.0, segments=None, depth=None, radius=None, **_kwargs):
    kwargs = {"radius1": radius or size / 2, "depth": depth or size}
    if segments is not None:
        kwargs["vertices"] = segments
    bpy.ops.mesh.primitive_cone_add(**kwargs)
    return bpy.context.active_object


def _create_torus(size=1.0, segments=None, major_radius=None, minor_radius=None, **_kwargs):
    kwargs = {
        "major_radius": major_radius or size / 2,
        "minor_radius": minor_radius or size / 6,
    }
    if segments is not None:
        kwargs["major_segments"] = segments
    bpy.ops.mesh.primitive_torus_add(**kwargs)
    return bpy.context.active_object


def _create_circle(size=1.0, segments=None, radius=None, **_kwargs):
    kwargs = {"radius": radius or size / 2}
    if segments is not None:
        kwargs["vertices"] = segments
    bpy.ops.mesh.primitive_circle_add(**kwargs)
    return bpy.context.active_object


def _create_grid(size=1.0, **_kwargs):
    bpy.ops.mesh.primitive_grid_add(size=size)
    return bpy.context.active_object


def _get_mesh_descendants(obj):
    """Recursively collect all MESH descendants of an object.

    Traverses the full hierarchy depth-first. Used for Sketchfab imports
    where meshes are nested under multiple levels of EMPTY objects.

    Returns:
        list of bpy.types.Object with type == 'MESH'
    """
    meshes = []
    if obj.type == 'MESH':
        meshes.append(obj)
    for child in obj.children:
        meshes.extend(_get_mesh_descendants(child))
    return meshes


def transform_object(object_name, location=None, rotation=None, scale=None, mode="set",
                     recursive=False, look_at=None):
    """Transform an object's location, rotation, and/or scale.

    Args:
        object_name: Name of the object to transform
        location: [x, y, z] position
        rotation: [x, y, z] rotation in degrees
        scale: [x, y, z] scale
        mode: "set" for absolute values, "delta" for additive
        recursive: When True and target is an EMPTY parent (e.g. Sketchfab
                   hierarchy), finds all MESH descendants and applies transforms
                   correctly through the hierarchy root.
        look_at: [x, y, z] target position — computes Z rotation to face that
                 point. Only rotates around Z axis (keeps X/Y unchanged).
                 When combined with recursive=True, computes facing direction
                 from the mesh AABB center.

    Returns:
        dict with name, location, rotation, scale
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}

        # Determine if we're in recursive mode (Sketchfab hierarchy)
        is_hierarchy = recursive and (obj.type == 'EMPTY' or len(obj.children) > 0)
        mesh_descendants = []
        if is_hierarchy:
            mesh_descendants = _get_mesh_descendants(obj)

        if not is_hierarchy:
            # ── Simple object transform ──
            if mode == "set":
                if location is not None:
                    obj.location = tuple(location)
                if rotation is not None:
                    obj.rotation_euler = tuple(math.radians(r) for r in rotation)
                if scale is not None:
                    obj.scale = tuple(scale)
            elif mode == "delta":
                if location is not None:
                    obj.location.x += location[0]
                    obj.location.y += location[1]
                    obj.location.z += location[2]
                if rotation is not None:
                    obj.rotation_euler.x += math.radians(rotation[0])
                    obj.rotation_euler.y += math.radians(rotation[1])
                    obj.rotation_euler.z += math.radians(rotation[2])
                if scale is not None:
                    obj.scale.x *= scale[0]
                    obj.scale.y *= scale[1]
                    obj.scale.z *= scale[2]
            else:
                return {"error": f"Unknown mode: {mode}. Use 'set' or 'delta'"}

            # Handle look_at for simple objects
            if look_at is not None:
                target = mathutils.Vector(look_at)
                origin = obj.matrix_world.translation.copy()
                dx = target.x - origin.x
                dy = target.y - origin.y
                obj.rotation_euler.z = math.atan2(dx, -dy)
        else:
            # ── Sketchfab / hierarchy transform ──
            # Parent transforms don't propagate reliably to Sketchfab mesh
            # children. Instead, compute a world-space transform matrix and
            # apply it directly to every mesh descendant's matrix_world.

            # 1. Compute the group's current AABB center from mesh descendants
            all_corners = []
            for desc in mesh_descendants:
                try:
                    all_corners.extend(
                        desc.matrix_world @ mathutils.Vector(c) for c in desc.bound_box
                    )
                except Exception:
                    pass
            if all_corners:
                group_center = mathutils.Vector((
                    sum(c.x for c in all_corners) / len(all_corners),
                    sum(c.y for c in all_corners) / len(all_corners),
                    sum(c.z for c in all_corners) / len(all_corners),
                ))
            else:
                group_center = obj.matrix_world.translation.copy()

            # 2. Build the transform matrix
            transform = mathutils.Matrix.Identity(4)

            # Translation
            if location is not None:
                if mode == "set":
                    delta = mathutils.Vector(location) - group_center
                else:  # delta
                    delta = mathutils.Vector(location)
                transform = mathutils.Matrix.Translation(delta) @ transform

            # Rotation (around group center)
            if rotation is not None:
                if mode == "set":
                    rot_rad = [math.radians(r) for r in rotation]
                else:  # delta
                    rot_rad = [math.radians(r) for r in rotation]
                rot_mat = mathutils.Euler(rot_rad, 'XYZ').to_matrix().to_4x4()
                # Rotate around group center (or new center if location was set)
                pivot = group_center if location is None else (
                    mathutils.Vector(location) if mode == "set" else group_center + mathutils.Vector(location)
                )
                transform = (
                    mathutils.Matrix.Translation(pivot) @
                    rot_mat @
                    mathutils.Matrix.Translation(-pivot) @
                    transform
                )

            # Handle look_at — compute Z rotation to face target from group center
            if look_at is not None:
                target = mathutils.Vector(look_at)
                # Origin for angle: new center after location change
                if location is not None:
                    if mode == "set":
                        origin = mathutils.Vector(location)
                    else:
                        origin = group_center + mathutils.Vector(location)
                else:
                    origin = group_center
                dx = target.x - origin.x
                dy = target.y - origin.y
                z_angle = math.atan2(dx, -dy)
                # Subtract current facing angle (derived from first mesh descendant)
                # to get the delta rotation needed
                rot_mat = mathutils.Matrix.Rotation(z_angle, 4, 'Z')
                pivot = origin
                transform = (
                    mathutils.Matrix.Translation(pivot) @
                    rot_mat @
                    mathutils.Matrix.Translation(-pivot) @
                    transform
                )

            # Scale (around group center)
            if scale is not None:
                if mode == "set":
                    scale_vec = mathutils.Vector(scale)
                else:
                    scale_vec = mathutils.Vector(scale)
                scale_mat = mathutils.Matrix.Diagonal(scale_vec).to_4x4()
                pivot = group_center
                transform = (
                    mathutils.Matrix.Translation(pivot) @
                    scale_mat @
                    mathutils.Matrix.Translation(-pivot) @
                    transform
                )

            # 3. Apply transform to all mesh descendants
            for desc in mesh_descendants:
                desc.matrix_world = transform @ desc.matrix_world

            bpy.context.view_layer.update()

        result = {
            "success": True,
            "name": obj.name,
            "location": list(obj.location),
            "rotation": [math.degrees(r) for r in obj.rotation_euler],
            "scale": list(obj.scale),
        }
        if is_hierarchy:
            result["recursive"] = True
            result["mesh_descendants"] = len(mesh_descendants)
            # Report actual mesh center after transform
            new_corners = []
            for desc in mesh_descendants:
                try:
                    new_corners.extend(
                        desc.matrix_world @ mathutils.Vector(c) for c in desc.bound_box
                    )
                except Exception:
                    pass
            if new_corners:
                result["mesh_center"] = [
                    round(sum(c.x for c in new_corners) / len(new_corners), 3),
                    round(sum(c.y for c in new_corners) / len(new_corners), 3),
                    round(sum(c.z for c in new_corners) / len(new_corners), 3),
                ]
        if look_at is not None:
            result["look_at"] = list(look_at)
        return result
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to transform object: {str(e)}"}


def duplicate_object(object_name, linked=False, new_name=None):
    """Duplicate an object.

    Args:
        object_name: Name of the object to duplicate
        linked: If True, shares mesh data (linked duplicate)
        new_name: Optional name for the duplicate

    Returns:
        dict with name, type, location, source
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}

        if linked:
            new_obj = obj.copy()
        else:
            new_obj = obj.copy()
            if obj.data:
                new_obj.data = obj.data.copy()

        if new_name:
            new_obj.name = new_name

        # Link to same collections as original
        for col in obj.users_collection:
            col.objects.link(new_obj)
        if not obj.users_collection:
            bpy.context.scene.collection.objects.link(new_obj)

        return {
            "success": True,
            "name": new_obj.name,
            "type": new_obj.type,
            "location": list(new_obj.location),
            "source": object_name,
            "linked": linked,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to duplicate object: {str(e)}"}


def batch_transform(transforms):
    """Apply transforms to multiple objects in a single call.

    Args:
        transforms: List of dicts, each with:
            object_name, location, rotation, scale, mode ("set"/"delta")

    Returns:
        dict with results list and count
    """
    try:
        results = []
        for t in transforms:
            obj_name = t.get("object_name")
            if not obj_name:
                results.append({"error": "object_name required"})
                continue
            r = transform_object(
                object_name=obj_name,
                location=t.get("location"),
                rotation=t.get("rotation"),
                scale=t.get("scale"),
                mode=t.get("mode", "set"),
                recursive=t.get("recursive", False),
                look_at=t.get("look_at"),
            )
            results.append(r)
        return {"success": True, "results": results, "count": len(results)}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed batch transform: {str(e)}"}


def place_relative(object_name, relative_to, relation="in_front", distance=0.5,
                    facing="toward", offset=None):
    """Place an object relative to another using spatial relations.

    Args:
        object_name: Name of object to place
        relative_to: Name of reference object
        relation: "in_front", "behind", "left_of", "right_of", "on_top", "below", "centered_on"
        distance: Gap in meters between closest faces (default 0.5)
        facing: "toward" (face reference), "away", "same" (match rotation), "opposite"
        offset: Optional [x, y, z] additional offset in meters

    Returns:
        dict with name, location, rotation
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}
        ref = bpy.data.objects.get(relative_to)
        if not ref:
            return {"error": f"Reference object not found: {relative_to}"}

        # Get world-space AABBs
        def get_world_aabb(o):
            corners = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
            xs = [c.x for c in corners]
            ys = [c.y for c in corners]
            zs = [c.z for c in corners]
            return (
                mathutils.Vector((min(xs), min(ys), min(zs))),
                mathutils.Vector((max(xs), max(ys), max(zs))),
            )

        ref_min, ref_max = get_world_aabb(ref)
        ref_center = (ref_min + ref_max) / 2
        ref_half = (ref_max - ref_min) / 2

        obj_min, obj_max = get_world_aabb(obj)
        obj_half = (obj_max - obj_min) / 2

        # Map relation to direction vector
        # Blender convention: -Y is front, +Y is back, +X is right, -X is left
        relation_map = {
            "in_front": mathutils.Vector((0, -1, 0)),
            "behind": mathutils.Vector((0, 1, 0)),
            "left_of": mathutils.Vector((-1, 0, 0)),
            "right_of": mathutils.Vector((1, 0, 0)),
            "on_top": mathutils.Vector((0, 0, 1)),
            "below": mathutils.Vector((0, 0, -1)),
            "centered_on": mathutils.Vector((0, 0, 0)),
        }

        direction = relation_map.get(relation)
        if direction is None:
            return {"error": f"Unknown relation: {relation}. Use: {list(relation_map.keys())}"}

        if relation == "centered_on":
            new_pos = ref_center.copy()
        else:
            # Transform direction by reference object's rotation
            ref_rot = ref.matrix_world.to_3x3()
            world_dir = (ref_rot @ direction).normalized()

            # Compute position: ref_center + direction * (ref_half + gap + obj_half)
            # Project halves along the direction axis
            abs_dir = mathutils.Vector((abs(world_dir.x), abs(world_dir.y), abs(world_dir.z)))
            ref_extent = ref_half.x * abs_dir.x + ref_half.y * abs_dir.y + ref_half.z * abs_dir.z
            obj_extent = obj_half.x * abs_dir.x + obj_half.y * abs_dir.y + obj_half.z * abs_dir.z

            new_pos = ref_center + world_dir * (ref_extent + distance + obj_extent)

            # For on_top/below, preserve XY of reference center
            if relation == "on_top":
                new_pos.x = ref_center.x
                new_pos.y = ref_center.y
            elif relation == "below":
                new_pos.x = ref_center.x
                new_pos.y = ref_center.y

        # Apply offset
        if offset:
            new_pos.x += offset[0]
            new_pos.y += offset[1]
            new_pos.z += offset[2]

        obj.location = new_pos

        # Handle facing
        if facing != "same" and relation != "centered_on":
            if facing == "toward":
                # Point object's -Y toward reference center
                direction_to_ref = ref_center - new_pos
                direction_to_ref.z = 0  # Only rotate in XY plane
                if direction_to_ref.length > 0.001:
                    angle = math.atan2(direction_to_ref.x, -direction_to_ref.y)
                    obj.rotation_euler = (obj.rotation_euler.x, obj.rotation_euler.y, angle)
            elif facing == "away":
                direction_from_ref = new_pos - ref_center
                direction_from_ref.z = 0
                if direction_from_ref.length > 0.001:
                    angle = math.atan2(direction_from_ref.x, -direction_from_ref.y)
                    obj.rotation_euler = (obj.rotation_euler.x, obj.rotation_euler.y, angle)
            elif facing == "opposite":
                obj.rotation_euler = (
                    ref.rotation_euler.x,
                    ref.rotation_euler.y,
                    ref.rotation_euler.z + math.pi,
                )
        elif facing == "same":
            obj.rotation_euler = ref.rotation_euler.copy()

        return {
            "success": True,
            "name": obj.name,
            "location": list(obj.location),
            "rotation": [math.degrees(r) for r in obj.rotation_euler],
            "relative_to": relative_to,
            "relation": relation,
            "distance": distance,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to place relative: {str(e)}"}


def _collect_all_descendants(obj):
    """Recursively collect all descendants of an object, bottom-up order."""
    descendants = []
    for child in obj.children:
        descendants.extend(_collect_all_descendants(child))
    descendants.append(obj)
    return descendants


def delete_object(object_names):
    """Delete one or more objects from the scene.

    Recursively deletes all descendants bottom-up to prevent orphaned
    children flying to wild coordinates.

    Args:
        object_names: List of object names to delete

    Returns:
        dict with deleted_count and deleted_names
    """
    try:
        if isinstance(object_names, str):
            object_names = [object_names]

        deleted = []
        not_found = []
        already_deleted = set()
        for name in object_names:
            obj = bpy.data.objects.get(name)
            if not obj:
                if name not in already_deleted:
                    not_found.append(name)
                continue
            # Collect all descendants bottom-up, then delete in that order
            to_delete = _collect_all_descendants(obj)
            for d in to_delete:
                if d.name not in already_deleted:
                    dname = d.name
                    bpy.data.objects.remove(d, do_unlink=True)
                    deleted.append(dname)
                    already_deleted.add(dname)

        result = {
            "success": True,
            "deleted_count": len(deleted),
            "deleted_names": deleted,
        }
        if not_found:
            result["not_found"] = not_found
        return result
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to delete objects: {str(e)}"}
