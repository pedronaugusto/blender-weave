import bpy
import mathutils
import requests
import json
import tempfile
import os
import traceback

from .scene import get_aabb

RODIN_FREE_TRIAL_KEY = "k9TcfFoEhNd9cCPP2guHAHHHkctZHIRhZDywZ1euGUXwihbYLpOjQhofby80NJez"


def get_hyper3d_status():
    """Get the current status of Hyper3D Rodin integration."""
    enabled = bpy.context.scene.blenderweave_use_hyper3d
    if enabled:
        if not bpy.context.scene.blenderweave_hyper3d_api_key:
            return {
                "enabled": False,
                "message": """Hyper3D Rodin integration is currently enabled, but API key is not given. To enable it:
                            1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                            2. Keep the 'Use Hyper3D Rodin 3D model generation' checkbox checked
                            3. Choose the right platform and fill in the API Key
                            4. Restart the MCP connection"""
            }
        mode = bpy.context.scene.blenderweave_hyper3d_mode
        message = f"Hyper3D Rodin integration is enabled and ready to use. Mode: {mode}. " + \
            f"Key type: {'private' if bpy.context.scene.blenderweave_hyper3d_api_key != RODIN_FREE_TRIAL_KEY else 'free_trial'}"
        return {"enabled": True, "message": message}
    else:
        return {
            "enabled": False,
            "message": """Hyper3D Rodin integration is currently disabled. To enable it:
                        1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                        2. Check the 'Use Hyper3D Rodin 3D model generation' checkbox
                        3. Restart the MCP connection"""
        }


def create_rodin_job(*args, **kwargs):
    match bpy.context.scene.blenderweave_hyper3d_mode:
        case "MAIN_SITE":
            return _create_rodin_job_main_site(*args, **kwargs)
        case "FAL_AI":
            return _create_rodin_job_fal_ai(*args, **kwargs)
        case _:
            return {"error": "Unknown Hyper3D Rodin mode!"}


def _create_rodin_job_main_site(text_prompt=None, images=None, bbox_condition=None):
    try:
        if images is None:
            images = []
        files = [
            *[("images", (f"{i:04d}{img_suffix}", img)) for i, (img_suffix, img) in enumerate(images)],
            ("tier", (None, "Sketch")),
            ("mesh_mode", (None, "Raw")),
        ]
        if text_prompt:
            files.append(("prompt", (None, text_prompt)))
        if bbox_condition:
            files.append(("bbox_condition", (None, json.dumps(bbox_condition))))
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/rodin",
            headers={"Authorization": f"Bearer {bpy.context.scene.blenderweave_hyper3d_api_key}"},
            files=files
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def _create_rodin_job_fal_ai(text_prompt=None, images=None, bbox_condition=None):
    try:
        req_data = {"tier": "Sketch"}
        if images:
            req_data["input_image_urls"] = images
        if text_prompt:
            req_data["prompt"] = text_prompt
        if bbox_condition:
            req_data["bbox_condition"] = bbox_condition
        response = requests.post(
            "https://queue.fal.run/fal-ai/hyper3d/rodin",
            headers={
                "Authorization": f"Key {bpy.context.scene.blenderweave_hyper3d_api_key}",
                "Content-Type": "application/json",
            },
            json=req_data
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def poll_rodin_job_status(*args, **kwargs):
    match bpy.context.scene.blenderweave_hyper3d_mode:
        case "MAIN_SITE":
            return _poll_rodin_job_status_main_site(*args, **kwargs)
        case "FAL_AI":
            return _poll_rodin_job_status_fal_ai(*args, **kwargs)
        case _:
            return {"error": "Unknown Hyper3D Rodin mode!"}


def _poll_rodin_job_status_main_site(subscription_key):
    response = requests.post(
        "https://hyperhuman.deemos.com/api/v2/status",
        headers={"Authorization": f"Bearer {bpy.context.scene.blenderweave_hyper3d_api_key}"},
        json={"subscription_key": subscription_key},
    )
    data = response.json()
    return {"status_list": [i["status"] for i in data["jobs"]]}


def _poll_rodin_job_status_fal_ai(request_id):
    response = requests.get(
        f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}/status",
        headers={"Authorization": f"KEY {bpy.context.scene.blenderweave_hyper3d_api_key}"},
    )
    return response.json()


def import_generated_asset(*args, **kwargs):
    match bpy.context.scene.blenderweave_hyper3d_mode:
        case "MAIN_SITE":
            return _import_generated_asset_main_site(*args, **kwargs)
        case "FAL_AI":
            return _import_generated_asset_fal_ai(*args, **kwargs)
        case _:
            return {"error": "Unknown Hyper3D Rodin mode!"}


def _import_generated_asset_main_site(task_uuid, name):
    response = requests.post(
        "https://hyperhuman.deemos.com/api/v2/download",
        headers={"Authorization": f"Bearer {bpy.context.scene.blenderweave_hyper3d_api_key}"},
        json={'task_uuid': task_uuid}
    )
    data_ = response.json()
    temp_file = None
    for i in data_["list"]:
        if i["name"].endswith(".glb"):
            temp_file = tempfile.NamedTemporaryFile(delete=False, prefix=task_uuid, suffix=".glb")
            try:
                response = requests.get(i["url"], stream=True)
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_file.close()
            except Exception as e:
                temp_file.close()
                os.unlink(temp_file.name)
                return {"succeed": False, "error": str(e)}
            break
    else:
        return {"succeed": False, "error": "Generation failed. Please first make sure that all jobs of the task are done and then try again later."}

    try:
        obj = _clean_imported_glb(filepath=temp_file.name, mesh_name=name)
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


def _import_generated_asset_fal_ai(request_id, name):
    response = requests.get(
        f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}",
        headers={"Authorization": f"Key {bpy.context.scene.blenderweave_hyper3d_api_key}"},
    )
    data_ = response.json()
    temp_file = tempfile.NamedTemporaryFile(delete=False, prefix=request_id, suffix=".glb")
    try:
        response = requests.get(data_["model_mesh"]["url"], stream=True)
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
        temp_file.close()
    except Exception as e:
        temp_file.close()
        os.unlink(temp_file.name)
        return {"succeed": False, "error": str(e)}

    try:
        obj = _clean_imported_glb(filepath=temp_file.name, mesh_name=name)
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


def _clean_imported_glb(filepath, mesh_name=None):
    existing_objects = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=filepath)
    bpy.context.view_layer.update()
    imported_objects = list(set(bpy.data.objects) - existing_objects)

    if not imported_objects:
        raise Exception("No objects were imported.")

    mesh_obj = None
    if len(imported_objects) == 1 and imported_objects[0].type == 'MESH':
        mesh_obj = imported_objects[0]
    elif len(imported_objects) == 2:
        empty_objs = [i for i in imported_objects if i.type == "EMPTY"]
        if len(empty_objs) == 1:
            parent_obj = empty_objs[0]
            if len(parent_obj.children) == 1 and parent_obj.children[0].type == 'MESH':
                potential_mesh = parent_obj.children[0]
                potential_mesh.parent = None
                bpy.data.objects.remove(parent_obj)
                mesh_obj = potential_mesh

    if mesh_obj and mesh_name:
        try:
            mesh_obj.name = mesh_name
            if mesh_obj.data and mesh_obj.data.name is not None:
                mesh_obj.data.name = mesh_name
        except Exception:
            pass

    if not mesh_obj:
        raise Exception("Could not identify mesh object from imported GLB.")

    return mesh_obj
