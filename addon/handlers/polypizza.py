import bpy
import requests
import tempfile
import os
from contextlib import suppress

REQ_HEADERS = {"User-Agent": "blender-weave"}


def get_polypizza_status():
    """Get the current status of Poly Pizza integration."""
    enabled = bpy.context.scene.blenderweave_use_polypizza
    if not enabled:
        return {
            "enabled": False,
            "message": """Poly Pizza integration is currently disabled. To enable it:
                        1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                        2. Check the 'Use Poly Pizza' checkbox and set your API key
                        3. Restart the MCP connection"""
        }
    api_key = bpy.context.scene.blenderweave_polypizza_api_key
    if not api_key:
        return {
            "enabled": False,
            "message": """Poly Pizza integration is enabled but API key is not set. To configure:
                        1. Get a free API key from https://poly.pizza
                        2. In the BlenderWeave panel, enter your Poly Pizza API key
                        3. Restart the MCP connection"""
        }
    return {"enabled": True, "message": "Poly Pizza integration is enabled and ready to use."}


def search_polypizza_models(query, category=None, limit=20):
    """Search Poly Pizza for low-poly CC0/CC-BY models."""
    try:
        api_key = bpy.context.scene.blenderweave_polypizza_api_key
        if not api_key:
            return {"error": "Poly Pizza API key not configured"}

        headers = dict(REQ_HEADERS)
        headers["X-Auth-Token"] = api_key

        url = f"https://api.poly.pizza/v1.1/search/{query}"
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 401:
            return {"error": "Invalid Poly Pizza API key"}
        if response.status_code != 200:
            return {"error": f"API request failed: {response.status_code}"}

        data = response.json()
        results = data.get("results", [])

        models = []
        for model in results[:limit]:
            info = {
                "id": model.get("ID", ""),
                "title": model.get("Title", ""),
                "download_url": model.get("Download", ""),
                "tri_count": model.get("Tri Count", 0),
                "category": model.get("Category", ""),
                "tags": model.get("Tags", []),
                "licence": model.get("Licence", ""),
                "thumbnail": model.get("Thumbnail", ""),
                "attribution": model.get("Attribution", ""),
            }
            if category and info["category"] != category:
                continue
            models.append(info)

        return {
            "success": True,
            "models": models,
            "returned_count": len(models),
        }
    except Exception as e:
        return {"error": f"Search failed: {str(e)}"}


def download_polypizza_model(model_id, model_url=None):
    """Download and import a Poly Pizza model into Blender."""
    try:
        api_key = bpy.context.scene.blenderweave_polypizza_api_key
        if not api_key:
            return {"error": "Poly Pizza API key not configured"}

        headers = dict(REQ_HEADERS)
        headers["X-Auth-Token"] = api_key

        if not model_url:
            search_resp = requests.get(
                f"https://api.poly.pizza/v1.1/search/{model_id}",
                headers=headers, timeout=15,
            )
            if search_resp.status_code != 200:
                return {"error": f"Failed to find model: {search_resp.status_code}"}
            results = search_resp.json().get("results", [])
            match = None
            for r in results:
                if str(r.get("ID", "")) == str(model_id):
                    match = r
                    break
            if not match:
                return {"error": f"Model not found: {model_id}"}
            model_url = match.get("Download", "")
            if not model_url:
                return {"error": "No download URL for this model"}

        resp = requests.get(model_url, headers=REQ_HEADERS, timeout=120, allow_redirects=True)
        if resp.status_code != 200:
            return {"error": f"Download failed: {resp.status_code}"}

        suffix = ".glb"
        if model_url.lower().endswith(".gltf"):
            suffix = ".gltf"

        tmp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp_path = tmp_file.name
        try:
            tmp_file.write(resp.content)
            tmp_file.close()

            bpy.ops.import_scene.gltf(filepath=tmp_path)
            imported = [obj.name for obj in bpy.context.selected_objects]

            return {
                "success": True,
                "message": f"Poly Pizza model '{model_id}' imported successfully",
                "imported_objects": imported,
            }
        finally:
            with suppress(Exception):
                os.unlink(tmp_path)

    except Exception as e:
        return {"error": f"Download failed: {str(e)}"}
