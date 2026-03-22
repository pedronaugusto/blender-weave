"""File operations and undo/redo for BlenderWeave."""
import bpy
import traceback


def save_file(filepath=None):
    """Save the current Blender file.

    Args:
        filepath: Optional path. If None, saves to current filepath.
                  If current file is untitled, filepath is required.

    Returns:
        dict with success status and filepath
    """
    try:
        if filepath:
            bpy.ops.wm.save_as_mainfile(filepath=filepath)
            return {
                "success": True,
                "message": f"File saved to {filepath}",
                "filepath": filepath,
            }
        else:
            current = bpy.data.filepath
            if not current:
                return {"error": "No filepath set. Provide a filepath for untitled files."}
            bpy.ops.wm.save_mainfile()
            return {
                "success": True,
                "message": f"File saved to {current}",
                "filepath": current,
            }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Save failed: {str(e)}"}


def open_file(filepath):
    """Open a Blender file.

    Args:
        filepath: Path to the .blend file to open

    Returns:
        dict with success status
    """
    try:
        if not filepath:
            return {"error": "filepath is required"}
        bpy.ops.wm.open_mainfile(filepath=filepath)
        return {
            "success": True,
            "message": f"Opened {filepath}",
            "filepath": filepath,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Open failed: {str(e)}"}


def undo():
    """Undo the last operation.

    Returns:
        dict with success status
    """
    try:
        bpy.ops.ed.undo()
        return {
            "success": True,
            "message": "Undo performed",
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Undo failed: {str(e)}"}


def redo():
    """Redo the last undone operation.

    Returns:
        dict with success status
    """
    try:
        bpy.ops.ed.redo()
        return {
            "success": True,
            "message": "Redo performed",
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Redo failed: {str(e)}"}


def undo_history():
    """Get the undo history stack.

    Returns:
        dict with undo steps
    """
    try:
        # Blender doesn't expose undo history directly via Python API
        # We can report the current undo step count
        return {
            "success": True,
            "message": "Undo history retrieved",
            "note": "Blender does not expose detailed undo history via Python API. Use undo() and redo() to navigate.",
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to get undo history: {str(e)}"}


def set_frame(frame=None, start=None, end=None):
    """Set current frame or frame range.

    Args:
        frame: Frame number to jump to
        start: Start frame of range
        end: End frame of range

    Returns:
        dict with frame info
    """
    try:
        scene = bpy.context.scene

        if frame is not None:
            scene.frame_set(frame)
        if start is not None:
            scene.frame_start = start
        if end is not None:
            scene.frame_end = end

        return {
            "success": True,
            "current_frame": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Frame operation failed: {str(e)}"}
