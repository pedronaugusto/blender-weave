import bpy
import os
import traceback


def bake_textures(high_poly, low_poly, bake_types, output_dir,
                  resolution=1024, cage_extrusion=0.1, uv_layer=None):
    """Bake textures from high-poly to low-poly mesh.

    Args:
        high_poly: Name of the high-poly source object
        low_poly: Name of the low-poly target object
        bake_types: List of bake types — DIFFUSE, NORMAL, AO, ROUGHNESS, COMBINED, EMIT
        output_dir: Directory to save baked texture images
        resolution: Texture resolution in pixels (default 1024)
        cage_extrusion: Ray cast distance for projection (default 0.1)
        uv_layer: UV layer name on low_poly to bake into (uses active if None)

    Returns:
        dict mapping bake_type to filepath for each baked texture
    """
    try:
        hi = bpy.data.objects.get(high_poly)
        if not hi:
            return {"error": f"High-poly object not found: {high_poly}"}
        lo = bpy.data.objects.get(low_poly)
        if not lo:
            return {"error": f"Low-poly object not found: {low_poly}"}
        if lo.type != 'MESH':
            return {"error": f"Low-poly object '{low_poly}' is not a mesh"}

        os.makedirs(output_dir, exist_ok=True)

        # Set UV layer if specified
        if uv_layer:
            uv = lo.data.uv_layers.get(uv_layer)
            if not uv:
                return {"error": f"UV layer '{uv_layer}' not found on '{low_poly}'"}
            lo.data.uv_layers.active = uv

        # Remember and switch to Cycles
        original_engine = bpy.context.scene.render.engine
        bpy.context.scene.render.engine = 'CYCLES'

        # Ensure low-poly has a material with an image texture node
        if not lo.data.materials:
            mat = bpy.data.materials.new(name=f"{low_poly}_BakeMat")
            mat.use_nodes = True
            lo.data.materials.append(mat)

        results = {}

        for bake_type in bake_types:
            bake_type = bake_type.upper()
            image_name = f"{low_poly}_{bake_type}"
            filepath = os.path.join(output_dir, f"{image_name}.png")

            # Create image
            if image_name in bpy.data.images:
                img = bpy.data.images[image_name]
                bpy.data.images.remove(img)
            img = bpy.data.images.new(
                image_name, width=resolution, height=resolution,
                alpha=(bake_type != "NORMAL"),
            )
            img.filepath_raw = filepath
            img.file_format = 'PNG'

            # Set up image texture node in each material on low-poly
            tex_nodes = []
            for mat_slot in lo.material_slots:
                mat = mat_slot.material
                if not mat or not mat.use_nodes:
                    continue
                tree = mat.node_tree
                tex_node = tree.nodes.new('ShaderNodeTexImage')
                tex_node.image = img
                tex_node.name = f"_bake_temp_{bake_type}"
                tree.nodes.active = tex_node
                tex_nodes.append((tree, tex_node))

            # Select objects for baking
            bpy.ops.object.select_all(action='DESELECT')
            hi.select_set(True)
            lo.select_set(True)
            bpy.context.view_layer.objects.active = lo

            # Bake
            bpy.context.scene.render.bake.use_selected_to_active = True
            bpy.context.scene.render.bake.cage_extrusion = cage_extrusion

            bake_map = {
                "DIFFUSE": "DIFFUSE",
                "NORMAL": "NORMAL",
                "AO": "AO",
                "ROUGHNESS": "ROUGHNESS",
                "COMBINED": "COMBINED",
                "EMIT": "EMIT",
            }

            bl_bake_type = bake_map.get(bake_type)
            if not bl_bake_type:
                results[bake_type] = {"error": f"Unknown bake type: {bake_type}"}
                continue

            # For DIFFUSE, disable direct/indirect to get only color
            if bake_type == "DIFFUSE":
                bpy.context.scene.render.bake.use_pass_direct = False
                bpy.context.scene.render.bake.use_pass_indirect = False
                bpy.context.scene.render.bake.use_pass_color = True

            bpy.ops.object.bake(type=bl_bake_type)

            # Save
            img.save_render(filepath)
            results[bake_type] = filepath

            # Clean up temp nodes
            for tree, tex_node in tex_nodes:
                tree.nodes.remove(tex_node)

        # Restore engine
        bpy.context.scene.render.engine = original_engine

        return {
            "success": True,
            "message": f"Baked {len(results)} texture(s) from '{high_poly}' to '{low_poly}'",
            "baked": results,
            "resolution": resolution,
        }
    except Exception as e:
        traceback.print_exc()
        # Try to restore engine
        try:
            bpy.context.scene.render.engine = original_engine
        except Exception:
            pass
        return {"error": f"Bake failed: {str(e)}"}
