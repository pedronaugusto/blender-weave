import bpy
import requests
import json
import re
import time
import hashlib
import hmac
import base64
import tempfile
import os
import os.path as osp
import zipfile
import traceback
import threading
import uuid
from datetime import datetime

from .scene import get_aabb

# In-flight local generation jobs (background threads)
_hunyuan_local_jobs = {}


def get_hunyuan3d_status():
    """Get the current status of Hunyuan3D integration."""
    enabled = bpy.context.scene.blenderweave_use_hunyuan3d
    hunyuan3d_mode = bpy.context.scene.blenderweave_hunyuan3d_mode
    if enabled:
        match hunyuan3d_mode:
            case "OFFICIAL_API":
                if not bpy.context.scene.blenderweave_hunyuan3d_secret_id or not bpy.context.scene.blenderweave_hunyuan3d_secret_key:
                    return {
                        "enabled": False,
                        "mode": hunyuan3d_mode,
                        "message": """Hunyuan3D integration is currently enabled, but SecretId or SecretKey is not given. To enable it:
                            1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                            2. Keep the 'Use Tencent Hunyuan 3D model generation' checkbox checked
                            3. Choose the right platform and fill in the SecretId and SecretKey
                            4. Restart the MCP connection"""
                    }
            case "LOCAL_API":
                if not bpy.context.scene.blenderweave_hunyuan3d_api_url:
                    return {
                        "enabled": False,
                        "mode": hunyuan3d_mode,
                        "message": """Hunyuan3D integration is currently enabled, but API URL is not given. To enable it:
                            1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                            2. Keep the 'Use Tencent Hunyuan 3D model generation' checkbox checked
                            3. Choose the right platform and fill in the API URL
                            4. Restart the MCP connection"""
                    }
            case _:
                return {"enabled": False, "message": "Hunyuan3D integration is enabled and mode is not supported."}
        return {"enabled": True, "mode": hunyuan3d_mode, "message": "Hunyuan3D integration is enabled and ready to use."}
    return {
        "enabled": False,
        "message": """Hunyuan3D integration is currently disabled. To enable it:
                    1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                    2. Check the 'Use Tencent Hunyuan 3D model generation' checkbox
                    3. Restart the MCP connection"""
    }


def create_hunyuan_job(*args, **kwargs):
    match bpy.context.scene.blenderweave_hunyuan3d_mode:
        case "OFFICIAL_API":
            return _create_hunyuan_job_main_site(*args, **kwargs)
        case "LOCAL_API":
            return _create_hunyuan_job_local_site(*args, **kwargs)
        case _:
            return {"error": "Unknown Hunyuan3D mode!"}


def _create_hunyuan_job_main_site(text_prompt=None, image=None):
    try:
        secret_id = bpy.context.scene.blenderweave_hunyuan3d_secret_id
        secret_key = bpy.context.scene.blenderweave_hunyuan3d_secret_key
        if not secret_id or not secret_key:
            return {"error": "SecretId or SecretKey is not given"}
        if not text_prompt and not image:
            return {"error": "Prompt or Image is required"}
        if text_prompt and image:
            return {"error": "Prompt and Image cannot be provided simultaneously"}

        service = "hunyuan"
        action = "SubmitHunyuanTo3DJob"
        version = "2023-09-01"
        region = "ap-guangzhou"
        headParams = {"Action": action, "Version": version, "Region": region}
        data = {"Num": 1}

        if text_prompt:
            if len(text_prompt) > 200:
                return {"error": "Prompt exceeds 200 characters limit"}
            data["Prompt"] = text_prompt

        if image:
            if re.match(r'^https?://', image, re.IGNORECASE) is not None:
                data["ImageUrl"] = image
            else:
                try:
                    with open(image, "rb") as f:
                        image_base64 = base64.b64encode(f.read()).decode("ascii")
                    data["ImageBase64"] = image_base64
                except Exception as e:
                    return {"error": f"Image encoding failed: {str(e)}"}

        headers, endpoint = _get_tencent_cloud_sign_headers("POST", "/", headParams, data, service, region, secret_id, secret_key)
        response = requests.post(endpoint, headers=headers, data=json.dumps(data))

        if response.status_code == 200:
            return response.json()
        return {"error": f"API request failed with status {response.status_code}: {response}"}
    except Exception as e:
        return {"error": str(e)}


def _create_hunyuan_job_local_site(text_prompt=None, image=None, **kwargs):
    """Start a Hunyuan3D local generation in a background thread.

    Returns immediately with a job_id. Use poll_hunyuan_job_status to check.
    On completion the GLB is auto-imported into Blender.
    """
    try:
        base_url = bpy.context.scene.blenderweave_hunyuan3d_api_url.rstrip('/')
        octree_resolution = bpy.context.scene.blenderweave_hunyuan3d_octree_resolution
        num_inference_steps = bpy.context.scene.blenderweave_hunyuan3d_num_inference_steps
        guidance_scale = bpy.context.scene.blenderweave_hunyuan3d_guidance_scale
        texture = bpy.context.scene.blenderweave_hunyuan3d_texture

        if not base_url:
            return {"error": "API URL is not given"}
        if not text_prompt and not image:
            return {"error": "Prompt or Image is required"}

        seed = kwargs.get('seed', bpy.context.scene.blenderweave_hunyuan3d_seed)
        data = {
            "octree_resolution": octree_resolution,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "texture": texture,
            "seed": seed,
        }
        texture_steps = kwargs.get('texture_steps', bpy.context.scene.blenderweave_hunyuan3d_texture_steps)
        data["texture_steps"] = texture_steps
        texture_guidance = kwargs.get('texture_guidance', bpy.context.scene.blenderweave_hunyuan3d_texture_guidance)
        data["texture_guidance"] = texture_guidance

        if text_prompt:
            data["text"] = text_prompt

        # Encode image upfront (fast)
        if image:
            if re.match(r'^https?://', image, re.IGNORECASE) is not None:
                try:
                    resImg = requests.get(image, timeout=30)
                    resImg.raise_for_status()
                    image_base64 = base64.b64encode(resImg.content).decode("ascii")
                    data["image"] = image_base64
                except Exception as e:
                    return {"error": f"Failed to download or encode image: {str(e)}"}
            else:
                try:
                    with open(image, "rb") as f:
                        image_base64 = base64.b64encode(f.read()).decode("ascii")
                    data["image"] = image_base64
                except Exception as e:
                    return {"error": f"Image encoding failed: {str(e)}"}

        job_id = f"hunyuan_{uuid.uuid4().hex[:8]}"
        _hunyuan_local_jobs[job_id] = {"status": "RUNNING", "message": "Generation started..."}

        def _run_generation():
            try:
                response = requests.post(f"{base_url}/generate", json=data, timeout=600)
                if response.status_code != 200:
                    _hunyuan_local_jobs[job_id] = {"status": "FAILED", "error": f"HTTP {response.status_code}: {response.text[:200]}"}
                    return

                glb_data = response.content
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
                temp_file.write(glb_data)
                temp_file_name = temp_file.name
                temp_file.close()

                def import_handler():
                    bpy.ops.import_scene.gltf(filepath=temp_file_name)
                    os.unlink(temp_file_name)
                    _hunyuan_local_jobs[job_id] = {"status": "DONE", "message": "Model imported successfully"}
                    return None

                bpy.app.timers.register(import_handler)
                _hunyuan_local_jobs[job_id] = {"status": "IMPORTING", "message": "Generation complete, importing GLB..."}
            except Exception as e:
                _hunyuan_local_jobs[job_id] = {"status": "FAILED", "error": str(e)}

        thread = threading.Thread(target=_run_generation, daemon=True)
        thread.start()

        return {"status": "STARTED", "job_id": job_id, "message": "Hunyuan3D generation started in background. Poll with poll_hunyuan_job_status."}
    except Exception as e:
        return {"error": str(e)}


def poll_hunyuan_job_status(job_id=None, **kwargs):
    """Poll job status — routes to local job dict or official API."""
    if not job_id:
        # Return all local jobs
        return {"jobs": {k: v for k, v in _hunyuan_local_jobs.items()}}
    # Check local jobs first
    if job_id in _hunyuan_local_jobs:
        return _hunyuan_local_jobs[job_id]
    # Fall through to official API
    return _poll_hunyuan_job_official(job_id)


def _poll_hunyuan_job_official(job_id):
    """Call the official Tencent API to get job status."""
    try:
        secret_id = bpy.context.scene.blenderweave_hunyuan3d_secret_id
        secret_key = bpy.context.scene.blenderweave_hunyuan3d_secret_key
        if not secret_id or not secret_key:
            return {"error": "SecretId or SecretKey is not given"}
        if not job_id:
            return {"error": "JobId is required"}

        service = "hunyuan"
        action = "QueryHunyuanTo3DJob"
        version = "2023-09-01"
        region = "ap-guangzhou"
        headParams = {"Action": action, "Version": version, "Region": region}
        clean_job_id = job_id.removeprefix("job_")
        data = {"JobId": clean_job_id}

        headers, endpoint = _get_tencent_cloud_sign_headers("POST", "/", headParams, data, service, region, secret_id, secret_key)
        response = requests.post(endpoint, headers=headers, data=json.dumps(data))

        if response.status_code == 200:
            return response.json()
        return {"error": f"API request failed with status {response.status_code}: {response}"}
    except Exception as e:
        return {"error": str(e)}


def import_generated_asset_hunyuan(name, zip_file_url):
    """Import a Hunyuan3D generated asset from a ZIP URL."""
    if not zip_file_url:
        return {"error": "Zip file not found"}
    if not re.match(r'^https?://', zip_file_url, re.IGNORECASE):
        return {"error": "Invalid URL format. Must start with http:// or https://"}

    temp_dir = tempfile.mkdtemp(prefix="tencent_obj_")
    zip_file_path = osp.join(temp_dir, "model.zip")
    obj_file_path = osp.join(temp_dir, "model.obj")

    try:
        zip_response = requests.get(zip_file_url, stream=True)
        zip_response.raise_for_status()
        with open(zip_file_path, "wb") as f:
            for chunk in zip_response.iter_content(chunk_size=8192):
                f.write(chunk)

        with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        for file in os.listdir(temp_dir):
            if file.endswith(".obj"):
                obj_file_path = osp.join(temp_dir, file)

        if not osp.exists(obj_file_path):
            return {"succeed": False, "error": "OBJ file not found after extraction"}

        bpy.ops.wm.obj_import(filepath=obj_file_path)

        imported_objs = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
        if not imported_objs:
            return {"succeed": False, "error": "No mesh objects imported"}

        obj = imported_objs[0]
        if name:
            obj.name = name

        result = {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
        }
        if obj.type == "MESH":
            result["world_bounding_box"] = get_aabb(obj)
        return {"succeed": True, **result}
    except Exception as e:
        return {"succeed": False, "error": str(e)}
    finally:
        try:
            if os.path.exists(zip_file_path):
                os.remove(zip_file_path)
            if os.path.exists(obj_file_path):
                os.remove(obj_file_path)
        except Exception as e:
            print(f"Failed to clean up temporary directory {temp_dir}: {e}")


def _get_tencent_cloud_sign_headers(method, path, headParams, data, service, region, secret_id, secret_key, host=None):
    """Generate the signature header required for Tencent Cloud API requests."""
    timestamp = int(time.time())
    date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    if not host:
        host = f"{service}.tencentcloudapi.com"
    endpoint = f"https://{host}"
    payload_str = json.dumps(data)

    canonical_uri = path
    canonical_querystring = ""
    ct = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{headParams.get('Action', '').lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    canonical_request = (method + "\n" + canonical_uri + "\n" + canonical_querystring + "\n" +
                        canonical_headers + "\n" + signed_headers + "\n" + hashed_request_payload)

    credential_scope = f"{date}/{service}/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = ("TC3-HMAC-SHA256" + "\n" + str(timestamp) + "\n" +
                     credential_scope + "\n" + hashed_canonical_request)

    def sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = sign(secret_date, service)
    secret_signing = sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = ("TC3-HMAC-SHA256 " +
                    "Credential=" + secret_id + "/" + credential_scope + ", " +
                    "SignedHeaders=" + signed_headers + ", " +
                    "Signature=" + signature)

    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": headParams.get("Action", ""),
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": headParams.get("Version", ""),
        "X-TC-Region": region
    }
    return headers, endpoint
