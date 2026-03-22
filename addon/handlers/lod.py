import bpy
import traceback


def generate_lod_chain(object_name, ratios=None, suffix_pattern="_LOD{i}",
                       collection_name=None):
    """Generate LOD (Level of Detail) chain by decimating copies of an object.

    Args:
        object_name: Name of the source object
        ratios: List of decimation ratios (default [1.0, 0.5, 0.25, 0.1])
        suffix_pattern: Naming pattern with {i} for LOD index (default "_LOD{i}")
        collection_name: Optional collection to place LOD objects into

    Returns:
        list of {name, ratio, poly_count} for each LOD level
    """
    try:
        if ratios is None:
            ratios = [1.0, 0.5, 0.25, 0.1]

        obj = bpy.data.objects.get(object_name)
        if not obj or obj.type != 'MESH':
            return {"error": f"Mesh object not found: {object_name}"}

        # Create collection if requested
        target_col = None
        if collection_name:
            target_col = bpy.data.collections.get(collection_name)
            if not target_col:
                target_col = bpy.data.collections.new(collection_name)
                bpy.context.scene.collection.children.link(target_col)

        original_poly_count = len(obj.data.polygons)
        levels = []

        for i, ratio in enumerate(ratios):
            suffix = suffix_pattern.replace("{i}", str(i))
            lod_name = f"{object_name}{suffix}"

            # Duplicate
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = lod_name

            if target_col:
                target_col.objects.link(new_obj)
            else:
                for col in obj.users_collection:
                    col.objects.link(new_obj)
                    break
                else:
                    bpy.context.scene.collection.objects.link(new_obj)

            # Apply decimate if ratio < 1
            if ratio < 1.0:
                mod = new_obj.modifiers.new(name="Decimate_LOD", type='DECIMATE')
                mod.ratio = ratio

                bpy.ops.object.select_all(action='DESELECT')
                new_obj.select_set(True)
                bpy.context.view_layer.objects.active = new_obj
                bpy.ops.object.modifier_apply(modifier=mod.name)

            poly_count = len(new_obj.data.polygons)
            levels.append({
                "name": new_obj.name,
                "ratio": ratio,
                "poly_count": poly_count,
            })

        return {
            "success": True,
            "message": f"Generated {len(levels)} LOD levels for '{object_name}'",
            "original_poly_count": original_poly_count,
            "levels": levels,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"LOD generation failed: {str(e)}"}


def generate_collision_mesh(object_name, method="CONVEX_HULL",
                            voxel_size=0.1, name_suffix="_collision"):
    """Generate a simplified collision mesh from an object.

    Args:
        object_name: Name of the source object
        method: Collision mesh method — CONVEX_HULL, BOX, VOXEL
        voxel_size: Voxel size for VOXEL method (default 0.1)
        name_suffix: Suffix for the collision mesh name (default "_collision")

    Returns:
        dict with name, vertex_count, method
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj or obj.type != 'MESH':
            return {"error": f"Mesh object not found: {object_name}"}

        col_name = f"{object_name}{name_suffix}"

        if method == "CONVEX_HULL":
            # Duplicate and apply convex hull
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = col_name
            for col in obj.users_collection:
                col.objects.link(new_obj)
                break
            else:
                bpy.context.scene.collection.objects.link(new_obj)

            # Enter edit mode and do convex hull
            bpy.ops.object.select_all(action='DESELECT')
            new_obj.select_set(True)
            bpy.context.view_layer.objects.active = new_obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.convex_hull()
            bpy.ops.object.mode_set(mode='OBJECT')

        elif method == "BOX":
            import mathutils
            local_corners = [mathutils.Vector(c) for c in obj.bound_box]
            min_c = mathutils.Vector((
                min(c.x for c in local_corners),
                min(c.y for c in local_corners),
                min(c.z for c in local_corners),
            ))
            max_c = mathutils.Vector((
                max(c.x for c in local_corners),
                max(c.y for c in local_corners),
                max(c.z for c in local_corners),
            ))
            center = (min_c + max_c) / 2
            dims = max_c - min_c

            bpy.ops.mesh.primitive_cube_add(
                size=1.0,
                location=obj.matrix_world @ center,
            )
            new_obj = bpy.context.active_object
            new_obj.name = col_name
            new_obj.scale = (dims.x, dims.y, dims.z)
            new_obj.rotation_euler = obj.rotation_euler.copy()

        elif method == "VOXEL":
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = col_name
            for col in obj.users_collection:
                col.objects.link(new_obj)
                break
            else:
                bpy.context.scene.collection.objects.link(new_obj)

            bpy.ops.object.select_all(action='DESELECT')
            new_obj.select_set(True)
            bpy.context.view_layer.objects.active = new_obj
            new_obj.data.remesh_voxel_size = voxel_size
            bpy.ops.object.voxel_remesh()

        else:
            return {"error": f"Unknown method: {method}. Use CONVEX_HULL, BOX, or VOXEL"}

        # Clear materials on collision mesh
        new_obj.data.materials.clear()

        # Set wireframe display
        new_obj.display_type = 'WIRE'

        vertex_count = len(new_obj.data.vertices)
        poly_count = len(new_obj.data.polygons)

        return {
            "success": True,
            "name": new_obj.name,
            "method": method,
            "vertex_count": vertex_count,
            "polygon_count": poly_count,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Collision mesh generation failed: {str(e)}"}
