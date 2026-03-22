import bpy
import requests
import re
import base64
import tempfile
import os
import threading
import uuid

# In-flight generation jobs (background threads)
_trellis2_jobs = {}


def get_trellis2_status():
    """Get the current status of Trellis2 integration."""
    enabled = bpy.context.scene.blenderweave_use_trellis2
    if enabled:
        api_url = bpy.context.scene.blenderweave_trellis2_api_url
        if not api_url:
            return {
                "enabled": False,
                "message": """Trellis2 integration is enabled but API URL is not set. To configure:
                    1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                    2. Set the Trellis2 API URL
                    3. Restart the MCP connection"""
            }
        return {"enabled": True, "message": "Trellis2 integration is enabled and ready to use."}
    return {
        "enabled": False,
        "message": """Trellis2 integration is currently disabled. To enable it:
                    1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                    2. Check the 'Use Trellis2 3D model generation' checkbox
                    3. Restart the MCP connection"""
    }


def create_trellis2_job(image=None, **kwargs):
    """Start a Trellis2 generation in a background thread.

    Returns immediately with a job_id. Use poll_trellis2_job to check status.
    On completion, the GLB is auto-imported into Blender.
    """
    try:
        base_url = bpy.context.scene.blenderweave_trellis2_api_url.rstrip('/')
        if not base_url:
            return {"error": "API URL is not given"}
        if not image:
            return {"error": "Image is required"}

        seed = kwargs.get('seed', bpy.context.scene.blenderweave_trellis2_seed)
        steps = kwargs.get('steps', None)
        if steps is None:
            steps = bpy.context.scene.blenderweave_trellis2_steps
        texture_size = kwargs.get('texture_size', bpy.context.scene.blenderweave_trellis2_texture_size)
        guidance_strength = kwargs.get('guidance_strength', bpy.context.scene.blenderweave_trellis2_guidance_strength)
        texture_guidance = kwargs.get('texture_guidance', bpy.context.scene.blenderweave_trellis2_texture_guidance)
        pipeline_type = kwargs.get('pipeline_type', bpy.context.scene.blenderweave_trellis2_pipeline_type)

        # Encode image upfront (fast)
        if re.match(r'^https?://', image, re.IGNORECASE) is not None:
            try:
                resImg = requests.get(image, timeout=30)
                resImg.raise_for_status()
                image_base64 = base64.b64encode(resImg.content).decode("ascii")
            except Exception as e:
                return {"error": f"Failed to download or encode image: {str(e)}"}
        else:
            try:
                with open(image, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode("ascii")
            except Exception as e:
                return {"error": f"Image encoding failed: {str(e)}"}

        data = {
            "image": image_base64,
            "seed": seed,
            "pipeline_type": pipeline_type,
            "steps": steps,
            "texture_size": texture_size,
            "guidance_strength": guidance_strength,
            "texture_guidance": texture_guidance,
        }

        job_id = uuid.uuid4().hex[:8]
        _trellis2_jobs[job_id] = {"status": "RUNNING", "message": "Generation started..."}

        def _run_generation():
            try:
                response = requests.post(f"{base_url}/generate", json=data, timeout=3600)
                if response.status_code != 200:
                    _trellis2_jobs[job_id] = {"status": "FAILED", "error": f"HTTP {response.status_code}: {response.text[:200]}"}
                    return

                result_json = response.json()
                glb_b64 = result_json.get("glb")
                if not glb_b64:
                    _trellis2_jobs[job_id] = {"status": "FAILED", "error": "No GLB data in response"}
                    return

                glb_data = base64.b64decode(glb_b64)
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
                temp_file.write(glb_data)
                temp_file_name = temp_file.name
                temp_file.close()

                def import_handler():
                    bpy.ops.import_scene.gltf(filepath=temp_file_name)
                    os.unlink(temp_file_name)
                    _trellis2_jobs[job_id] = {"status": "DONE", "message": "Model imported successfully"}
                    return None

                bpy.app.timers.register(import_handler)
                _trellis2_jobs[job_id] = {"status": "IMPORTING", "message": "Generation complete, importing GLB..."}
            except Exception as e:
                _trellis2_jobs[job_id] = {"status": "FAILED", "error": str(e)}

        thread = threading.Thread(target=_run_generation, daemon=True)
        thread.start()

        return {"status": "STARTED", "job_id": job_id, "message": "Trellis2 generation started in background. Poll with poll_trellis2_job."}
    except Exception as e:
        print(f"Trellis2 error: {e}")
        return {"error": str(e)}


def poll_trellis2_job(job_id=None, **kwargs):
    """Check the status of a Trellis2 generation job."""
    if not job_id:
        # Return all jobs
        return {"jobs": {k: v for k, v in _trellis2_jobs.items()}}
    job = _trellis2_jobs.get(job_id)
    if not job:
        return {"error": f"Unknown job_id: {job_id}"}
    return job
