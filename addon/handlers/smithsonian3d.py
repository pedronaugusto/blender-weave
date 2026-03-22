import bpy
import requests
import tempfile
import os
from contextlib import suppress

REQ_HEADERS = {"User-Agent": "blender-weave"}

SI_SEARCH_URL = "https://api.si.edu/openaccess/api/v1.0/search"
SI_3D_DOC_URL = "https://3d-api.si.edu/content/document"
SI_CDN_URL = "https://cdn.3d-api.si.edu"


def get_smithsonian_status():
    """Get the current status of Smithsonian 3D integration."""
    enabled = bpy.context.scene.blenderweave_use_smithsonian
    if not enabled:
        return {
            "enabled": False,
            "message": """Smithsonian 3D integration is currently disabled. To enable it:
                        1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                        2. Check the 'Use Smithsonian 3D' checkbox and set your API key
                        3. Restart the MCP connection"""
        }
    api_key = bpy.context.scene.blenderweave_smithsonian_api_key
    if not api_key:
        return {
            "enabled": False,
            "message": """Smithsonian 3D integration is enabled but API key is not set. To configure:
                        1. Get a free API key from https://api.data.gov/signup/
                        2. In the BlenderWeave panel, enter your Smithsonian API key
                        3. Restart the MCP connection"""
        }
    return {"enabled": True, "message": "Smithsonian 3D integration is enabled and ready to use."}


def search_smithsonian_models(query, limit=20):
    """Search Smithsonian Open Access for 3D models."""
    try:
        api_key = bpy.context.scene.blenderweave_smithsonian_api_key
        if not api_key:
            return {"error": "Smithsonian API key not configured"}

        params = {
            "q": f"{query} AND online_media_type:3d",
            "api_key": api_key,
            "rows": min(limit, 50),
            "start": 0,
        }
        response = requests.get(SI_SEARCH_URL, params=params, headers=REQ_HEADERS, timeout=15)
        if response.status_code != 200:
            return {"error": f"API request failed: {response.status_code}"}

        data = response.json()
        rows = data.get("response", {}).get("rows", [])
        total = data.get("response", {}).get("rowCount", 0)

        models = []
        for row in rows:
            content = row.get("content", {})
            descriptive = content.get("descriptiveNonRepeating", {})
            freetext = content.get("freetext", {})
            indexed = content.get("indexedStructured", {})

            title_info = descriptive.get("title", {})
            title = title_info.get("content", "") if isinstance(title_info, dict) else str(title_info)

            record_id = row.get("id", "")
            unit_code = descriptive.get("unit_code", "")

            # Extract 3D media UUID from online_media
            media_list = descriptive.get("online_media", {}).get("media", [])
            uuid_3d = None
            for media in media_list:
                media_type = media.get("type", "")
                if "3d" in media_type.lower() or "model" in media_type.lower():
                    content_url = media.get("content", "")
                    if content_url:
                        parts = content_url.rstrip("/").split("/")
                        for part in parts:
                            if len(part) >= 30 and "-" in part:
                                uuid_3d = part
                                break
                    if not uuid_3d:
                        guid = media.get("guid", "")
                        if guid:
                            uuid_3d = guid
                    if uuid_3d:
                        break

            notes = []
            for note in freetext.get("notes", []):
                if isinstance(note, dict):
                    notes.append(note.get("content", ""))

            info = {
                "id": record_id,
                "title": title,
                "unit_code": unit_code,
                "uuid_3d": uuid_3d,
                "topics": indexed.get("topic", []),
                "object_type": indexed.get("object_type", []),
                "notes": notes[:2],
            }
            models.append(info)

        return {
            "success": True,
            "models": models,
            "total_count": total,
            "returned_count": len(models),
        }
    except Exception as e:
        return {"error": f"Search failed: {str(e)}"}


def download_smithsonian_model(model_id, quality="Medium"):
    """Download and import a Smithsonian 3D model into Blender.

    model_id should be the 3D content UUID (uuid_3d from search results).
    """
    try:
        doc_url = f"{SI_3D_DOC_URL}/{model_id}/document.json"
        doc_resp = requests.get(doc_url, headers=REQ_HEADERS, timeout=15)
        if doc_resp.status_code != 200:
            return {"error": f"Failed to fetch document: {doc_resp.status_code}. Is '{model_id}' a valid 3D UUID?"}

        doc = doc_resp.json()

        glb_url = None
        glb_filename = None

        # Look through derivatives for GLB assets matching quality
        derivatives = doc.get("derivatives", [])
        if not derivatives and "items" in doc:
            for item in doc["items"]:
                derivatives.extend(item.get("derivatives", []))

        quality_lower = quality.lower()
        fallback_url = None

        for deriv in derivatives:
            deriv_quality = deriv.get("quality", "").lower()
            assets = deriv.get("assets", [])
            for asset in assets:
                uri = asset.get("uri", "")
                if not uri.lower().endswith(".glb"):
                    continue
                if deriv_quality == quality_lower:
                    glb_url = uri
                    glb_filename = uri.split("/")[-1]
                    break
                if not fallback_url:
                    fallback_url = uri
            if glb_url:
                break

        if not glb_url:
            glb_url = fallback_url
        if not glb_url:
            available = set()
            for d in derivatives:
                for a in d.get("assets", []):
                    if a.get("uri", "").lower().endswith(".glb"):
                        available.add(d.get("quality", "unknown"))
            if available:
                return {"error": f"No GLB at quality '{quality}'. Available: {sorted(available)}"}
            return {"error": "No GLB files found in document"}

        if glb_filename is None:
            glb_filename = glb_url.split("/")[-1]

        if not glb_url.startswith("http"):
            glb_url = f"{SI_CDN_URL}/{model_id}/{glb_url}"

        resp = requests.get(glb_url, headers=REQ_HEADERS, timeout=120, allow_redirects=True)
        if resp.status_code != 200:
            return {"error": f"GLB download failed: {resp.status_code}"}

        tmp_file = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        tmp_path = tmp_file.name
        try:
            tmp_file.write(resp.content)
            tmp_file.close()

            bpy.ops.import_scene.gltf(filepath=tmp_path)
            imported = [obj.name for obj in bpy.context.selected_objects]

            return {
                "success": True,
                "message": f"Smithsonian 3D model '{model_id}' imported successfully",
                "imported_objects": imported,
                "filename": glb_filename,
            }
        finally:
            with suppress(Exception):
                os.unlink(tmp_path)

    except Exception as e:
        return {"error": f"Download failed: {str(e)}"}
