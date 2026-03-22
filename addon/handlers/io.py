import bpy
import os
import traceback


FORMAT_MAP = {
    ".glb": "GLB", ".gltf": "GLB",
    ".fbx": "FBX",
    ".obj": "OBJ",
    ".usd": "USD", ".usdc": "USD", ".usda": "USD",
    ".stl": "STL",
    ".abc": "ABC",
    ".ply": "PLY",
    ".dae": "DAE",
}


def import_model(filepath, format="auto", scale=1.0):
    """Import a 3D model file into Blender.

    Args:
        filepath: Path to the model file
        format: File format (auto-detect from extension, or: GLB, FBX, OBJ, USD, STL, ABC, PLY, DAE)
        scale: Import scale factor

    Returns:
        dict with success status and imported object names
    """
    try:
        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}

        if format == "auto":
            ext = os.path.splitext(filepath)[1].lower()
            format = FORMAT_MAP.get(ext)
            if not format:
                return {"error": f"Cannot auto-detect format for extension: {ext}"}

        existing_objects = set(obj.name for obj in bpy.data.objects)

        if format == "GLB":
            bpy.ops.import_scene.gltf(filepath=filepath)
        elif format == "FBX":
            bpy.ops.import_scene.fbx(filepath=filepath, global_scale=scale)
        elif format == "OBJ":
            bpy.ops.wm.obj_import(filepath=filepath, global_scale=scale)
        elif format == "USD":
            bpy.ops.wm.usd_import(filepath=filepath, scale=scale)
        elif format == "STL":
            bpy.ops.wm.stl_import(filepath=filepath, global_scale=scale)
        elif format == "ABC":
            bpy.ops.wm.alembic_import(filepath=filepath, scale=scale)
        elif format == "PLY":
            bpy.ops.wm.ply_import(filepath=filepath, global_scale=scale)
        elif format == "DAE":
            bpy.ops.wm.collada_import(filepath=filepath)
        else:
            return {"error": f"Unsupported format: {format}"}

        # Apply scale for formats that don't support it natively
        if format in ("GLB", "DAE") and scale != 1.0:
            for obj in bpy.context.selected_objects:
                obj.scale = (obj.scale.x * scale, obj.scale.y * scale, obj.scale.z * scale)

        new_objects = [obj.name for obj in bpy.data.objects if obj.name not in existing_objects]

        return {
            "success": True,
            "message": f"Imported {filepath}",
            "format": format,
            "imported_objects": new_objects,
            "object_count": len(new_objects),
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Import failed: {str(e)}"}


def export_model(filepath, format="GLB", selected_only=False, apply_modifiers=True):
    """Export scene or selected objects to a file.

    Args:
        filepath: Output file path
        format: Export format (GLB, FBX, OBJ, USD, STL, ABC, PLY, DAE)
        selected_only: Export only selected objects
        apply_modifiers: Apply modifiers before export

    Returns:
        dict with success status
    """
    try:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        if format == "GLB":
            try:
                bpy.ops.export_scene.gltf(
                    filepath=filepath,
                    export_format='GLB',
                    use_selection=selected_only,
                    export_apply=apply_modifiers,
                )
            except Exception:
                # Blender 5.0 glTF can crash on NLA strips with null slots;
                # retry without animations
                bpy.ops.export_scene.gltf(
                    filepath=filepath,
                    export_format='GLB',
                    use_selection=selected_only,
                    export_apply=apply_modifiers,
                    export_animations=False,
                )
        elif format == "FBX":
            bpy.ops.export_scene.fbx(
                filepath=filepath,
                use_selection=selected_only,
                apply_unit_scale=True,
                use_mesh_modifiers=apply_modifiers,
            )
        elif format == "OBJ":
            bpy.ops.wm.obj_export(
                filepath=filepath,
                export_selected_objects=selected_only,
                apply_modifiers=apply_modifiers,
            )
        elif format == "USD":
            bpy.ops.wm.usd_export(
                filepath=filepath,
                selected_objects_only=selected_only,
            )
        elif format == "STL":
            bpy.ops.wm.stl_export(
                filepath=filepath,
                export_selected_objects=selected_only,
                apply_modifiers=apply_modifiers,
            )
        elif format == "ABC":
            bpy.ops.wm.alembic_export(
                filepath=filepath,
                selected=selected_only,
            )
        elif format == "PLY":
            bpy.ops.wm.ply_export(
                filepath=filepath,
                export_selected_objects=selected_only,
                apply_modifiers=apply_modifiers,
            )
        elif format == "DAE":
            bpy.ops.wm.collada_export(
                filepath=filepath,
                selected=selected_only,
                apply_modifiers=apply_modifiers,
            )
        else:
            return {"error": f"Unsupported format: {format}"}

        return {
            "success": True,
            "message": f"Exported to {filepath}",
            "filepath": filepath,
            "format": format,
            "selected_only": selected_only,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Export failed: {str(e)}"}
