import bpy
import mathutils
import requests
import json
import base64
import tempfile
import os
import shutil
import zipfile
import traceback
from contextlib import suppress
from ._utils import compute_world_aabb
import math


def _collect_hierarchy(obj, meshes, empties):
    """Recursively collect mesh objects and empties from a hierarchy."""
    if obj.type == 'MESH':
        meshes.append(obj)
    elif obj.type in ('EMPTY', 'ARMATURE'):
        empties.append(obj)
    for child in obj.children:
        _collect_hierarchy(child, meshes, empties)


def _detect_and_store_front_axis(mesh_objects):
    """Detect the visual front of imported meshes via bounding box asymmetry.

    Heuristic: the narrower axis of the XY footprint is likely the side axis,
    and the wider axis is front-to-back. The front faces the direction with
    more vertex density (detail). Stores result as 'blenderweave_front_axis'
    custom property on each mesh: '+Y', '-Y', '+X', '-X'.
    """
    if not mesh_objects:
        return

    # Merge all mesh corners to get overall bbox
    all_corners = []
    for obj in mesh_objects:
        try:
            all_corners.extend(
                obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box
            )
        except Exception:
            pass
    if not all_corners:
        return

    min_x = min(c.x for c in all_corners)
    max_x = max(c.x for c in all_corners)
    min_y = min(c.y for c in all_corners)
    max_y = max(c.y for c in all_corners)
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    dx = max_x - min_x
    dy = max_y - min_y

    # Sample vertex positions to detect which half has more detail
    front_axis = "+Y"  # default
    if dx > dy * 1.3:
        # Wider in X — front/back is along X
        # Count verts in +X vs -X half
        plus_count = 0
        minus_count = 0
        for obj in mesh_objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            for v in obj.data.vertices:
                wv = obj.matrix_world @ v.co
                if wv.x > cx:
                    plus_count += 1
                else:
                    minus_count += 1
        front_axis = "-X" if plus_count > minus_count else "+X"
    elif dy > dx * 1.3:
        # Wider in Y — front/back is along Y
        plus_count = 0
        minus_count = 0
        for obj in mesh_objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            for v in obj.data.vertices:
                wv = obj.matrix_world @ v.co
                if wv.y > cy:
                    plus_count += 1
                else:
                    minus_count += 1
        front_axis = "-Y" if plus_count > minus_count else "+Y"

    # Store on all mesh objects
    for obj in mesh_objects:
        obj["blenderweave_front_axis"] = front_axis


def get_sketchfab_status():
    """Get the current status of Sketchfab integration."""
    enabled = bpy.context.scene.blenderweave_use_sketchfab
    api_key = bpy.context.scene.blenderweave_sketchfab_api_key

    if api_key:
        try:
            headers = {"Authorization": f"Token {api_key}"}
            response = requests.get("https://api.sketchfab.com/v3/me", headers=headers, timeout=30)
            if response.status_code == 200:
                user_data = response.json()
                username = user_data.get("username", "Unknown user")
                return {"enabled": True, "message": f"Sketchfab integration is enabled and ready to use. Logged in as: {username}"}
            else:
                return {"enabled": False, "message": f"Sketchfab API key seems invalid. Status code: {response.status_code}"}
        except requests.exceptions.Timeout:
            return {"enabled": False, "message": "Timeout connecting to Sketchfab API. Check your internet connection."}
        except Exception as e:
            return {"enabled": False, "message": f"Error testing Sketchfab API key: {str(e)}"}

    if enabled and api_key:
        return {"enabled": True, "message": "Sketchfab integration is enabled and ready to use."}
    elif enabled and not api_key:
        return {
            "enabled": False,
            "message": """Sketchfab integration is currently enabled, but API key is not given. To enable it:
                        1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                        2. Keep the 'Use Sketchfab' checkbox checked
                        3. Enter your Sketchfab API Key
                        4. Restart the MCP connection"""
        }
    else:
        return {
            "enabled": False,
            "message": """Sketchfab integration is currently disabled. To enable it:
                        1. In the 3D Viewport, find the BlenderWeave panel in the sidebar (press N if hidden)
                        2. Check the 'Use assets from Sketchfab' checkbox
                        3. Enter your Sketchfab API Key
                        4. Restart the MCP connection"""
        }


def search_sketchfab_models(query, categories=None, count=20, downloadable=True):
    """Search for models on Sketchfab."""
    try:
        api_key = bpy.context.scene.blenderweave_sketchfab_api_key
        if not api_key:
            return {"error": "Sketchfab API key is not configured"}

        params = {
            "type": "models",
            "q": query,
            "count": count,
            "downloadable": downloadable,
            "archives_flavours": False
        }
        if categories:
            params["categories"] = categories

        headers = {"Authorization": f"Token {api_key}"}
        response = requests.get("https://api.sketchfab.com/v3/search", headers=headers, params=params, timeout=30)

        if response.status_code == 401:
            return {"error": "Authentication failed (401). Check your API key."}
        if response.status_code != 200:
            return {"error": f"API request failed with status code {response.status_code}"}

        response_data = response.json()
        if response_data is None:
            return {"error": "Received empty response from Sketchfab API"}

        results = response_data.get("results", [])
        if not isinstance(results, list):
            return {"error": f"Unexpected response format from Sketchfab API: {response_data}"}

        return response_data
    except requests.exceptions.Timeout:
        return {"error": "Request timed out. Check your internet connection."}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON response from Sketchfab API: {str(e)}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def get_sketchfab_model_preview(uid):
    """Get thumbnail preview image of a Sketchfab model."""
    try:
        api_key = bpy.context.scene.blenderweave_sketchfab_api_key
        if not api_key:
            return {"error": "Sketchfab API key is not configured"}

        headers = {"Authorization": f"Token {api_key}"}
        response = requests.get(f"https://api.sketchfab.com/v3/models/{uid}", headers=headers, timeout=30)

        if response.status_code == 401:
            return {"error": "Authentication failed (401). Check your API key."}
        if response.status_code == 404:
            return {"error": f"Model not found: {uid}"}
        if response.status_code != 200:
            return {"error": f"Failed to get model info: {response.status_code}"}

        data = response.json()
        thumbnails = data.get("thumbnails", {}).get("images", [])
        if not thumbnails:
            return {"error": "No thumbnail available for this model"}

        selected_thumbnail = None
        for thumb in thumbnails:
            width = thumb.get("width", 0)
            if 400 <= width <= 800:
                selected_thumbnail = thumb
                break
        if not selected_thumbnail:
            selected_thumbnail = thumbnails[0]

        thumbnail_url = selected_thumbnail.get("url")
        if not thumbnail_url:
            return {"error": "Thumbnail URL not found"}

        img_response = requests.get(thumbnail_url, timeout=30)
        if img_response.status_code != 200:
            return {"error": f"Failed to download thumbnail: {img_response.status_code}"}

        image_data = base64.b64encode(img_response.content).decode('ascii')
        content_type = img_response.headers.get("Content-Type", "")
        img_format = "png" if ("png" in content_type or thumbnail_url.endswith(".png")) else "jpeg"

        return {
            "success": True,
            "image_data": image_data,
            "format": img_format,
            "model_name": data.get("name", "Unknown"),
            "author": data.get("user", {}).get("username", "Unknown"),
            "uid": uid,
            "thumbnail_width": selected_thumbnail.get("width"),
            "thumbnail_height": selected_thumbnail.get("height")
        }
    except requests.exceptions.Timeout:
        return {"error": "Request timed out. Check your internet connection."}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to get model preview: {str(e)}"}


def download_sketchfab_model(uid, normalize_size=False, target_size=1.0):
    """Download a model from Sketchfab by its UID."""
    try:
        api_key = bpy.context.scene.blenderweave_sketchfab_api_key
        if not api_key:
            return {"error": "Sketchfab API key is not configured"}

        headers = {"Authorization": f"Token {api_key}"}
        response = requests.get(f"https://api.sketchfab.com/v3/models/{uid}/download", headers=headers, timeout=30)

        if response.status_code == 401:
            return {"error": "Authentication failed (401). Check your API key."}
        if response.status_code != 200:
            return {"error": f"Download request failed with status code {response.status_code}"}

        data = response.json()
        if data is None:
            return {"error": "Received empty response from Sketchfab API for download request"}

        gltf_data = data.get("gltf")
        if not gltf_data:
            return {"error": "No gltf download URL available for this model. Response: " + str(data)}
        download_url = gltf_data.get("url")
        if not download_url:
            return {"error": "No download URL available for this model."}

        model_response = requests.get(download_url, timeout=60)
        if model_response.status_code != 200:
            return {"error": f"Model download failed with status code {model_response.status_code}"}

        temp_dir = tempfile.mkdtemp()
        zip_file_path = os.path.join(temp_dir, f"{uid}.zip")
        with open(zip_file_path, "wb") as f:
            f.write(model_response.content)

        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                file_path = file_info.filename
                target_path = os.path.join(temp_dir, os.path.normpath(file_path))
                abs_temp_dir = os.path.abspath(temp_dir)
                abs_target_path = os.path.abspath(target_path)
                if not abs_target_path.startswith(abs_temp_dir):
                    with suppress(Exception):
                        shutil.rmtree(temp_dir)
                    return {"error": "Security issue: Zip contains files with path traversal attempt"}
                if ".." in file_path:
                    with suppress(Exception):
                        shutil.rmtree(temp_dir)
                    return {"error": "Security issue: Zip contains files with directory traversal sequence"}
            zip_ref.extractall(temp_dir)

        gltf_files = [f for f in os.listdir(temp_dir) if f.endswith('.gltf') or f.endswith('.glb')]
        if not gltf_files:
            with suppress(Exception):
                shutil.rmtree(temp_dir)
            return {"error": "No glTF file found in the downloaded model"}

        main_file = os.path.join(temp_dir, gltf_files[0])
        bpy.ops.import_scene.gltf(filepath=main_file)

        imported_objects = list(bpy.context.selected_objects)
        imported_object_names = [obj.name for obj in imported_objects]

        with suppress(Exception):
            shutil.rmtree(temp_dir)

        root_objects = [obj for obj in imported_objects if obj.parent is None]

        def _compute_hierarchy_aabb(root_objects):
            """Compute merged AABB across all root objects using compute_world_aabb."""
            merged_min = mathutils.Vector((float('inf'), float('inf'), float('inf')))
            merged_max = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
            has_geometry = False
            for root in root_objects:
                aabb_min, aabb_max, _ = compute_world_aabb(root)
                if aabb_min is not None:
                    has_geometry = True
                    merged_min.x = min(merged_min.x, aabb_min.x)
                    merged_min.y = min(merged_min.y, aabb_min.y)
                    merged_min.z = min(merged_min.z, aabb_min.z)
                    merged_max.x = max(merged_max.x, aabb_max.x)
                    merged_max.y = max(merged_max.y, aabb_max.y)
                    merged_max.z = max(merged_max.z, aabb_max.z)
            if not has_geometry:
                return None, None, None
            dims = [merged_max.x - merged_min.x, merged_max.y - merged_min.y, merged_max.z - merged_min.z]
            return merged_min, merged_max, dims

        all_min, all_max, dimensions = _compute_hierarchy_aabb(root_objects)

        if dimensions is not None:
            max_dimension = max(dimensions)

            scale_applied = 1.0
            if normalize_size and max_dimension > 0:
                scale_factor = target_size / max_dimension
                scale_applied = scale_factor
                for root in root_objects:
                    root.scale = (root.scale.x * scale_factor, root.scale.y * scale_factor, root.scale.z * scale_factor)
                bpy.context.view_layer.update()

                all_min, all_max, dimensions = _compute_hierarchy_aabb(root_objects)

            world_bounding_box = [[all_min.x, all_min.y, all_min.z], [all_max.x, all_max.y, all_max.z]]
        else:
            world_bounding_box = None
            dimensions = None
            scale_applied = 1.0

        # ── Flatten Sketchfab hierarchy ──
        # Sketchfab imports create deep empty chains (Sketchfab_model > RootNode >
        # GLTF_SceneRootNode > ...). The empties have transforms that don't
        # propagate reliably via depsgraph. Fix: bake world transforms into mesh
        # objects, unparent them, then delete the empty chain.
        mesh_objects_imported = []
        empty_chain = []
        for root in root_objects:
            _collect_hierarchy(root, mesh_objects_imported, empty_chain)

        if mesh_objects_imported:
            # Bake world transform into each mesh object
            for mesh_obj in mesh_objects_imported:
                # Store current world matrix
                world_mat = mesh_obj.matrix_world.copy()
                # Unparent keeping transform
                mesh_obj.parent = None
                mesh_obj.matrix_world = world_mat

            bpy.context.view_layer.update()

            # Detect front axis from mesh asymmetry and store as custom property
            _detect_and_store_front_axis(mesh_objects_imported)

            # Create a single organizing empty as parent (flat, no transform chain)
            if len(mesh_objects_imported) > 1:
                # Use first root's name for the group
                group_name = root_objects[0].name if root_objects else "Imported"
                group_empty = bpy.data.objects.new(group_name + "_group", None)
                bpy.context.scene.collection.objects.link(group_empty)
                group_empty.empty_display_type = 'PLAIN_AXES'
                group_empty.empty_display_size = 0.1
                # Compute group center
                all_corners = []
                for m in mesh_objects_imported:
                    try:
                        all_corners.extend(
                            m.matrix_world @ mathutils.Vector(c) for c in m.bound_box
                        )
                    except Exception:
                        pass
                if all_corners:
                    group_empty.location = (
                        sum(c.x for c in all_corners) / len(all_corners),
                        sum(c.y for c in all_corners) / len(all_corners),
                        min(c.z for c in all_corners),  # base at floor
                    )
                # Parent meshes to flat group (keep world transform)
                for mesh_obj in mesh_objects_imported:
                    world_mat = mesh_obj.matrix_world.copy()
                    mesh_obj.parent = group_empty
                    mesh_obj.matrix_world = world_mat

                bpy.context.view_layer.update()

            # Delete empty chain (bottom-up to avoid dangling refs)
            for emp in reversed(empty_chain):
                try:
                    bpy.data.objects.remove(emp, do_unlink=True)
                except Exception:
                    pass

        imported_object_names = [obj.name for obj in mesh_objects_imported]

        # Normalize origin to geometry center
        result = {"success": True, "message": "Model imported successfully", "imported_objects": imported_object_names}
        result["flattened"] = True
        result["mesh_count"] = len(mesh_objects_imported)

        if world_bounding_box:
            result["world_bounding_box"] = world_bounding_box
        if dimensions:
            result["dimensions"] = [round(d, 4) for d in dimensions]
        if normalize_size:
            result["scale_applied"] = round(scale_applied, 6)
            result["normalized"] = True

        return result
    except requests.exceptions.Timeout:
        return {"error": "Request timed out. Check your internet connection and try again with a simpler model."}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON response from Sketchfab API: {str(e)}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to download model: {str(e)}"}
