import bpy
import math
import mathutils
import os
import traceback

from ._compat import normalize_engine, is_eevee
from ._utils import select_only

# Async render job tracking
_render_jobs = {}
_render_restore = {}


def set_camera(camera_name=None, focal_length=None, sensor_width=None,
               dof_enabled=None, aperture_fstop=None,
               focus_object=None, focus_distance=None,
               look_at=None, path_object=None, follow_path=None):
    """Configure camera settings.

    Args:
        camera_name: Name of camera object (default: active camera)
        focal_length: Lens focal length in mm
        sensor_width: Sensor width in mm
        dof_enabled: Enable/disable depth of field
        aperture_fstop: F-stop value for DOF
        focus_object: Name of object to focus on
        focus_distance: Manual focus distance in meters
        look_at: Name of object or [x,y,z] point to look at (adds TRACK_TO constraint)
        path_object: Name of curve object for camera path
        follow_path: If True, add Follow Path constraint to path_object

    Returns:
        dict with success status and camera info
    """
    try:
        if camera_name:
            cam_obj = bpy.data.objects.get(camera_name)
            if not cam_obj or cam_obj.type != 'CAMERA':
                return {"error": f"Camera not found: {camera_name}"}
        else:
            cam_obj = bpy.context.scene.camera
            if not cam_obj:
                return {"error": "No active camera in scene"}

        cam = cam_obj.data

        if focal_length is not None:
            cam.lens = focal_length
        if sensor_width is not None:
            cam.sensor_width = sensor_width
        if dof_enabled is not None:
            cam.dof.use_dof = dof_enabled
        if aperture_fstop is not None:
            cam.dof.aperture_fstop = aperture_fstop
        if focus_object is not None:
            focus_obj = bpy.data.objects.get(focus_object)
            if focus_obj:
                cam.dof.focus_object = focus_obj
            else:
                return {"error": f"Focus object not found: {focus_object}"}
        if focus_distance is not None:
            cam.dof.focus_distance = focus_distance

        # Look at target
        if look_at is not None:
            _camera_look_at(cam_obj, look_at)

        # Follow path
        if follow_path and path_object:
            _camera_follow_path(cam_obj, path_object)

        return {
            "success": True,
            "message": f"Camera '{cam_obj.name}' updated",
            "camera": {
                "name": cam_obj.name,
                "focal_length": cam.lens,
                "sensor_width": cam.sensor_width,
                "dof_enabled": cam.dof.use_dof,
                "aperture_fstop": cam.dof.aperture_fstop,
                "focus_object": cam.dof.focus_object.name if cam.dof.focus_object else None,
                "focus_distance": cam.dof.focus_distance,
                "location": [cam_obj.location.x, cam_obj.location.y, cam_obj.location.z],
                "rotation": [cam_obj.rotation_euler.x, cam_obj.rotation_euler.y, cam_obj.rotation_euler.z],
            }
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to set camera: {str(e)}"}


def _camera_look_at(cam_obj, target):
    """Point camera at a target object or point."""
    if isinstance(target, str):
        target_obj = bpy.data.objects.get(target)
        if not target_obj:
            raise ValueError(f"Look-at target not found: {target}")
        target_loc = target_obj.location
    elif isinstance(target, (list, tuple)) and len(target) == 3:
        target_loc = mathutils.Vector(target)
    else:
        raise ValueError("look_at must be an object name or [x,y,z] coordinates")

    # Remove existing track-to constraints
    for con in list(cam_obj.constraints):
        if con.type == 'TRACK_TO':
            cam_obj.constraints.remove(con)

    # Calculate direction and set rotation
    direction = target_loc - cam_obj.location
    rot = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot.to_euler()


def _camera_follow_path(cam_obj, path_name):
    """Add Follow Path constraint to camera."""
    path_obj = bpy.data.objects.get(path_name)
    if not path_obj:
        raise ValueError(f"Path object not found: {path_name}")
    if path_obj.type != 'CURVE':
        raise ValueError(f"Object '{path_name}' is not a curve (type={path_obj.type})")

    # Remove existing follow path constraints
    for con in list(cam_obj.constraints):
        if con.type == 'FOLLOW_PATH':
            cam_obj.constraints.remove(con)

    con = cam_obj.constraints.new('FOLLOW_PATH')
    con.target = path_obj
    con.use_curve_follow = True

    # Animate the offset
    con.offset_factor = 0.0
    path_obj.data.use_path = True


def render_scene(output_path, engine="CYCLES", samples=128,
                 resolution_x=1920, resolution_y=1080,
                 format="PNG", denoise=True,
                 animation=False, frame_start=None, frame_end=None, frame_step=1):
    """Render the scene to a file, or render an animation frame range.

    Args:
        output_path: Path to save rendered image(s). For animation, use a
                     directory or path with frame placeholder (e.g. /tmp/frames/)
        engine: Render engine (CYCLES, BLENDER_EEVEE, BLENDER_WORKBENCH)
               (BLENDER_EEVEE_NEXT also accepted for backwards compatibility)
        samples: Number of render samples
        resolution_x: Horizontal resolution
        resolution_y: Vertical resolution
        format: Output format (PNG, JPEG, EXR, etc.)
        denoise: Enable denoising (Cycles only)
        animation: If True, render frame range instead of single still
        frame_start: First frame to render (default: scene frame_start)
        frame_end: Last frame to render (default: scene frame_end)
        frame_step: Frame step for animation (default: 1)

    Returns:
        dict with success status and render info
    """
    try:
        scene = bpy.context.scene
        render = scene.render

        # Auto-set active camera if none set
        if not scene.camera:
            for obj in scene.objects:
                if obj.type == 'CAMERA':
                    scene.camera = obj
                    break
            if not scene.camera:
                return {"error": "No camera in scene. Create one with create_object(type='CAMERA')"}

        # Store original settings to restore after render
        orig_engine = render.engine
        orig_res_x = render.resolution_x
        orig_res_y = render.resolution_y
        orig_format = render.image_settings.file_format
        orig_filepath = render.filepath
        orig_frame_start = scene.frame_start
        orig_frame_end = scene.frame_end
        orig_frame_step = scene.frame_step

        # Apply render settings
        render.engine = normalize_engine(engine)
        render.resolution_x = resolution_x
        render.resolution_y = resolution_y
        render.image_settings.file_format = format
        render.filepath = output_path

        if engine == "CYCLES":
            scene.cycles.samples = samples
            scene.cycles.use_denoising = denoise
        elif is_eevee(engine):
            if hasattr(scene.eevee, 'taa_render_samples'):
                scene.eevee.taa_render_samples = samples

        if animation:
            # Set frame range
            if frame_start is not None:
                scene.frame_start = frame_start
            if frame_end is not None:
                scene.frame_end = frame_end
            scene.frame_step = frame_step

            # Ensure output path ends with separator for frame numbering
            if not output_path.endswith(('/', os.sep)) and '#' not in output_path:
                render.filepath = output_path.rstrip('/') + '/'

            # Async render — return immediately, poll with poll_render_job
            import uuid
            job_id = uuid.uuid4().hex[:8]
            total_frames = (scene.frame_end - scene.frame_start) // scene.frame_step + 1
            _render_jobs[job_id] = {
                "status": "RENDERING",
                "output_path": render.filepath,
                "frame_start": scene.frame_start,
                "frame_end": scene.frame_end,
                "frame_step": scene.frame_step,
                "total_frames": total_frames,
                "format": format,
                "engine": render.engine,
                "resolution": [resolution_x, resolution_y],
            }

            # Store settings to restore after render completes
            _render_restore = {
                "engine": orig_engine, "res_x": orig_res_x, "res_y": orig_res_y,
                "format": orig_format, "filepath": orig_filepath,
                "frame_start": orig_frame_start, "frame_end": orig_frame_end,
                "frame_step": orig_frame_step,
            }

            def _do_render():
                try:
                    bpy.ops.render.render(animation=True)
                    _render_jobs[job_id]["status"] = "DONE"
                    _render_jobs[job_id]["message"] = f"Animation rendered ({_render_jobs[job_id]['total_frames']} frames)"
                except Exception as e:
                    _render_jobs[job_id]["status"] = "FAILED"
                    _render_jobs[job_id]["error"] = str(e)
                finally:
                    # Restore settings
                    r = _render_restore
                    render.engine = r["engine"]
                    render.resolution_x = r["res_x"]
                    render.resolution_y = r["res_y"]
                    render.image_settings.file_format = r["format"]
                    render.filepath = r["filepath"]
                    scene.frame_start = r["frame_start"]
                    scene.frame_end = r["frame_end"]
                    scene.frame_step = r["frame_step"]
                return None

            bpy.app.timers.register(_do_render, first_interval=0.1)

            return {
                "status": "STARTED",
                "job_id": job_id,
                "message": f"Animation render started ({total_frames} frames). Poll with poll_render_job.",
                "total_frames": total_frames,
            }
        else:
            bpy.ops.render.render(write_still=True)

            result = {
                "success": True,
                "message": f"Scene rendered to {output_path}",
                "output_path": output_path,
                "engine": render.engine,
                "resolution": [resolution_x, resolution_y],
                "samples": samples,
                "format": format,
            }

        # Restore settings
        render.engine = orig_engine
        render.resolution_x = orig_res_x
        render.resolution_y = orig_res_y
        render.image_settings.file_format = orig_format
        render.filepath = orig_filepath
        scene.frame_start = orig_frame_start
        scene.frame_end = orig_frame_end
        scene.frame_step = orig_frame_step

        return result
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Render failed: {str(e)}"}


def poll_render_job(job_id=None):
    """Poll the status of an async animation render job.

    Returns status: RENDERING, DONE, or FAILED.
    When RENDERING, includes progress based on output files written.
    """
    if job_id is None:
        return {"jobs": {k: v.get("status") for k, v in _render_jobs.items()}}

    job = _render_jobs.get(job_id)
    if not job:
        return {"error": f"No render job with ID {job_id}"}

    result = {"status": job["status"]}

    if job["status"] == "RENDERING":
        # Count frames written to disk for progress
        out_path = job.get("output_path", "")
        if out_path:
            import glob
            pattern = os.path.join(out_path, "*.png") if out_path.endswith("/") else out_path + "*.png"
            written = len(glob.glob(pattern))
            total = job.get("total_frames", 1)
            result["frames_done"] = written
            result["total_frames"] = total
            result["progress"] = f"{written}/{total}"
    elif job["status"] == "DONE":
        result["message"] = job.get("message", "Render complete")
        result["output_path"] = job.get("output_path")
        result["total_frames"] = job.get("total_frames")
    elif job["status"] == "FAILED":
        result["error"] = job.get("error", "Unknown error")

    return result


def camera_walkthrough(camera_name=None, waypoints=None, interpolation="BEZIER",
                       frame_start=1, frames_per_segment=60):
    """Create a camera walkthrough animation from waypoints.

    Each waypoint defines a camera position and look-at target. The camera
    is keyframed at evenly-spaced intervals with smooth interpolation.

    Args:
        camera_name: Name of camera (default: active camera)
        waypoints: List of dicts, each with:
            - location: [x, y, z] camera position
            - look_at: [x, y, z] point to look at (or object name)
            - focal_length: Optional lens override for this waypoint
        interpolation: Keyframe interpolation (BEZIER, LINEAR, CONSTANT)
        frame_start: First frame number (default 1)
        frames_per_segment: Frames between waypoints (default 60)

    Returns:
        dict with success status, frame range, waypoint count
    """
    try:
        if not waypoints or len(waypoints) < 2:
            return {"error": "At least 2 waypoints required"}

        if camera_name:
            cam_obj = bpy.data.objects.get(camera_name)
            if not cam_obj or cam_obj.type != 'CAMERA':
                return {"error": f"Camera not found: {camera_name}"}
        else:
            cam_obj = bpy.context.scene.camera
            if not cam_obj:
                return {"error": "No active camera in scene"}

        cam = cam_obj.data
        scene = bpy.context.scene

        # Clear existing animation on camera
        if cam_obj.animation_data and cam_obj.animation_data.action:
            bpy.data.actions.remove(cam_obj.animation_data.action)

        for i, wp in enumerate(waypoints):
            frame = frame_start + i * frames_per_segment

            # Set location
            loc = wp.get("location")
            if loc:
                cam_obj.location = tuple(loc)

            # Set look-at rotation
            look_at = wp.get("look_at")
            if look_at:
                if isinstance(look_at, str):
                    target_obj = bpy.data.objects.get(look_at)
                    if target_obj:
                        look_at = list(target_obj.location)
                    else:
                        return {"error": f"Look-at target not found: {look_at}"}
                target = mathutils.Vector(look_at)
                direction = target - cam_obj.location
                rot = direction.to_track_quat('-Z', 'Y')
                cam_obj.rotation_euler = rot.to_euler()

            # Set focal length if specified
            fl = wp.get("focal_length")
            if fl is not None:
                cam.lens = fl

            # Insert keyframes
            scene.frame_set(frame)
            cam_obj.keyframe_insert(data_path="location", frame=frame)
            cam_obj.keyframe_insert(data_path="rotation_euler", frame=frame)
            if fl is not None:
                cam.keyframe_insert(data_path="lens", frame=frame)

        # Set interpolation on all keyframes
        if cam_obj.animation_data and cam_obj.animation_data.action:
            action = cam_obj.animation_data.action
            fcurves = action.fcurves if hasattr(action, 'fcurves') else []
            try:
                # Blender 5 fallback
                if not fcurves:
                    for layer in action.layers:
                        for strip in layer.strips:
                            fcurves = strip.channelbags[0].fcurves
                            break
                        break
            except (AttributeError, IndexError):
                pass

            for fc in fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = interpolation

        frame_end = frame_start + (len(waypoints) - 1) * frames_per_segment
        scene.frame_start = frame_start
        scene.frame_end = frame_end

        return {
            "success": True,
            "message": f"Camera walkthrough: {len(waypoints)} waypoints, frames {frame_start}-{frame_end}",
            "camera": cam_obj.name,
            "waypoint_count": len(waypoints),
            "frame_range": [frame_start, frame_end],
            "frames_per_segment": frames_per_segment,
            "interpolation": interpolation,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Camera walkthrough failed: {str(e)}"}
