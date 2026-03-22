import bpy
import requests
import tempfile
import os
import shutil
import zipfile
import traceback
from contextlib import suppress

REQ_HEADERS = {"User-Agent": "blender-weave"}


def get_ambientcg_status():
    """Get integration status."""
    enabled = bpy.context.scene.blenderweave_use_ambientcg
    if enabled:
        return {"enabled": True, "message": "AmbientCG integration is enabled. CC0 PBR textures, HDRIs, 3D models."}
    return {"enabled": False, "message": "AmbientCG integration is disabled. Enable it in the BlenderWeave panel."}


def search_ambientcg_assets(query=None, asset_type=None, sort="popular", limit=20):
    """Search AmbientCG for PBR materials, HDRIs, or 3D models."""
    try:
        params = {
            "limit": min(limit, 50),
            "sort": sort,
            "include": "downloads,tags,thumbnails,maps,title,type",
        }
        if query:
            params["q"] = query
        if asset_type and asset_type != "all":
            type_map = {"materials": "material", "textures": "material", "hdris": "hdri", "models": "3d-model"}
            params["type"] = type_map.get(asset_type, asset_type)

        response = requests.get("https://ambientcg.com/api/v3/assets", params=params, headers=REQ_HEADERS, timeout=15)
        if response.status_code != 200:
            return {"error": f"API request failed: {response.status_code}"}

        data = response.json()
        assets = []
        for asset in data.get("assets", []):
            info = {
                "id": asset["id"],
                "title": asset.get("title", asset["id"]),
                "type": asset.get("type", "material"),
                "tags": asset.get("tags", [])[:5],
                "maps": asset.get("maps", []),
            }
            # Get available resolutions from downloads
            downloads = asset.get("downloads", [])
            info["resolutions"] = [d["attributes"] for d in downloads[:6]]
            assets.append(info)

        return {
            "success": True,
            "assets": assets,
            "total_count": data.get("totalResults", len(assets)),
            "returned_count": len(assets),
        }
    except Exception as e:
        return {"error": f"Search failed: {str(e)}"}


def download_ambientcg_asset(asset_id, resolution="2K-JPG", asset_type="material"):
    """Download and import an AmbientCG asset into Blender."""
    try:
        # Get asset info first to find correct download URL
        params = {"id": asset_id, "include": "downloads,type,maps"}
        info_resp = requests.get("https://ambientcg.com/api/v3/assets", params=params, headers=REQ_HEADERS, timeout=15)
        if info_resp.status_code != 200:
            return {"error": f"Failed to get asset info: {info_resp.status_code}"}

        data = info_resp.json()
        assets = data.get("assets", [])
        if not assets:
            return {"error": f"Asset not found: {asset_id}"}

        asset = assets[0]
        actual_type = asset.get("type", asset_type)

        # Find the download URL for requested resolution
        downloads = asset.get("downloads", [])
        download_url = None
        for dl in downloads:
            if dl["attributes"] == resolution:
                download_url = dl["url"]
                break
        if not download_url:
            # Fallback: try common patterns
            download_url = f"https://ambientcg.com/get?file={asset_id}_{resolution}.zip"

        # Download the ZIP
        resp = requests.get(download_url, headers=REQ_HEADERS, timeout=120, allow_redirects=True)
        if resp.status_code != 200:
            available = [d["attributes"] for d in downloads]
            return {"error": f"Download failed ({resp.status_code}). Available: {available}"}

        temp_dir = tempfile.mkdtemp(prefix="ambientcg_")
        zip_path = os.path.join(temp_dir, f"{asset_id}.zip")

        with open(zip_path, "wb") as f:
            f.write(resp.content)

        # Extract ZIP
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)

        os.remove(zip_path)

        if actual_type == "hdri":
            return _import_ambientcg_hdri(temp_dir, asset_id)
        elif actual_type == "3d-model":
            return _import_ambientcg_model(temp_dir, asset_id)
        else:
            return _import_ambientcg_material(temp_dir, asset_id)

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Download failed: {str(e)}"}


def _import_ambientcg_material(temp_dir, asset_id):
    """Import extracted PBR textures as a Blender material."""
    try:
        # Find texture files
        texture_map = {}
        map_names = {
            "Color": "Base Color", "Displacement": "displacement",
            "NormalGL": "Normal", "NormalDX": "Normal",
            "Roughness": "Roughness", "Metalness": "Metallic",
            "AmbientOcclusion": "ao", "Opacity": "Alpha",
            "Emission": "Emission",
        }

        for fname in os.listdir(temp_dir):
            if not fname.lower().endswith(('.jpg', '.png', '.exr')):
                continue
            for map_key, bsdf_name in map_names.items():
                if f"_{map_key}." in fname or f"_{map_key}_" in fname:
                    fpath = os.path.join(temp_dir, fname)
                    img = bpy.data.images.load(fpath)
                    img.name = f"{asset_id}_{map_key}"
                    img.pack()
                    # Set colorspace
                    if map_key == "Color":
                        try: img.colorspace_settings.name = 'sRGB'
                        except: pass
                    else:
                        try: img.colorspace_settings.name = 'Non-Color'
                        except: pass
                    texture_map[map_key] = img
                    break

        if not texture_map:
            return {"error": "No texture maps found in downloaded archive"}

        # Build material
        mat = bpy.data.materials.new(name=asset_id)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (600, 0)
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.location = (300, 0)
        links.new(bsdf.outputs[0], output.inputs[0])

        tex_coord = nodes.new('ShaderNodeTexCoord')
        tex_coord.location = (-800, 0)
        mapping = nodes.new('ShaderNodeMapping')
        mapping.location = (-600, 0)
        links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])

        y = 300
        for map_key, img in texture_map.items():
            tex = nodes.new('ShaderNodeTexImage')
            tex.location = (-300, y)
            tex.image = img
            links.new(mapping.outputs['Vector'], tex.inputs['Vector'])

            if map_key == "Color":
                links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
            elif map_key == "Roughness":
                links.new(tex.outputs['Color'], bsdf.inputs['Roughness'])
            elif map_key == "Metalness":
                links.new(tex.outputs['Color'], bsdf.inputs['Metallic'])
            elif map_key in ("NormalGL", "NormalDX"):
                nmap = nodes.new('ShaderNodeNormalMap')
                nmap.location = (0, y)
                links.new(tex.outputs['Color'], nmap.inputs['Color'])
                links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
            elif map_key == "Displacement":
                disp = nodes.new('ShaderNodeDisplacement')
                disp.location = (300, y - 200)
                disp.inputs['Scale'].default_value = 0.05
                links.new(tex.outputs['Color'], disp.inputs['Height'])
                links.new(disp.outputs['Displacement'], output.inputs['Displacement'])
            elif map_key == "Opacity":
                links.new(tex.outputs['Color'], bsdf.inputs['Alpha'])
                mat.blend_method = 'CLIP' if hasattr(mat, 'blend_method') else None
            y -= 250

        shutil.rmtree(temp_dir, ignore_errors=True)

        return {
            "success": True,
            "message": f"AmbientCG material '{asset_id}' imported",
            "material_name": mat.name,
            "maps": list(texture_map.keys()),
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Material import failed: {str(e)}"}


def _import_ambientcg_hdri(temp_dir, asset_id):
    """Import extracted HDRI as world environment."""
    try:
        hdri_file = None
        for fname in os.listdir(temp_dir):
            if fname.lower().endswith(('.exr', '.hdr')):
                hdri_file = os.path.join(temp_dir, fname)
                break
        if not hdri_file:
            return {"error": "No HDRI file found in archive"}

        if not bpy.data.worlds:
            bpy.data.worlds.new("World")
        world = bpy.data.worlds[0]
        world.use_nodes = True
        tree = world.node_tree
        tree.nodes.clear()

        tc = tree.nodes.new('ShaderNodeTexCoord')
        tc.location = (-800, 0)
        mp = tree.nodes.new('ShaderNodeMapping')
        mp.location = (-600, 0)
        env = tree.nodes.new('ShaderNodeTexEnvironment')
        env.location = (-300, 0)
        env.image = bpy.data.images.load(hdri_file)
        try: env.image.colorspace_settings.name = 'Linear'
        except: pass
        bg = tree.nodes.new('ShaderNodeBackground')
        bg.location = (0, 0)
        out = tree.nodes.new('ShaderNodeOutputWorld')
        out.location = (200, 0)

        tree.links.new(tc.outputs['Generated'], mp.inputs['Vector'])
        tree.links.new(mp.outputs['Vector'], env.inputs['Vector'])
        tree.links.new(env.outputs['Color'], bg.inputs['Color'])
        tree.links.new(bg.outputs['Background'], out.inputs['Surface'])
        bpy.context.scene.world = world

        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"success": True, "message": f"AmbientCG HDRI '{asset_id}' applied to world"}
    except Exception as e:
        return {"error": f"HDRI import failed: {str(e)}"}


def _import_ambientcg_model(temp_dir, asset_id):
    """Import extracted 3D model."""
    try:
        for fname in os.listdir(temp_dir):
            fpath = os.path.join(temp_dir, fname)
            if fname.lower().endswith('.glb') or fname.lower().endswith('.gltf'):
                bpy.ops.import_scene.gltf(filepath=fpath)
                imported = [o.name for o in bpy.context.selected_objects]
                shutil.rmtree(temp_dir, ignore_errors=True)
                return {"success": True, "message": f"AmbientCG model '{asset_id}' imported", "objects": imported}
            elif fname.lower().endswith('.fbx'):
                bpy.ops.import_scene.fbx(filepath=fpath)
                imported = [o.name for o in bpy.context.selected_objects]
                shutil.rmtree(temp_dir, ignore_errors=True)
                return {"success": True, "message": f"AmbientCG model '{asset_id}' imported", "objects": imported}
        return {"error": "No importable model file found in archive"}
    except Exception as e:
        return {"error": f"Model import failed: {str(e)}"}
