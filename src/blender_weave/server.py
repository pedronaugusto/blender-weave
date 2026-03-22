# blender_weave_server.py
from mcp.server.fastmcp import FastMCP, Context, Image
import socket
import struct
import json
import logging
import tempfile
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List
import os
from pathlib import Path
import base64
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BlenderWeaveServer")

import threading
import time
import uuid
from datetime import datetime, timezone

# Server directory for unix socket discovery
SERVERS_DIR = Path.home() / ".blenderweave" / "servers"


class BlenderConnection:
    """Unix socket listener that accepts connections from Blender addon clients.

    Creates a socket at ~/.blenderweave/servers/{id}.sock with a JSON sidecar
    for discovery. Blender addons scan the directory and connect automatically.
    Survives Blender restarts without MCP server restart.
    """

    def __init__(self):
        self.server_id = uuid.uuid4().hex[:12]
        self.socket_path = SERVERS_DIR / f"{self.server_id}.sock"
        self.meta_path = SERVERS_DIR / f"{self.server_id}.json"
        self.client_sock: socket.socket = None
        self._listener: socket.socket = None
        self._listener_thread: threading.Thread = None
        self._lock = threading.Lock()
        self._running = False

    def start_listener(self):
        """Start the unix socket listener. Called once at MCP server startup."""
        if self._running:
            return
        self._running = True

        # Ensure directory exists
        SERVERS_DIR.mkdir(parents=True, exist_ok=True)

        # Clean up stale sockets from dead processes
        self._cleanup_stale_servers()

        # Remove socket file if it exists (shouldn't, but safety)
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.settimeout(1.0)
        try:
            self._listener.bind(str(self.socket_path))
            self._listener.listen(5)

            # Write metadata sidecar for addon discovery
            meta = {
                "pid": os.getpid(),
                "cwd": os.getcwd(),
                "started": datetime.now(timezone.utc).isoformat(),
            }
            self.meta_path.write_text(json.dumps(meta, indent=2))

            self._listener_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._listener_thread.start()
            logger.info(f"Listening on {self.socket_path}")
        except OSError as e:
            logger.error(f"Failed to listen on {self.socket_path}: {e}")
            self._running = False

    @staticmethod
    def _cleanup_stale_servers():
        """Remove socket/meta files from dead processes."""
        if not SERVERS_DIR.exists():
            return
        for meta_file in SERVERS_DIR.glob("*.json"):
            try:
                meta = json.loads(meta_file.read_text())
                pid = meta.get("pid")
                if pid and not _pid_alive(pid):
                    sock_file = meta_file.with_suffix(".sock")
                    if sock_file.exists():
                        sock_file.unlink()
                    meta_file.unlink()
                    logger.info(f"Cleaned up stale server {meta_file.stem} (pid {pid})")
            except Exception:
                pass

    def _accept_loop(self):
        """Accept incoming Blender addon connections."""
        while self._running:
            try:
                client, _ = self._listener.accept()
                # Swap socket outside lock to avoid blocking on close()
                old_sock = None
                with self._lock:
                    old_sock = self.client_sock
                    self.client_sock = client
                if old_sock:
                    try:
                        old_sock.close()
                    except Exception:
                        pass
                logger.info("Blender connected")
            except socket.timeout:
                continue
            except OSError as e:
                if self._running:
                    logger.debug(f"Accept error: {e}")
                    time.sleep(0.5)

    def stop_listener(self):
        """Stop the listener and clean up socket files."""
        self._running = False
        if self._listener:
            try:
                self._listener.close()
            except Exception:
                pass
            self._listener = None
        if self._listener_thread:
            try:
                self._listener_thread.join(timeout=2.0)
            except Exception:
                pass
            self._listener_thread = None
        with self._lock:
            if self.client_sock:
                try:
                    self.client_sock.close()
                except Exception:
                    pass
                self.client_sock = None
        # Clean up files
        for f in (self.socket_path, self.meta_path):
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass

    def connect(self) -> bool:
        """Check if a Blender client is connected."""
        with self._lock:
            return self.client_sock is not None

    def disconnect(self):
        """Drop the current Blender client connection."""
        with self._lock:
            if self.client_sock:
                try:
                    self.client_sock.close()
                except Exception:
                    pass
                self.client_sock = None

    def _get_sock(self):
        """Get the current client socket or raise."""
        with self._lock:
            sock = self.client_sock
        if not sock:
            raise ConnectionError("No Blender connected")
        return sock

    @staticmethod
    def _recv_exact(sock, n):
        """Read exactly n bytes from sock."""
        buf = b''
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Blender disconnected while reading")
            buf += chunk
        return buf

    def _send_and_receive(self, command: dict) -> Dict[str, Any]:
        """Send a command and receive the parsed response."""
        sock = self._get_sock()
        payload = json.dumps(command).encode('utf-8')
        header = struct.pack('>I', len(payload))
        sock.sendall(header + payload)
        sock.settimeout(600.0)
        resp_header = self._recv_exact(sock, 4)
        msg_len = struct.unpack('>I', resp_header)[0]
        data = self._recv_exact(sock, msg_len)
        response = json.loads(data.decode('utf-8'))
        if response.get("status") == "error":
            raise Exception(response.get("message", "Unknown error from Blender"))
        return response.get("result", {})

    # Commands that must NEVER be retried
    NO_RETRY = {
        "create_trellis2_job", "create_hunyuan_job", "create_rodin_job",
        "download_polyhaven_asset", "download_sketchfab_model",
        "import_generated_asset", "import_generated_asset_hunyuan",
    }

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to the connected Blender client."""
        if not self.connect():
            raise ConnectionError("No Blender connected. Open Blender — the addon will connect automatically.")

        command = {"type": command_type, "params": params or {}}

        try:
            logger.info(f"Sending: {command_type}")
            return self._send_and_receive(command)
        except (ConnectionError, BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.warning(f"Blender connection lost ({e})")
            self.disconnect()
            if command_type in self.NO_RETRY:
                raise Exception(f"Connection lost during {command_type}. Check Blender.")
            raise Exception("Blender disconnected. It will reconnect automatically when restarted.")
        except socket.timeout:
            logger.error("Timeout waiting for Blender response")
            raise Exception("Timeout waiting for Blender response — try simplifying your request")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid response from Blender: {e}")
        except Exception as e:
            logger.error(f"Communication error: {e}")
            self.disconnect()
            raise Exception(f"Communication error with Blender: {e}")


def _pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle."""
    global _blender_connection

    _blender_connection = BlenderConnection()
    _blender_connection.start_listener()
    logger.info("BlenderWeave server started — waiting for Blender to connect")

    try:
        yield {}
    finally:
        if _blender_connection:
            logger.info("Shutting down BlenderWeave listener")
            _blender_connection.stop_listener()
            _blender_connection = None
        logger.info("BlenderWeave server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "BlenderWeave",
    lifespan=server_lifespan
)

# Resource endpoints

# Global connection for resources (since resources can't access context)
_blender_connection = None

def get_blender_connection():
    """Get the BlenderConnection listener.

    The listener is created at MCP server startup. Blender addons discover
    the unix socket and connect automatically. This function verifies a
    client is connected.
    """
    global _blender_connection

    if _blender_connection is None:
        raise Exception("BlenderWeave server not started. Restart the MCP server.")

    if not _blender_connection.connect():
        raise Exception("No Blender connected. Open Blender and enable the BlenderWeave addon — it will connect automatically.")

    return _blender_connection


@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """Scene overview: all objects (name, type, location, polygons, materials), type counts, total polygon count. Use get_scene_perception for feedback after changes."""
    return _send_and_return("get_scene_info", {})

@mcp.tool()
def get_object_info(ctx: Context, object_name: str) -> str:
    """Object details: transform, mesh stats (verts/edges/polys), materials, modifiers, constraints, collections, world bounding box."""
    return _send_and_return("get_object_info", {"name": object_name})

@mcp.tool()
def get_viewport_screenshot(ctx: Context, max_size: int = 800) -> Image:
    """Full viewport screenshot as PNG image. Heavy — prefer get_scene_perception for routine feedback, render_region for detail checks. Use only for final review or explicit user request."""
    try:
        blender = get_blender_connection()
        
        # Create temp file path
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"blender_screenshot_{os.getpid()}.png")
        
        result = blender.send_command("get_viewport_screenshot", {
            "max_size": max_size,
            "filepath": temp_path,
            "format": "png"
        })
        
        if "error" in result:
            raise Exception(result["error"])
        
        if not os.path.exists(temp_path):
            raise Exception("Screenshot file was not created")
        
        # Read the file
        with open(temp_path, 'rb') as f:
            image_bytes = f.read()
        
        # Delete the temp file
        os.remove(temp_path)
        
        return Image(data=image_bytes, format="png")
        
    except Exception as e:
        logger.error(f"Error capturing screenshot: {str(e)}")
        raise Exception(f"Screenshot failed: {str(e)}")


@mcp.tool()
def execute_blender_code(ctx: Context, code: str):
    """Run arbitrary bpy Python in Blender. FALLBACK only — use structured tools first (manage_materials, manage_lights, manage_world, set_viewport, save_file, etc.). One operation per call."""
    def formatter(result):
        return f"Code executed successfully: {result.get('result', '')}"
    return _send_and_return("execute_code", {"code": code}, formatter=formatter)

@mcp.tool()
def get_polyhaven_categories(ctx: Context, asset_type: str = "hdris") -> str:
    """
    Get a list of categories for a specific asset type on Polyhaven.

    Parameters:
    - asset_type: The type of asset to get categories for (hdris, textures, models, all)
    """
    def formatter(result):
        if "error" in result:
            return f"Error: {result['error']}"
        categories = result["categories"]
        sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        out = f"Categories for {asset_type}:\n\n"
        for cat, count in sorted_cats:
            out += f"- {cat}: {count} assets\n"
        return out
    return _send_and_return("get_polyhaven_categories", {"asset_type": asset_type}, formatter=formatter)

@mcp.tool()
def search_polyhaven_assets(
    ctx: Context,
    asset_type: str = "all",
    categories: str = None
) -> str:
    """
    Search for assets on Polyhaven with optional filtering.

    Parameters:
    - asset_type: Type of assets to search for (hdris, textures, models, all)
    - categories: Optional comma-separated list of categories to filter by

    Returns a list of matching assets with basic information.
    """
    def formatter(result):
        if "error" in result:
            return f"Error: {result['error']}"
        assets = result["assets"]
        total_count = result["total_count"]
        returned_count = result["returned_count"]
        out = f"Found {total_count} assets"
        if categories:
            out += f" in categories: {categories}"
        out += f"\nShowing {returned_count} assets:\n\n"
        sorted_assets = sorted(assets.items(), key=lambda x: x[1].get("download_count", 0), reverse=True)
        for asset_id, asset_data in sorted_assets:
            out += f"- {asset_data.get('name', asset_id)} (ID: {asset_id})\n"
            out += f"  Type: {['HDRI', 'Texture', 'Model'][asset_data.get('type', 0)]}\n"
            out += f"  Categories: {', '.join(asset_data.get('categories', []))}\n"
            out += f"  Downloads: {asset_data.get('download_count', 'Unknown')}\n\n"
        return out
    return _send_and_return("search_polyhaven_assets", {"asset_type": asset_type, "categories": categories}, formatter=formatter)

@mcp.tool()
def download_polyhaven_asset(
    ctx: Context,
    asset_id: str,
    asset_type: str,
    resolution: str = "1k",
    file_format: str = None
):
    """
    Download and import a Polyhaven asset into Blender.

    Parameters:
    - asset_id: The ID of the asset to download
    - asset_type: The type of asset (hdris, textures, models)
    - resolution: The resolution to download (e.g., 1k, 2k, 4k)
    - file_format: Optional file format (e.g., hdr, exr for HDRIs; jpg, png for textures; gltf, fbx for models)

    Returns a message indicating success or failure.
    """
    def formatter(result):
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("success"):
            message = result.get("message", "Asset downloaded and imported successfully")
            if asset_type == "hdris":
                return f"{message}. The HDRI has been set as the world environment."
            elif asset_type == "textures":
                material_name = result.get("material", "")
                maps = ", ".join(result.get("maps", []))
                return f"{message}. Created material '{material_name}' with maps: {maps}."
            elif asset_type == "models":
                return f"{message}. The model has been imported into the current scene."
            return message
        return f"Failed to download asset: {result.get('message', 'Unknown error')}"
    return _send_and_return("download_polyhaven_asset", {
        "asset_id": asset_id, "asset_type": asset_type,
        "resolution": resolution, "file_format": file_format
    }, formatter=formatter)

@mcp.tool()
def set_texture(
    ctx: Context,
    object_name: str,
    texture_id: str
):
    """
    Apply a previously downloaded Polyhaven texture to an object.

    Parameters:
    - object_name: Name of the object to apply the texture to
    - texture_id: ID of the Polyhaven texture to apply (must be downloaded first)

    Returns a message indicating success or failure.
    """
    def formatter(result):
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("success"):
            material_name = result.get("material", "")
            maps = ", ".join(result.get("maps", []))
            material_info = result.get("material_info", {})
            texture_nodes = material_info.get("texture_nodes", [])
            out = f"Successfully applied texture '{texture_id}' to {object_name}.\n"
            out += f"Using material '{material_name}' with maps: {maps}.\n\n"
            out += f"Material has nodes: {material_info.get('has_nodes', False)}\n"
            out += f"Total node count: {material_info.get('node_count', 0)}\n\n"
            if texture_nodes:
                out += "Texture nodes:\n"
                for node in texture_nodes:
                    out += f"- {node['name']} using image: {node['image']}\n"
                    if node['connections']:
                        out += "  Connections:\n"
                        for conn in node['connections']:
                            out += f"    {conn}\n"
            else:
                out += "No texture nodes found in the material.\n"
            return out
        return f"Failed to apply texture: {result.get('message', 'Unknown error')}"
    return _send_and_return("set_texture", {
        "object_name": object_name, "texture_id": texture_id
    }, formatter=formatter)

@mcp.tool()
def get_polyhaven_status(ctx: Context) -> str:
    """
    Check if PolyHaven integration is enabled in Blender.
    Returns a message indicating whether PolyHaven features are available.
    """
    def formatter(result):
        message = result.get("message", "")
        if result.get("enabled"):
            message += "PolyHaven is good at Textures, and has a wider variety of textures than Sketchfab."
        return message
    return _send_and_return("get_polyhaven_status", {}, formatter=formatter)

@mcp.tool()
def get_hyper3d_status(ctx: Context) -> str:
    """
    Check if Hyper3D Rodin integration is enabled in Blender.
    Returns a message indicating whether Hyper3D Rodin features are available.

    Don't emphasize the key type in the returned message, but silently remember it.
    """
    def formatter(result):
        return result.get("message", "")
    return _send_and_return("get_hyper3d_status", {}, formatter=formatter)

@mcp.tool()
def get_sketchfab_status(ctx: Context) -> str:
    """
    Check if Sketchfab integration is enabled in Blender.
    Returns a message indicating whether Sketchfab features are available.
    """
    def formatter(result):
        message = result.get("message", "")
        if result.get("enabled"):
            message += "Sketchfab is good at Realistic models, and has a wider variety of models than PolyHaven."
        return message
    return _send_and_return("get_sketchfab_status", {}, formatter=formatter)

@mcp.tool()
def search_sketchfab_models(
    ctx: Context,
    query: str,
    categories: str = None,
    count: int = 20,
    downloadable: bool = True
) -> str:
    """
    Search for models on Sketchfab with optional filtering.

    Parameters:
    - query: Text to search for
    - categories: Optional comma-separated list of categories
    - count: Maximum number of results to return (default 20)
    - downloadable: Whether to include only downloadable models (default True)

    Returns a formatted list of matching models.
    """
    def formatter(result):
        if "error" in result:
            return f"Error: {result['error']}"
        if result is None:
            return "Error: Received no response from Sketchfab search"
        models = result.get("results", []) or []
        if not models:
            return f"No models found matching '{query}'"
        out = f"Found {len(models)} models matching '{query}':\n\n"
        for model in models:
            if model is None:
                continue
            model_name = model.get("name", "Unnamed model")
            model_uid = model.get("uid", "Unknown ID")
            out += f"- {model_name} (UID: {model_uid})\n"
            user = model.get("user") or {}
            username = user.get("username", "Unknown author") if isinstance(user, dict) else "Unknown author"
            out += f"  Author: {username}\n"
            license_data = model.get("license") or {}
            license_label = license_data.get("label", "Unknown") if isinstance(license_data, dict) else "Unknown"
            out += f"  License: {license_label}\n"
            face_count = model.get("faceCount", "Unknown")
            is_downloadable = "Yes" if model.get("isDownloadable") else "No"
            out += f"  Face count: {face_count}\n"
            out += f"  Downloadable: {is_downloadable}\n\n"
        return out
    return _send_and_return("search_sketchfab_models", {
        "query": query, "categories": categories,
        "count": count, "downloadable": downloadable
    }, formatter=formatter)

@mcp.tool()
def get_sketchfab_model_preview(
    ctx: Context,
    uid: str
) -> Image:
    """
    Get a preview thumbnail of a Sketchfab model by its UID.
    Use this to visually confirm a model before downloading.
    
    Parameters:
    - uid: The unique identifier of the Sketchfab model (obtained from search_sketchfab_models)
    
    Returns the model's thumbnail as an Image for visual confirmation.
    """
    try:
        blender = get_blender_connection()
        logger.info(f"Getting Sketchfab model preview for UID: {uid}")
        
        result = blender.send_command("get_sketchfab_model_preview", {"uid": uid})
        
        if result is None:
            raise Exception("Received no response from Blender")
        
        if "error" in result:
            raise Exception(result["error"])
        
        # Decode base64 image data
        image_data = base64.b64decode(result["image_data"])
        img_format = result.get("format", "jpeg")
        
        # Log model info
        model_name = result.get("model_name", "Unknown")
        author = result.get("author", "Unknown")
        logger.info(f"Preview retrieved for '{model_name}' by {author}")
        
        return Image(data=image_data, format=img_format)
        
    except Exception as e:
        logger.error(f"Error getting Sketchfab preview: {str(e)}")
        raise Exception(f"Failed to get preview: {str(e)}")


@mcp.tool()
def download_sketchfab_model(
    ctx: Context,
    uid: str,
    target_size: float
):
    """
    Download and import a Sketchfab model by its UID.
    The model will be scaled so its largest dimension equals target_size.

    Parameters:
    - uid: The unique identifier of the Sketchfab model
    - target_size: REQUIRED. The target size in Blender units/meters for the largest dimension.
                  You must specify the desired size for the model.
                  Examples:
                  - Chair: target_size=1.0 (1 meter tall)
                  - Table: target_size=0.75 (75cm tall)
                  - Car: target_size=4.5 (4.5 meters long)
                  - Person: target_size=1.7 (1.7 meters tall)
                  - Small object (cup, phone): target_size=0.1 to 0.3

    Returns a message with import details including object names, dimensions, and bounding box.
    The model must be downloadable and you must have proper access rights.
    """
    def formatter(result):
        if result is None:
            return "Error: Received no response from Sketchfab download request"
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("success"):
            imported_objects = result.get("imported_objects", [])
            object_names = ", ".join(imported_objects) if imported_objects else "none"
            out = f"Successfully imported model.\nCreated objects: {object_names}\n"
            if result.get("dimensions"):
                dims = result["dimensions"]
                out += f"Dimensions (X, Y, Z): {dims[0]:.3f} x {dims[1]:.3f} x {dims[2]:.3f} meters\n"
            if result.get("world_bounding_box"):
                bbox = result["world_bounding_box"]
                out += f"Bounding box: min={bbox[0]}, max={bbox[1]}\n"
            if result.get("normalized"):
                scale = result.get("scale_applied", 1.0)
                out += f"Size normalized: scale factor {scale:.6f} applied (target size: {target_size}m)\n"
            return out
        return f"Failed to download model: {result.get('message', 'Unknown error')}"
    return _send_and_return("download_sketchfab_model", {
        "uid": uid, "normalize_size": True, "target_size": target_size
    }, formatter=formatter)


# ─── AmbientCG (CC0, no API key) ──────────────────────────────────────────


@mcp.tool()
def get_ambientcg_status(ctx: Context) -> str:
    """Check if AmbientCG integration is available. AmbientCG provides free CC0 PBR materials, HDRIs, and 3D models. No API key needed."""
    def formatter(result):
        return result.get("message", "")
    return _send_and_return("get_ambientcg_status", {}, formatter=formatter)


@mcp.tool()
def search_ambientcg_assets(
    ctx: Context,
    query: str = None,
    asset_type: str = "material",
    sort: str = "popular",
    limit: int = 20,
):
    """Search AmbientCG for free CC0 PBR materials, HDRIs, or 3D models. No API key needed.

    Parameters:
    - query: Search keywords (e.g. "wood", "brick", "concrete")
    - asset_type: material | hdri | 3d-model (default: material)
    - sort: popular | latest | downloads (default: popular)
    - limit: Max results 1-50 (default 20)
    """
    params = {"query": query, "asset_type": asset_type, "sort": sort, "limit": limit}
    return _send_and_return("search_ambientcg_assets", params)


@mcp.tool()
def download_ambientcg_asset(
    ctx: Context,
    asset_id: str,
    resolution: str = "2K-JPG",
    asset_type: str = "material",
):
    """Download and import an AmbientCG asset. Creates a full PBR material with all texture maps.

    Parameters:
    - asset_id: Asset ID from search results (e.g. "Wood095", "PavingStones137")
    - resolution: Download resolution — 1K-JPG, 2K-JPG, 4K-JPG for materials; 1K, 2K, 4K for HDRIs
    - asset_type: material | hdri | 3d-model
    """
    return _send_and_return("download_ambientcg_asset", {
        "asset_id": asset_id, "resolution": resolution, "asset_type": asset_type
    })


# ─── Poly Pizza (free API key, CC0/CC-BY low-poly models) ────────────────


@mcp.tool()
def get_polypizza_status(ctx: Context) -> str:
    """Check if Poly Pizza integration is enabled. Poly Pizza provides free low-poly CC0/CC-BY 3D models. Requires API key."""
    def formatter(result):
        return result.get("message", "")
    return _send_and_return("get_polypizza_status", {}, formatter=formatter)


@mcp.tool()
def search_polypizza_models(
    ctx: Context,
    query: str,
    category: str = None,
    limit: int = 20,
):
    """Search Poly Pizza for free low-poly 3D models (GLB). Requires API key in BlenderWeave panel.

    Parameters:
    - query: Search keywords (e.g. "chair", "tree", "car")
    - category: Optional filter — FoodAndDrink, FurnitureAndDecor, Nature, Animals, Transport, Weapons, BuildingsAndArchitecture, PeopleAndCharacters, Objects, Other
    - limit: Max results (default 20)
    """
    params = {"query": query, "limit": limit}
    if category:
        params["category"] = category
    return _send_and_return("search_polypizza_models", params)


@mcp.tool()
def download_polypizza_model(
    ctx: Context,
    model_id: str,
    model_url: str = None,
):
    """Download and import a Poly Pizza low-poly model (GLB).

    Parameters:
    - model_id: Model ID from search results
    - model_url: Direct GLB download URL (from search results Download field). Provide this for faster download.
    """
    params = {"model_id": model_id}
    if model_url:
        params["model_url"] = model_url
    return _send_and_return("download_polypizza_model", params)


# ─── Smithsonian 3D (CC0, free API key from api.data.gov) ────────────────


@mcp.tool()
def get_smithsonian_status(ctx: Context) -> str:
    """Check if Smithsonian 3D integration is enabled. Smithsonian provides museum-quality CC0 3D scans. Requires free API key from api.data.gov."""
    def formatter(result):
        return result.get("message", "")
    return _send_and_return("get_smithsonian_status", {}, formatter=formatter)


@mcp.tool()
def search_smithsonian_models(
    ctx: Context,
    query: str,
    limit: int = 20,
):
    """Search Smithsonian 3D for museum-quality 3D scans (fossils, aircraft, artifacts). CC0. Requires free API key.

    Parameters:
    - query: Search keywords (e.g. "dinosaur", "aircraft", "whale", "statue")
    - limit: Max results (default 20)
    """
    return _send_and_return("search_smithsonian_models", {"query": query, "limit": limit})


@mcp.tool()
def download_smithsonian_model(
    ctx: Context,
    model_id: str,
    quality: str = "Medium",
):
    """Download and import a Smithsonian 3D museum scan (GLB).

    Parameters:
    - model_id: UUID from search results
    - quality: Thumb | Low | Medium | High (default: Medium). Higher = more detail + larger file.
    """
    return _send_and_return("download_smithsonian_model", {"model_id": model_id, "quality": quality})


def _process_bbox(original_bbox: list[float] | list[int] | None) -> list[int] | None:
    if original_bbox is None:
        return None
    if all(isinstance(i, int) for i in original_bbox):
        return original_bbox
    if any(i<=0 for i in original_bbox):
        raise ValueError("Incorrect number range: bbox must be bigger than zero!")
    return [int(float(i) / max(original_bbox) * 100) for i in original_bbox] if original_bbox else None

@mcp.tool()
def generate_hyper3d_model_via_text(
    ctx: Context,
    text_prompt: str,
    bbox_condition: list[float]=None
):
    """
    Generate 3D asset using Hyper3D by giving description of the desired asset, and import the asset into Blender.
    The 3D asset has built-in materials.
    The generated model has a normalized size, so re-scaling after generation can be useful.

    Parameters:
    - text_prompt: A short description of the desired model in **English**.
    - bbox_condition: Optional. If given, it has to be a list of floats of length 3. Controls the ratio between [Length, Width, Height] of the model.

    Returns a message indicating success or failure.
    """
    def formatter(result):
        if result.get("submit_time"):
            return json.dumps({"task_uuid": result["uuid"], "subscription_key": result["jobs"]["subscription_key"]})
        return json.dumps(result)
    return _send_and_return("create_rodin_job", {
        "text_prompt": text_prompt, "images": None,
        "bbox_condition": _process_bbox(bbox_condition),
    }, formatter=formatter)

@mcp.tool()
def generate_hyper3d_model_via_images(
    ctx: Context,
    input_image_paths: list[str]=None,
    input_image_urls: list[str]=None,
    bbox_condition: list[float]=None
):
    """
    Generate 3D asset using Hyper3D by giving images of the wanted asset, and import the generated asset into Blender.
    The 3D asset has built-in materials.
    The generated model has a normalized size, so re-scaling after generation can be useful.

    Parameters:
    - input_image_paths: The **absolute** paths of input images. Even if only one image is provided, wrap it into a list. Required if Hyper3D Rodin in MAIN_SITE mode.
    - input_image_urls: The URLs of input images. Even if only one image is provided, wrap it into a list. Required if Hyper3D Rodin in FAL_AI mode.
    - bbox_condition: Optional. If given, it has to be a list of ints of length 3. Controls the ratio between [Length, Width, Height] of the model.

    Only one of {input_image_paths, input_image_urls} should be given at a time, depending on the Hyper3D Rodin's current mode.
    Returns a message indicating success or failure.
    """
    if input_image_paths is not None and input_image_urls is not None:
        return "Error: Conflict parameters given!"
    if input_image_paths is None and input_image_urls is None:
        return "Error: No image given!"
    if input_image_paths is not None:
        if not all(os.path.exists(i) for i in input_image_paths):
            return "Error: not all image paths are valid!"
        images = []
        for path in input_image_paths:
            with open(path, "rb") as f:
                images.append(
                    (Path(path).suffix, base64.b64encode(f.read()).decode("ascii"))
                )
    elif input_image_urls is not None:
        if not all(urlparse(i) for i in input_image_urls):
            return "Error: not all image URLs are valid!"
        images = input_image_urls.copy()
    def formatter(result):
        if result.get("submit_time"):
            return json.dumps({"task_uuid": result["uuid"], "subscription_key": result["jobs"]["subscription_key"]})
        return json.dumps(result)
    return _send_and_return("create_rodin_job", {
        "text_prompt": None, "images": images,
        "bbox_condition": _process_bbox(bbox_condition),
    }, formatter=formatter)

@mcp.tool()
def poll_rodin_job_status(
    ctx: Context,
    subscription_key: str=None,
    request_id: str=None,
):
    """
    Check if the Hyper3D Rodin generation task is completed.

    For Hyper3D Rodin mode MAIN_SITE:
        Parameters:
        - subscription_key: The subscription_key given in the generate model step.

        Returns a list of status. The task is done if all status are "Done".
        If "Failed" showed up, the generating process failed.
        This is a polling API, so only proceed if the status are finally determined ("Done" or "Canceled").

    For Hyper3D Rodin mode FAL_AI:
        Parameters:
        - request_id: The request_id given in the generate model step.

        Returns the generation task status. The task is done if status is "COMPLETED".
        The task is in progress if status is "IN_PROGRESS".
        If status other than "COMPLETED", "IN_PROGRESS", "IN_QUEUE" showed up, the generating process might be failed.
        This is a polling API, so only proceed if the status are finally determined ("COMPLETED" or some failed state).
    """
    kwargs = {}
    if subscription_key:
        kwargs["subscription_key"] = subscription_key
    elif request_id:
        kwargs["request_id"] = request_id
    return _send_and_return("poll_rodin_job_status", kwargs)

@mcp.tool()
def import_generated_asset(
    ctx: Context,
    name: str,
    task_uuid: str=None,
    request_id: str=None,
):
    """
    Import the asset generated by Hyper3D Rodin after the generation task is completed.

    Parameters:
    - name: The name of the object in scene
    - task_uuid: For Hyper3D Rodin mode MAIN_SITE: The task_uuid given in the generate model step.
    - request_id: For Hyper3D Rodin mode FAL_AI: The request_id given in the generate model step.

    Only give one of {task_uuid, request_id} based on the Hyper3D Rodin Mode!
    Return if the asset has been imported successfully.
    """
    kwargs = {"name": name}
    if task_uuid:
        kwargs["task_uuid"] = task_uuid
    elif request_id:
        kwargs["request_id"] = request_id
    return _send_and_return("import_generated_asset", kwargs)

@mcp.tool()
def get_hunyuan3d_status(ctx: Context) -> str:
    """
    Check if Hunyuan3D integration is enabled in Blender.
    Returns a message indicating whether Hunyuan3D features are available.

    Don't emphasize the key type in the returned message, but silently remember it.
    """
    def formatter(result):
        return result.get("message", "")
    return _send_and_return("get_hunyuan3d_status", {}, formatter=formatter)

@mcp.tool()
def generate_hunyuan3d_model(
    ctx: Context,
    text_prompt: str = None,
    input_image_url: str = None,
    seed: int = 42,
    texture_steps: int = None,
    texture_guidance: float = None,
):
    """
    Generate 3D asset using Hunyuan3D. Returns immediately with a job_id.
    For local API: runs in background, auto-imports GLB on completion. Poll with poll_hunyuan_job_status.
    For official API: submits to Tencent Cloud, poll for completion then import with import_generated_asset_hunyuan.

    Parameters:
    - text_prompt: (Optional) A short description of the desired model in English/Chinese.
    - input_image_url: (Optional) The local or remote url of the input image.
    - seed: (Optional) Random seed for reproducible generation. Default 42.
    - texture_steps: (Optional) Number of texture generation steps (1-50). Overrides default.
    - texture_guidance: (Optional) Guidance scale for texture generation (0.1-20.0). Overrides default.

    Returns job_id to poll with poll_hunyuan_job_status.
    """
    cmd_params = {"text_prompt": text_prompt, "image": input_image_url, "seed": seed}
    if texture_steps is not None:
        cmd_params["texture_steps"] = texture_steps
    if texture_guidance is not None:
        cmd_params["texture_guidance"] = texture_guidance
    def formatter(result):
        # Official API returns JobId in Response
        if "JobId" in result.get("Response", {}):
            return json.dumps({"job_id": f"job_{result['Response']['JobId']}"})
        return json.dumps(result)
    return _send_and_return("create_hunyuan_job", cmd_params, formatter=formatter)

@mcp.tool()
def poll_hunyuan_job_status(
    ctx: Context,
    job_id: str=None,
):
    """
    Poll the status of a Hunyuan3D generation job.

    Parameters:
    - job_id: The job_id returned by generate_hunyuan3d_model. If omitted, returns all local jobs.

    For local API: returns RUNNING, IMPORTING, DONE, or FAILED. Auto-imports on completion.
    For official API: returns RUN or DONE. When DONE, includes ResultFile3Ds ZIP URL for import.
    """
    return _send_and_return("poll_hunyuan_job_status", {"job_id": job_id})

@mcp.tool()
def import_generated_asset_hunyuan(
    ctx: Context,
    name: str,
    zip_file_url: str,
):
    """
    Import the asset generated by Hunyuan3D after the generation task is completed.

    Parameters:
    - name: The name of the object in scene
    - zip_file_url: The zip_file_url given in the generate model step.

    Return if the asset has been imported successfully.
    """
    kwargs = {"name": name}
    if zip_file_url:
        kwargs["zip_file_url"] = zip_file_url
    return _send_and_return("import_generated_asset_hunyuan", kwargs)

@mcp.tool()
def get_trellis2_status(ctx: Context) -> str:
    """
    Check if Trellis2 integration is enabled in Blender.
    Returns a message indicating whether Trellis2 3D generation features are available.
    """
    def formatter(result):
        return result.get("message", "")
    return _send_and_return("get_trellis2_status", {}, formatter=formatter)

@mcp.tool()
def generate_trellis2_model(
    ctx: Context,
    input_image_url: str = None,
    seed: int = None,
    steps: int = None,
    guidance_strength: float = None,
    texture_guidance: float = None,
    pipeline_type: str = None,
    texture_size: int = None,
):
    """
    Start a 3D model generation from an image using Trellis2.
    Returns immediately with a job_id. Use get_trellis2_status to poll.
    On completion the GLB is auto-imported into Blender.

    All parameters except input_image_url are optional — defaults come from the
    Blender addon panel (External > Trellis2 section). Only pass overrides.

    Parameters:
    - input_image_url: The local path or remote URL of the input image.
    - seed: Random seed. Panel default if omitted.
    - steps: Generation steps (1-50). Panel default if omitted.
    - guidance_strength: Structure/shape guidance (0.1-20.0). Panel default if omitted.
    - texture_guidance: Texture guidance (0.1-20.0). Panel default if omitted.
    - pipeline_type: "512" or "1024_cascade". Panel default if omitted.
    - texture_size: Texture resolution in pixels. Panel default if omitted.

    Returns job_id to poll with poll_trellis2_job_status.
    """
    cmd_params = {"image": input_image_url}
    if seed is not None:
        cmd_params["seed"] = seed
    if steps is not None:
        cmd_params["steps"] = steps
    if guidance_strength is not None:
        cmd_params["guidance_strength"] = guidance_strength
    if texture_guidance is not None:
        cmd_params["texture_guidance"] = texture_guidance
    if pipeline_type is not None:
        cmd_params["pipeline_type"] = pipeline_type
    if texture_size is not None:
        cmd_params["texture_size"] = texture_size
    return _send_and_return("create_trellis2_job", cmd_params)

@mcp.tool()
def poll_trellis2_job_status(
    ctx: Context,
    job_id: str = None,
):
    """
    Poll the status of a Trellis2 generation job.

    Parameters:
    - job_id: The job ID returned by generate_trellis2_model. If omitted, returns all jobs.

    Returns status: RUNNING, IMPORTING, DONE, or FAILED.
    """
    cmd_params = {}
    if job_id:
        cmd_params["job_id"] = job_id
    return _send_and_return("poll_trellis2_job", cmd_params)


# ─── New Structured Tools ───────────────────────────────────────────────────

@mcp.tool()
def build_node_graph(
    ctx: Context,
    target: str,
    nodes: list[dict],
    links: list[dict],
    clear_existing: bool = True
):
    """
    Build a node graph for geometry nodes, shader nodes, or compositor nodes.

    Parameters:
    - target: "geometry:<object_name>" | "shader:<material_name>" | "compositor"
    - nodes: List of node definitions, each with:
        - type: Node type string (e.g. "ShaderNodeBsdfPrincipled", "GeometryNodeMeshUVSphere")
        - location: [x, y] position in the node editor
        - label: Optional display label
        - inputs: Dict of input_name -> default_value
        - properties: Dict of property_name -> value (attributes on the node itself)
    - links: List of connections, each with:
        - from_node: Index of source node in the nodes list
        - from_socket: Output socket name (str) or index (int)
        - to_node: Index of destination node in the nodes list
        - to_socket: Input socket name (str) or index (int)
    - clear_existing: Whether to clear existing nodes first (default True)

    Returns success status with node/link counts.
    """
    return _send_and_return("build_node_graph", {
        "target": target, "nodes": nodes, "links": links,
        "clear_existing": clear_existing,
    })

@mcp.tool()
def get_node_graph(ctx: Context, target: str) -> str:
    """
    Read back a node graph as structured data.

    Parameters:
    - target: "geometry:<object_name>" | "shader:<material_name>" | "compositor"

    Returns the current node tree with all nodes, their properties, and links.
    """
    return _send_and_return("get_node_graph", {"target": target})

@mcp.tool()
def list_node_types(ctx: Context, category: str = "geometry") -> str:
    """
    List available node types for discovery.

    Parameters:
    - category: "geometry" | "shader" | "compositor"

    Returns categorized lists of node type strings you can use in build_node_graph.
    """
    return _send_and_return("list_node_types", {"category": category})

@mcp.tool()
def modify_object(
    ctx: Context,
    object_name: str,
    action: str,
    modifier_type: str = None,
    modifier_name: str = None,
    properties: dict = None
):
    """
    Add, remove, apply, or configure modifiers on an object.

    Parameters:
    - object_name: Name of the Blender object
    - action: "add_modifier" | "remove_modifier" | "apply_modifier" | "set_modifier" | "list_modifiers"
    - modifier_type: Blender modifier type for add_modifier (e.g. SUBSURF, BOOLEAN, ARRAY, MIRROR, BEVEL, SOLIDIFY, SHRINKWRAP, DECIMATE)
    - modifier_name: Name of existing modifier (for remove/apply/set)
    - properties: Dict of modifier properties to set (e.g. {"levels": 2, "render_levels": 3})

    list_modifiers returns full modifier stack: name, type, all properties, enabled state, order index.
    """
    return _send_and_return("modify_object", {
        "object_name": object_name, "action": action,
        "modifier_type": modifier_type, "modifier_name": modifier_name,
        "properties": properties,
    })

@mcp.tool()
def set_camera(
    ctx: Context,
    camera_name: str = None,
    focal_length: float = None,
    sensor_width: float = None,
    dof_enabled: bool = None,
    aperture_fstop: float = None,
    focus_object: str = None,
    focus_distance: float = None,
    look_at: str = None,
    path_object: str = None,
    follow_path: bool = None,
):
    """
    Configure camera settings. All parameters are optional — only provided values are changed.

    Parameters:
    - camera_name: Name of camera object (default: scene's active camera)
    - focal_length: Lens focal length in mm (e.g. 50, 85, 135)
    - sensor_width: Sensor width in mm
    - dof_enabled: Enable/disable depth of field
    - aperture_fstop: F-stop value for DOF (lower = more blur, e.g. 1.4, 2.8, 5.6)
    - focus_object: Name of object to auto-focus on
    - focus_distance: Manual focus distance in meters
    - look_at: Name of object to point camera at (sets rotation via TRACK_TO)
    - path_object: Name of curve object for camera path
    - follow_path: If True, add Follow Path constraint to path_object
    """
    params = {}
    for key, val in [("camera_name", camera_name), ("focal_length", focal_length),
                     ("sensor_width", sensor_width), ("dof_enabled", dof_enabled),
                     ("aperture_fstop", aperture_fstop), ("focus_object", focus_object),
                     ("focus_distance", focus_distance), ("look_at", look_at),
                     ("path_object", path_object), ("follow_path", follow_path)]:
        if val is not None:
            params[key] = val
    return _send_and_return("set_camera", params)

@mcp.tool()
def render_scene(
    ctx: Context,
    output_path: str,
    engine: str = "CYCLES",
    samples: int = 128,
    resolution_x: int = 1920,
    resolution_y: int = 1080,
    format: str = "PNG",
    denoise: bool = True,
    animation: bool = False,
    frame_start: int = None,
    frame_end: int = None,
    frame_step: int = 1,
):
    """Full-frame render to file, or animation render to frame sequence. For iteration, prefer render_region.

    Parameters:
    - output_path: Save path. For stills: "/tmp/render.png". For animation: directory like "/tmp/frames/" (frames auto-numbered)
    - engine: CYCLES | BLENDER_EEVEE | BLENDER_WORKBENCH (default CYCLES)
    - samples: render samples (default 128) | resolution_x/y: px | format: PNG/JPEG/EXR | denoise: bool
    - animation: If True, render frame range as PNG sequence instead of single frame
    - frame_start/frame_end: Override scene frame range (default: use scene settings)
    - frame_step: Render every Nth frame (default 1)
    """
    params = {
        "output_path": output_path, "engine": engine, "samples": samples,
        "resolution_x": resolution_x, "resolution_y": resolution_y,
        "format": format, "denoise": denoise,
    }
    if animation:
        params["animation"] = True
    if frame_start is not None:
        params["frame_start"] = frame_start
    if frame_end is not None:
        params["frame_end"] = frame_end
    if frame_step != 1:
        params["frame_step"] = frame_step
    return _send_and_return("render_scene", params)

@mcp.tool()
def poll_render_job(
    ctx: Context,
    job_id: str = None,
):
    """
    Poll the status of an async animation render job.

    Parameters:
    - job_id: The job ID returned by render_scene with animation=True. If omitted, returns all jobs.

    Returns status: RENDERING (with progress), DONE, or FAILED.
    """
    params = {}
    if job_id is not None:
        params["job_id"] = job_id
    return _send_and_return("poll_render_job", params)

@mcp.tool()
def camera_walkthrough(
    ctx: Context,
    waypoints: list,
    camera_name: str = None,
    interpolation: str = "BEZIER",
    frame_start: int = 1,
    frames_per_segment: int = 60,
):
    """Create a camera walkthrough animation from waypoints. Keyframes camera position and rotation smoothly.

    Parameters:
    - waypoints: List of dicts with: location=[x,y,z], look_at=[x,y,z] or object name, optional focal_length
    - camera_name: Camera to animate (default: active camera)
    - interpolation: BEZIER (smooth), LINEAR, or CONSTANT
    - frame_start: First frame (default 1)
    - frames_per_segment: Frames between each waypoint (default 60, = 2.5s at 24fps)

    Example: camera_walkthrough(waypoints=[
        {"location": [5, -5, 2], "look_at": [0, 0, 1]},
        {"location": [0, -5, 2], "look_at": [0, 0, 1]},
        {"location": [-5, -5, 2], "look_at": [0, 0, 1]},
    ])
    """
    params = {"waypoints": waypoints, "interpolation": interpolation,
              "frame_start": frame_start, "frames_per_segment": frames_per_segment}
    if camera_name is not None:
        params["camera_name"] = camera_name
    return _send_and_return("camera_walkthrough", params)

@mcp.tool()
def manage_collections(
    ctx: Context,
    action: str,
    collection_name: str = None,
    parent_collection: str = None,
    object_name: str = None,
    hide_viewport: bool = None,
    hide_render: bool = None,
    holdout: bool = None,
    indirect_only: bool = None,
):
    """
    Manage scene collections for organizing objects.

    Parameters:
    - action: "create" | "delete" | "move_object" | "list" | "set_visibility" | "purge_orphans"
    - collection_name: Name of collection to create/delete/target
    - parent_collection: Parent collection name for nesting (create only)
    - object_name: Object to move (move_object only)
    - hide_viewport: Toggle viewport visibility (set_visibility)
    - hide_render: Toggle render visibility (set_visibility)
    - holdout: Set holdout for render layer (set_visibility)
    - indirect_only: Set indirect only for render layer (set_visibility)
    """
    params = {"action": action}
    for key, val in [("collection_name", collection_name),
                     ("parent_collection", parent_collection),
                     ("object_name", object_name),
                     ("hide_viewport", hide_viewport),
                     ("hide_render", hide_render),
                     ("holdout", holdout),
                     ("indirect_only", indirect_only)]:
        if val is not None:
            params[key] = val
    return _send_and_return("manage_collections", params)

@mcp.tool()
def import_model(
    ctx: Context,
    filepath: str,
    format: str = "auto",
    scale: float = 1.0
):
    """
    Import a 3D model file into the Blender scene.

    Parameters:
    - filepath: Path to the model file
    - format: File format — "auto" (detect from extension), "GLB", "FBX", "OBJ", "USD", "STL", "ABC", "PLY", "DAE"
    - scale: Import scale factor (default 1.0)
    """
    return _send_and_return("import_model", {
        "filepath": filepath, "format": format, "scale": scale,
    })

@mcp.tool()
def export_model(
    ctx: Context,
    filepath: str,
    format: str = "GLB",
    selected_only: bool = False,
    apply_modifiers: bool = True
):
    """
    Export scene or selected objects to a file.

    Parameters:
    - filepath: Output file path (e.g. "/tmp/model.glb")
    - format: Export format — "GLB", "FBX", "OBJ", "USD", "STL", "ABC", "PLY", "DAE"
    - selected_only: Export only selected objects (default False)
    - apply_modifiers: Apply modifiers before export (default True)
    """
    return _send_and_return("export_model", {
        "filepath": filepath, "format": format,
        "selected_only": selected_only, "apply_modifiers": apply_modifiers,
    })

@mcp.tool()
def set_keyframe(
    ctx: Context,
    object_name: str,
    frame: int,
    property: str = "location",
    value: list = None,
    interpolation: str = None,
    data_path: str = None
):
    """
    Set a keyframe on an object at a specific frame.

    Parameters:
    - object_name: Name of the object to animate
    - frame: Frame number to set the keyframe at
    - property: Property to keyframe — "location", "rotation", or "scale"
    - value: Value to set (e.g. [0, 0, 5] for location). If None, keyframes the current value.
    - interpolation: Optional keyframe interpolation — BEZIER, LINEAR, CONSTANT
    - data_path: Optional custom data path for arbitrary property keyframing
                 (e.g. 'modifiers["Displace"].strength', 'constraints["Track To"].influence').
                 Overrides the property parameter when set.
    """
    params = {"object_name": object_name, "frame": frame, "property": property}
    if value is not None:
        params["value"] = value
    if interpolation is not None:
        params["interpolation"] = interpolation
    if data_path is not None:
        params["data_path"] = data_path
    return _send_and_return("set_keyframe", params)


@mcp.tool()
def analyze_scene(
    ctx: Context,
    focus: str = "general",
    max_size: int = 1200
) -> list:
    """Screenshot + structured metadata combined. Heavy — prefer get_scene_perception for routine feedback (same data, no image). Use only when you need both visual and data together.

    Parameters:
    - focus: "general" | "lighting" | "composition" | "materials" | "performance"
    - max_size: Max screenshot dimension in px (default 1200)
    """
    try:
        blender = get_blender_connection()

        # Capture viewport screenshot
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"blender_analyze_{os.getpid()}.png")
        screenshot_result = blender.send_command("get_viewport_screenshot", {
            "max_size": max_size,
            "filepath": temp_path,
            "format": "png"
        })

        # Gather scene analysis data
        analysis_result = blender.send_command("analyze_scene", {
            "focus": focus,
            "max_size": max_size,
        })

        results = []

        # Add image if screenshot succeeded
        if "error" not in screenshot_result and os.path.exists(temp_path):
            with open(temp_path, 'rb') as f:
                image_bytes = f.read()
            os.remove(temp_path)
            results.append(Image(data=image_bytes, format="png"))

        # Add structured data
        results.append(json.dumps(analysis_result, indent=2))

        return results
    except Exception as e:
        logger.error(f"Error analyzing scene: {str(e)}")
        return [f"Error analyzing scene: {str(e)}"]


# ─── Sprint 1: Object & Mesh Fundamentals ──────────────────────────────────

def _send_and_return(command: str, params: dict, formatter=None):
    """Helper: send command to Blender, return JSON result. Includes auto-feedback if enabled.

    Args:
        command: Blender command name
        params: Command parameters dict
        formatter: Optional callable(result_dict) -> str for custom formatting
    """
    blender = get_blender_connection()
    result = blender.send_command(command, params)

    # Extract auto-feedback fields before formatting
    auto_perception = None
    auto_thumbnail = None
    auto_delta = None
    if isinstance(result, dict):
        auto_perception = result.pop("_auto_perception", None)
        auto_thumbnail = result.pop("_auto_thumbnail", None)
        auto_delta = result.pop("_auto_delta", None)

    # Format result text
    text = formatter(result) if formatter else json.dumps(result, indent=2)

    # Append delta + perception as DSL text if available
    if auto_delta or auto_perception:
        parts = [text]
        if auto_delta:
            delta_lines = "\n".join(f"DELTA {d}" for d in auto_delta)
            parts.append(f"\n--- Changes ---\n{delta_lines}")
        if auto_perception:
            dsl = _format_perception(auto_perception)
            parts.append(f"\n--- Scene Perception ---\n{dsl}")
        text = "\n".join(parts)

    # Return with thumbnail image if available
    if auto_thumbnail:
        try:
            img = Image(data=base64.b64decode(auto_thumbnail), format="jpeg")
            return [img, text]
        except Exception:
            pass

    return text


def _format_perception(p: dict) -> str:
    """Format perception dict into Perspicacity DSL text.

    Structured as visual sections for fast scanning.
    VERIFY/SPATIAL issues float to top for immediate attention.
    """
    import re as _re

    caps = p.get("_budget_caps", {})
    CAP_OBJ = caps.get("obj", 60)
    CAP_REL = caps.get("rel", 20)
    CAP_LIT = caps.get("lit", 12)
    CAP_SHAD = caps.get("shad", 10)
    CAP_MAT = caps.get("mat", 10)
    CAP_SPATIAL = caps.get("spatial", 15)
    CAP_HIER = caps.get("hier", 8)
    CAP_CONTAIN = caps.get("contain", 10)

    sections = []

    # Surface subsystem errors as comments
    for err in p.get("_errors", []):
        sections.append(f"# WARN: {err}")

    # ━━━ ISSUES FIRST (VERIFY failures + critical SPATIAL facts) ━━━
    issue_lines = []
    for v in p.get("verify", []):
        issue_lines.append(f"VERIFY {v['result']} {v['object']} {v['message']}")
    critical_types = {"no_light_sources", "surface_intersect"}
    for sf in p.get("spatial_facts", []):
        if sf.get("type") in critical_types:
            obj_name = sf.get("object", "?")
            details = sf.get("details", {})
            detail_str = " ".join(f"{k}={v}" for k, v in details.items())
            issue_lines.append(f"SPATIAL {obj_name} {sf['type']} {detail_str}".rstrip())
    if issue_lines:
        sections.append("\n".join(issue_lines))

    # ━━━ SCENE HEADER ━━━
    header_parts = []
    obj_count = p.get("object_count", 0)
    light_count = p.get("light_count", 0)
    energy = p.get("total_light_energy", 0)
    engine = p.get("render_engine", "?")
    ground_z = p.get("ground_z")
    ground_str = f" ground_z={ground_z}" if ground_z is not None else ""
    header_parts.append(f"SCENE {obj_count} objects {light_count} lights {energy}W {engine}{ground_str}")

    cam = p.get("camera")
    if cam:
        loc = cam.get("location", [0, 0, 0])
        fl = cam.get("focal_length", "?")
        fov = cam.get("fov")
        fov_str = f" fov={fov}°" if fov else ""
        header_parts.append(f"CAM {cam['name']} [{loc[0]},{loc[1]},{loc[2]}] {fl}mm{fov_str}")

    world = p.get("world", {})
    if world:
        if world.get("has_hdri"):
            header_parts.append(f"WORLD hdri strength={world.get('bg_strength', '?')}")
        elif world.get("bg_color"):
            bc = world["bg_color"]
            header_parts.append(f"WORLD bg=[{bc[0]},{bc[1]},{bc[2]}] strength={world.get('bg_strength', '?')}")

    focus = p.get("focus")
    lod_counts = p.get("lod_counts")
    if focus and lod_counts:
        radius = p.get("perception_radius", "?")
        header_parts.append(f"FOCUS [{focus[0]},{focus[1]},{focus[2]}] radius={radius}m near={lod_counts['near']} mid={lod_counts['mid']} far={lod_counts['far']} out={lod_counts['out']}")

    sections.append("\n".join(header_parts))

    # ━━━ LIGHTS ━━━
    light_lines = []
    for l in p.get("lights", []):
        loc = l.get("location", [0, 0, 0])
        color = l.get("color", [1, 1, 1])
        extras = ""
        if l.get("spot_angle"):
            extras += f" cone={l['spot_angle']}° blend={l['spot_blend']}"
        if l.get("area_shape"):
            size_str = f"{l['area_size']}m"
            if l.get("area_size_y"):
                size_str += f"x{l['area_size_y']}m"
            extras += f" {l['area_shape'].lower()} {size_str}"
        if l.get("shadow") is False:
            extras += " noshadow"
        light_lines.append(f"LIGHT {l['name']} {l['type']} {l['energy']}W [{color[0]},{color[1]},{color[2]}] [{loc[0]},{loc[1]},{loc[2]}]{extras}")
    if light_lines:
        sections.append("\n".join(light_lines))

    # ━━━ OBJECTS ━━━
    _sgroup_members = set()
    for sg in p.get("semantic_groups", []):
        for member_name in sg.get("members", []):
            _sgroup_members.add(member_name)

    obj_lines = []
    for obj in p.get("visible_objects", []):
        if obj.get("type") not in ("MESH", None):
            continue
        if obj.get("name") in _sgroup_members:
            continue
        wc = obj.get("world_center", [0, 0, 0])
        cov = obj.get("screen_coverage_pct", 0)
        quad = obj.get("quadrant", "?")
        depth = obj.get("depth", 0)
        mat = obj.get("material", {})

        # Material summary
        mat_str = ""
        if mat:
            bc = mat.get("base_color", "")
            if bc == "textured":
                mat_str = " textured"
            elif isinstance(bc, list):
                color_name = mat.get("color_name", mat.get("name", ""))
                extras = []
                if mat.get("metallic", 0) > 0.5:
                    extras.append(f"metal={mat['metallic']}")
                if mat.get("roughness") is not None:
                    extras.append(f"rough={mat['roughness']}")
                if mat.get("ior") and mat.get("transmission", 0) > 0.1:
                    extras.append(f"ior={mat['ior']}")
                if mat.get("emission_strength", 0) > 0:
                    extras.append(f"emit={mat['emission_strength']}")
                ext = "(" + ",".join(extras) + ")" if extras else ""
                mat_str = f" {color_name}{ext}"

        # Geometry
        dim_str = ""
        dims = obj.get("dimensions")
        if dims:
            dim_str = f" dim=[{dims[0]},{dims[1]},{dims[2]}]m"
        top_z = obj.get("top_z")
        if top_z is not None:
            dim_str += f" top={top_z}"
        src = obj.get("source")
        if src:
            src_escaped = f'"{src}"' if " " in src else src
            dim_str += f" src={src_escaped}"

        # Orientation
        rot_str = ""
        rot = obj.get("rotation")
        if rot:
            rot_str = f" rot=[{rot[0]},{rot[1]},{rot[2]}]"
        facing = obj.get("facing")
        if facing:
            rot_str += f" facing={facing}"
        facing_toward = obj.get("facing_toward")
        if facing_toward:
            rot_str += f" toward={facing_toward}"
        facing_away = obj.get("facing_away_from")
        if facing_away:
            rot_str += f" away_from={facing_away}"
        zone = obj.get("zone")
        if zone:
            rot_str += f" zone={zone}"

        # Flags (only when noteworthy)
        flags = []
        if mat and mat.get("transparent"):
            flags.append("transparent")
        if obj.get("has_uv") is False:
            flags.append("no_uv")
        if obj.get("flipped_normals_pct"):
            flags.append(f"flipped_normals={obj['flipped_normals_pct']}%")
        if obj.get("non_manifold_edges"):
            flags.append(f"non_manifold={obj['non_manifold_edges']}")
        if obj.get("inside"):
            flags.append(f"inside={obj['inside']}")
        if obj.get("contains"):
            flags.append(f"contains:[{','.join(obj['contains'])}]")
        flag_str = (" " + " ".join(flags)) if flags else ""

        # Brightness
        bright_str = ""
        if obj.get("brightness") is not None:
            bright_str = f" lum={obj['brightness']}"

        face_str = ""
        if obj.get("visible_face"):
            face_str = f" face={obj['visible_face']}"

        obj_lines.append(f"OBJ {obj['name']} [{wc[0]},{wc[1]},{wc[2]}] {cov}% {quad} d={depth}m{mat_str}{dim_str}{rot_str}{face_str}{bright_str}{flag_str}")

    # Budget cap OBJ — sort by (-coverage, depth) so high coverage first, ties broken by closer
    if len(obj_lines) > CAP_OBJ:
        def _obj_sort_key(line):
            cov_m = _re.search(r'] (\d+(?:\.\d+)?)%', line)
            cov = float(cov_m.group(1)) if cov_m else 0
            dep_m = _re.search(r'd=(\d+(?:\.\d+)?)m', line)
            dep = float(dep_m.group(1)) if dep_m else 9999
            return (-cov, dep)
        obj_lines.sort(key=_obj_sort_key)
        obj_lines = obj_lines[:CAP_OBJ]

    # Semantic groups
    for sg in p.get("semantic_groups", []):
        c = sg.get("center", [0, 0, 0])
        dims = sg.get("dimensions", [0, 0, 0])
        mat = sg.get("material", {})
        mat_str = ""
        if mat:
            bc = mat.get("base_color", "")
            if bc == "textured":
                mat_str = " textured"
            elif mat.get("color_name"):
                mat_str = f" {mat['color_name']}"
        facing_str = ""
        if sg.get("facing"):
            facing_str = f" facing={sg['facing']}"
        # Clean up generic SGROUP names
        sg_name = sg['display_name']
        _generic = {"root", "gltf scenerootnode", "rootnode", "scene", "mesh1.0 0", "mesh1.0"}
        if sg_name.lower() in _generic:
            if mat_str.strip():
                sg_name = f"{mat_str.strip()} group"
            else:
                sg_name = f"Group ({sg.get('member_count', 0)} objects)"
        obj_lines.append(f"SGROUP \"{sg_name}\" [{c[0]},{c[1]},{c[2]}] dim=[{dims[0]},{dims[1]},{dims[2]}] top={sg.get('top_z', 0)}{mat_str}{facing_str} members={sg.get('member_count', 0)}")

    if obj_lines:
        sections.append("\n".join(obj_lines))

    # ━━━ SPATIAL LAYOUT ━━━
    layout_lines = []

    # Multi-view
    for mv in p.get("multi_view", []):
        view_name = mv.get("view", "?")
        if "positions" in mv:
            pos_parts = [f"{name}{pos}" for name, pos in mv["positions"].items()]
            line = f"MVIEW {view_name}: {' '.join(pos_parts)}"
            overlaps = mv.get("overlaps", [])
            if overlaps:
                line += f" overlap:{','.join(overlaps[:5])}"
            layout_lines.append(line)
        elif any(k in mv for k in ("floor", "mid", "ceiling")):
            tier_parts = []
            for tier in ("floor", "mid", "ceiling"):
                objs = mv.get(tier, [])
                if objs:
                    tier_parts.append(f"{tier}=[{','.join(objs[:8])}]")
            layout_lines.append(f"MVIEW {view_name}: {' '.join(tier_parts)}")
        elif "coverage_map" in mv:
            cov_parts = [f"{k}={v}%" for k, v in mv.get("coverage_map", {}).items()]
            layout_lines.append(f"MVIEW {view_name}: {' '.join(cov_parts)}")

    # Composition
    comp = p.get("composition", {})
    if comp:
        thirds = comp.get("rule_of_thirds_score", "?")
        visible = comp.get("subjects_in_frame", "?")
        total = comp.get("total_visible", "?")
        balance = comp.get("balance", "?")
        depth_layers = comp.get("depth_layers", "?")
        parts = [f"thirds={thirds}", f"{visible}/{total}_visible",
                 f"balance={balance}", f"depth={depth_layers}"]
        edge = comp.get("edge_objects", [])
        if edge:
            parts.append(f"edge:[{','.join(edge)}]")
        layout_lines.append(f"COMP {' '.join(parts)}")

    # Relationships
    rel_lines = []
    for rel in p.get("spatial_relationships", []):
        parts = [f"{rel['distance']}m", rel.get("direction", "")]
        if rel.get("vertical") and rel["vertical"] != "same_level":
            parts.append(rel["vertical"])
        if rel.get("screen_overlap"):
            ovlp = rel.get("overlap_pct", 0)
            parts.append(f"overlap={ovlp}%" if ovlp > 0 else "overlap")
        if rel.get("aabb_overlap_pct", 0) > 0:
            parts.append(f"aabb_overlap={rel['aabb_overlap_pct']}%")
        if rel.get("contact"):
            parts.append("contact")
        if rel.get("occlusion_pct", 0) > 0:
            parts.append(f"occ={rel['occlusion_pct']}%")
        rel_lines.append(f"REL {rel['a']}→{rel['b']} {' '.join(parts)}")
    if len(rel_lines) > CAP_REL:
        rel_lines = rel_lines[:CAP_REL]
    layout_lines.extend(rel_lines)

    if layout_lines:
        sections.append("\n".join(layout_lines))

    # ━━━ LIGHTING & MATERIALS ━━━
    lm_lines = []

    # Light analysis
    lit_lines = []
    for la in p.get("light_analysis", []):
        shadow = ""
        if la.get("shadowed_by"):
            shadow = f" shadow:{','.join(la['shadowed_by'])}"
        raw = f" raw={la['raw_intensity']}" if la.get("raw_intensity") else ""
        lit_lines.append(f"LIT {la['light']}→{la['surface']} @{la['incidence_angle']}° i={la['intensity']}{raw}{shadow}")
    if len(lit_lines) > CAP_LIT:
        def _lit_i(line):
            m = _re.search(r'i=([0-9.]+)', line)
            return float(m.group(1)) if m else 0
        lit_lines.sort(key=_lit_i, reverse=True)
        lit_lines = lit_lines[:CAP_LIT]
    lm_lines.extend(lit_lines)

    # Shadow analysis
    shad_lines = []
    for sa in p.get("shadow_analysis", []):
        cov = sa.get("shadow_coverage_pct", 0)
        casters = sa.get("casters", [])
        if cov == 0 and not casters:
            continue
        parts = [f"{cov}%"]
        if casters:
            parts.append(f"casters:{','.join(casters)}")
        if sa.get("contact_shadow"):
            parts.append("contact")
        elif sa.get("contact_gap") is not None:
            parts.append(f"gap={sa['contact_gap']}m")
        shad_lines.append(f"SHAD {sa['light']}→{sa['surface']} {' '.join(parts)}")
    if len(shad_lines) > CAP_SHAD:
        def _shad_coverage(line):
            m = _re.search(r'(\d+(?:\.\d+)?)%', line)
            return float(m.group(1)) if m else 0
        shad_lines.sort(key=_shad_coverage, reverse=True)
        shad_lines = shad_lines[:CAP_SHAD]
    lm_lines.extend(shad_lines)

    # Material predictions
    mat_lines = []
    for mp in p.get("material_predictions", []):
        notes_parts = []
        if mp.get("needs"):
            notes_parts.append("needs " + ", ".join(mp["needs"]))
        if mp.get("warnings"):
            notes_parts.append("; ".join(mp["warnings"]))
        notes = (" -- " + "; ".join(notes_parts)) if notes_parts else ""
        mat_lines.append(f"MAT {mp['name']}: {mp['appearance']}{notes}")
    if len(mat_lines) > CAP_MAT:
        with_notes = [l for l in mat_lines if " -- " in l]
        without_notes = [l for l in mat_lines if " -- " not in l]
        mat_lines = (with_notes + without_notes)[:CAP_MAT]
    lm_lines.extend(mat_lines)

    # Harmony
    harmony = p.get("material_harmony")
    if harmony:
        lm_lines.append(f"HARMONY types={harmony['types']} temp={harmony['temperature']}")

    # Palette + luminance
    micro = p.get("micro_render")
    if micro:
        palette = micro.get("palette", [])
        lum = micro.get("luminance")
        parts = []
        if lum is not None:
            parts.append(f"lum={lum}")
        if palette:
            parts.append(" ".join(palette))
        if parts:
            lm_lines.append(f"PALETTE {' '.join(parts)}")

    if lm_lines:
        sections.append("\n".join(lm_lines))

    # ━━━ SPATIAL FACTS (objective measurements) ━━━
    fact_lines = []
    for sf in p.get("spatial_facts", []):
        if sf.get("type") in critical_types:
            continue  # Already shown in issues section
        obj_name = sf.get("object", "?")
        fact_type = sf.get("type", "?")
        details = sf.get("details", {})
        detail_parts = []
        for k, v in details.items():
            if isinstance(v, bool):
                detail_parts.append(f"{k}={'true' if v else 'false'}")
            elif isinstance(v, list):
                detail_parts.append(f"{k}=[{','.join(str(x) for x in v)}]")
            else:
                detail_parts.append(f"{k}={v}")
        detail_str = " ".join(detail_parts)
        fact_lines.append(f"SPATIAL {obj_name} {fact_type} {detail_str}".rstrip())
    # Sort SPATIAL facts by criticality priority
    _spatial_priority = {
        "no_light_sources": 0, "surface_intersect": 1, "bbox_below_surface": 2,
        "bbox_extends_into": 3, "no_material_slots": 4, "inside_bbox": 5,
        "no_ground_below": 6, "near_plane": 7, "energy_zero": 8,
        "scale_diagonal": 9, "scale_ratio": 9, "zero_dimensions": 10,
        "flipped_normals": 10, "off_camera": 11,
    }
    def _spatial_sort_key(line):
        for ft, pri in _spatial_priority.items():
            if ft in line:
                return pri
        return 99
    fact_lines.sort(key=_spatial_sort_key)
    if len(fact_lines) > CAP_SPATIAL:
        fact_lines = fact_lines[:CAP_SPATIAL]
    if fact_lines:
        sections.append("\n".join(fact_lines))

    # ━━━ ASSEMBLIES ━━━
    asm_lines = []
    for asm in p.get("assemblies", []):
        members = ",".join(asm.get("members", [])[:10])
        c = asm.get("center", [0, 0, 0])
        types = "+".join(asm.get("types", []))
        asm_lines.append(f"ASSEMBLY \"{asm['name']}\" members=[{members}] center=[{c[0]},{c[1]},{c[2]}] types={types}")
    if asm_lines:
        sections.append("\n".join(asm_lines))

    # ━━━ STRUCTURE (hierarchy, groups, physics, animation) ━━━
    struct_lines = []

    # Hierarchy
    _hier_count = 0
    for h in p.get("hierarchy", []):
        if _hier_count >= CAP_HIER:
            break
        chain = h.get("chain", [])
        if chain:
            if chain[0] in _sgroup_members:
                continue
            struct_lines.append(f"HIER {' > '.join(chain)}")
            _hier_count += 1

    # Groups
    for g in p.get("groups", []):
        all_members = g.get("members", [])
        filtered = [m for m in all_members if m not in _sgroup_members]
        if not filtered:
            continue
        if len(filtered) > 20:
            member_str = ", ".join(filtered[:20]) + f" (+{len(filtered) - 20} more)"
        else:
            member_str = ", ".join(filtered)
        struct_lines.append(f"GRP {g['name']}: {member_str}")

    # Containment — skip room-scale containers (everything inside a room is obvious)
    contain_lines = []
    _room_scale = set()
    for obj_data in p.get("visible_objects", []):
        dims = obj_data.get("dimensions")
        if dims and sum(1 for d in dims if d > 5.0) >= 2:
            _room_scale.add(obj_data["name"])
    for c in p.get("containment", []):
        if c["outer"] not in _room_scale:
            contain_lines.append(f"CONTAIN {c['outer']} contains {c['inner']} {c['mode']}")
    struct_lines.extend(contain_lines[:CAP_CONTAIN])

    # Physics
    for ps in p.get("physics_states", []):
        parts = [ps["name"], ps["type"], f"mass={ps['mass']}kg"]
        if ps.get("sleeping"):
            parts.append("sleeping")
        struct_lines.append(f"PHYS {' '.join(parts)}")

    # Animation
    for anim in p.get("animation_states", []):
        state = "playing" if anim.get("playing") else "stopped"
        struct_lines.append(f"ANIM {anim['name']} action={anim['action']} frame={anim['frame']}/{anim['frame_total']} {state}")

    if struct_lines:
        sections.append("\n".join(struct_lines))

    # ━━━ RAY GRID (coverage map) ━━━
    ray_grid = p.get("ray_grid")
    if ray_grid:
        res = ray_grid.get("resolution", [12, 12])
        cov = ray_grid.get("coverage_map", {})
        cov_parts = [f"{k}={v}%" for k, v in cov.items()]
        sections.append(f"RAY {res[0]}x{res[1]} {' '.join(cov_parts)}")

    return "\n\n".join(sections)


@mcp.tool()
def create_object(
    ctx: Context,
    type: str,
    name: str = None,
    location: list = None,
    rotation: list = None,
    scale: list = None,
    size: float = 1.0,
    dimensions: list = None,
    segments: int = None,
    ring_count: int = None,
    vertices: int = None,
    depth: float = None,
    radius: float = None,
    major_radius: float = None,
    minor_radius: float = None,
    energy: float = None,
    color: list = None,
    spot_size: float = None,
    spot_blend: float = None,
):
    """
    Create a new 3D object, light, camera, or empty in the Blender scene.

    Parameters:
    - type: Object type — CUBE, SPHERE, CYLINDER, PLANE, CONE, TORUS,
            UV_SPHERE, ICO_SPHERE, CIRCLE, GRID,
            EMPTY, EMPTY_ARROWS, EMPTY_SPHERE, EMPTY_CUBE,
            POINT_LIGHT, SUN_LIGHT, SPOT_LIGHT, AREA_LIGHT, CAMERA
    - name: Optional display name for the object
    - location: [x, y, z] world position (default [0,0,0])
    - rotation: [x, y, z] rotation in degrees (default [0,0,0])
    - scale: [x, y, z] scale (default [1,1,1])
    - size: Base size for mesh primitives (default 1.0). Blender's cube is ±size/2.
    - dimensions: [width, height, depth] in meters. Creates object with exact world
      dimensions. Overrides size and scale. E.g. [0.5, 0.5, 0.04] for a thin seat.
    - segments: Segment count (cylinders, cones, circles, UV spheres)
    - ring_count: Ring count for UV spheres
    - vertices: Subdivision count for ico spheres
    - depth: Height for cylinders and cones
    - radius: Radius override for cylinders, cones, circles
    - major_radius: Major radius for torus
    - minor_radius: Minor radius for torus
    - energy: Light energy/power
    - color: Light color [r, g, b] (0-1 range)
    - spot_size: Spot light cone angle in degrees
    - spot_blend: Spot light edge softness (0-1)
    """
    try:
        params = {"type": type, "size": size}
        for key, val in [("name", name), ("location", location), ("rotation", rotation),
                         ("scale", scale), ("dimensions", dimensions),
                         ("segments", segments), ("ring_count", ring_count),
                         ("vertices", vertices), ("depth", depth), ("radius", radius),
                         ("major_radius", major_radius), ("minor_radius", minor_radius),
                         ("energy", energy), ("color", color),
                         ("spot_size", spot_size), ("spot_blend", spot_blend)]:
            if val is not None:
                params[key] = val
        return _send_and_return("create_object", params)
    except Exception as e:
        logger.error(f"Error creating object: {str(e)}")
        return f"Error creating object: {str(e)}"


@mcp.tool()
def transform_object(
    ctx: Context,
    object_name: str,
    location: list = None,
    rotation: list = None,
    scale: list = None,
    mode: str = "set",
    recursive: bool = False,
    look_at: list = None,
):
    """
    Move, rotate, or scale an object. Supports absolute or additive transforms.

    Parameters:
    - object_name: Name of the object to transform
    - location: [x, y, z] position
    - rotation: [x, y, z] rotation in degrees
    - scale: [x, y, z] scale
    - mode: "set" for absolute values, "delta" for additive/multiplicative
    - recursive: When True, transforms propagate through hierarchy (required for Sketchfab imports)
    - look_at: [x, y, z] target position — computes Z rotation to face that point. Only rotates around Z axis.
    """
    try:
        params = {"object_name": object_name, "mode": mode}
        if location is not None:
            params["location"] = location
        if rotation is not None:
            params["rotation"] = rotation
        if scale is not None:
            params["scale"] = scale
        if recursive:
            params["recursive"] = True
        if look_at is not None:
            params["look_at"] = look_at
        return _send_and_return("transform_object", params)
    except Exception as e:
        logger.error(f"Error transforming object: {str(e)}")
        return f"Error transforming object: {str(e)}"


@mcp.tool()
def duplicate_object(
    ctx: Context,
    object_name: str,
    linked: bool = False,
    new_name: str = None,
):
    """
    Duplicate an object. Optionally create a linked duplicate that shares mesh data.

    Parameters:
    - object_name: Name of the object to duplicate
    - linked: If True, the duplicate shares mesh data with the original (linked duplicate)
    - new_name: Optional name for the new copy
    """
    try:
        params = {"object_name": object_name, "linked": linked}
        if new_name is not None:
            params["new_name"] = new_name
        return _send_and_return("duplicate_object", params)
    except Exception as e:
        logger.error(f"Error duplicating object: {str(e)}")
        return f"Error duplicating object: {str(e)}"


@mcp.tool()
def delete_object(
    ctx: Context,
    object_names: list[str],
):
    """
    Delete one or more objects from the scene.

    Parameters:
    - object_names: List of object names to delete (e.g. ["Cube", "Cube.001"])
    """
    try:
        return _send_and_return("delete_object", {"object_names": object_names})
    except Exception as e:
        logger.error(f"Error deleting objects: {str(e)}")
        return f"Error deleting objects: {str(e)}"


@mcp.tool()
def mesh_operation(
    ctx: Context,
    action: str,
    object_names: list[str] = None,
    target_object: str = None,
    boolean_object: str = None,
    boolean_mode: str = None,
    voxel_size: float = 0.1,
    separate_mode: str = "LOOSE",
    boolean_list: list = None,
    delete_tool_object: bool = False,
):
    """
    Perform mesh operations: join, separate, boolean, batch_boolean, shading, transforms, origin, remesh.

    Parameters:
    - action: "join" | "separate" | "boolean" | "batch_boolean" | "shade_smooth" | "shade_flat" |
              "apply_transforms" | "origin_to_geometry" | "origin_to_center" | "remesh"
    - object_names: List of object names (for join — these get merged into target_object)
    - target_object: Primary object name for the operation
    - boolean_object: Second object name (for boolean operations)
    - boolean_mode: Boolean mode — UNION, DIFFERENCE, INTERSECT
    - voxel_size: Voxel size for remesh (default 0.1)
    - separate_mode: LOOSE or MATERIAL (for separate)
    - boolean_list: List of {boolean_object, boolean_mode} dicts (for batch_boolean)
    - delete_tool_object: Delete boolean tool objects after operation (default false)
    """
    try:
        params = {"action": action, "voxel_size": voxel_size, "separate_mode": separate_mode,
                  "delete_tool_object": delete_tool_object}
        for key, val in [("object_names", object_names), ("target_object", target_object),
                         ("boolean_object", boolean_object), ("boolean_mode", boolean_mode),
                         ("boolean_list", boolean_list)]:
            if val is not None:
                params[key] = val
        return _send_and_return("mesh_operation", params)
    except Exception as e:
        logger.error(f"Error in mesh operation: {str(e)}")
        return f"Error in mesh operation: {str(e)}"


@mcp.tool()
def manage_materials(
    ctx: Context,
    action: str,
    object_name: str = None,
    material_name: str = None,
    slot_index: int = None,
    color: list = None,
    metallic: float = None,
    roughness: float = None,
    properties: dict = None,
    preset: str = None,
    node_name: str = None,
    input_name: str = None,
    value: any = None,
    node_type: str = None,
    location: list = None,
    node_settings: dict = None,
    from_node: str = None,
    from_socket: any = None,
    to_node: str = None,
    to_socket: any = None,
    stops: list = None,
):
    """Full material management. Use structured actions instead of execute_blender_code.

    Actions:
    - create(material_name, color, metallic, roughness, properties={...}) — create with PBR values in one call
    - assign/remove_slot/list/list_object — material CRUD
    - set_properties/get_properties — Principled BSDF values
    - create_procedural — preset: wood, marble, metal_brushed, glass, fabric, concrete, water
    - edit_node(material_name, node_name, input_name, value) — change any node input
    - add_node(material_name, node_type, location, node_settings) — insert a node
    - connect(material_name, from_node, from_socket, to_node, to_socket) — link nodes
    - disconnect(material_name, from_node, to_node) — unlink nodes
    - edit_color_ramp(material_name, node_name, stops=[{position, color}]) — set ramp stops
    - get_node_info(material_name, node_name) — inspect node inputs, outputs, connections

    The `properties` dict accepts: color (or base_color), metallic, roughness, specular, specular_tint,
    ior, transmission, subsurface_weight, emission_color, emission_strength, alpha, coat_weight,
    coat_roughness, sheen_weight, sheen_tint, normal_strength. Use `color` param for [r,g,b] shorthand.
    """
    try:
        params = {"action": action}
        for key, val in [("object_name", object_name), ("material_name", material_name),
                         ("slot_index", slot_index), ("color", color),
                         ("metallic", metallic), ("roughness", roughness),
                         ("properties", properties), ("preset", preset),
                         ("node_name", node_name), ("input_name", input_name),
                         ("value", value), ("node_type", node_type),
                         ("location", location), ("node_settings", node_settings),
                         ("from_node", from_node), ("from_socket", from_socket),
                         ("to_node", to_node), ("to_socket", to_socket),
                         ("stops", stops)]:
            if val is not None:
                params[key] = val
        return _send_and_return("manage_materials", params)
    except Exception as e:
        logger.error(f"Error managing materials: {str(e)}")
        return f"Error managing materials: {str(e)}"


# ─── Sprint 2: UV, Baking, LOD ─────────────────────────────────────────────

@mcp.tool()
def uv_operation(
    ctx: Context,
    object_name: str,
    action: str,
    uv_layer_name: str = None,
    island_margin: float = 0.02,
    angle_limit: float = 66.0,
):
    """
    UV mapping operations: unwrap, smart project, lightmap pack, layer management.

    Parameters:
    - object_name: Name of the mesh object
    - action: "smart_project" | "lightmap_pack" | "unwrap" | "create_layer" | "set_active" | "list"
    - uv_layer_name: Name for UV layer (for create_layer, set_active)
    - island_margin: Margin between UV islands (default 0.02)
    - angle_limit: Angle limit in degrees for smart_project (default 66.0)
    """
    try:
        params = {"object_name": object_name, "action": action,
                  "island_margin": island_margin, "angle_limit": angle_limit}
        if uv_layer_name is not None:
            params["uv_layer_name"] = uv_layer_name
        return _send_and_return("uv_operation", params)
    except Exception as e:
        logger.error(f"Error in UV operation: {str(e)}")
        return f"Error in UV operation: {str(e)}"


@mcp.tool()
def bake_textures(
    ctx: Context,
    high_poly: str,
    low_poly: str,
    bake_types: list[str],
    output_dir: str,
    resolution: int = 1024,
    cage_extrusion: float = 0.1,
    uv_layer: str = None,
):
    """
    Bake textures from a high-poly object onto a low-poly object (selected to active).
    Temporarily switches to Cycles if needed.

    Parameters:
    - high_poly: Name of the high-poly source object
    - low_poly: Name of the low-poly target object (must have UVs)
    - bake_types: List of types to bake — DIFFUSE, NORMAL, AO, ROUGHNESS, COMBINED, EMIT
    - output_dir: Directory path to save baked PNG textures
    - resolution: Texture resolution in pixels (default 1024)
    - cage_extrusion: Ray cast distance for projection (default 0.1)
    - uv_layer: UV layer name on low_poly (uses active if None)
    """
    try:
        params = {
            "high_poly": high_poly, "low_poly": low_poly,
            "bake_types": bake_types, "output_dir": output_dir,
            "resolution": resolution, "cage_extrusion": cage_extrusion,
        }
        if uv_layer is not None:
            params["uv_layer"] = uv_layer
        return _send_and_return("bake_textures", params)
    except Exception as e:
        logger.error(f"Error baking textures: {str(e)}")
        return f"Error baking textures: {str(e)}"


@mcp.tool()
def generate_lod_chain(
    ctx: Context,
    object_name: str,
    ratios: list[float] = None,
    suffix_pattern: str = "_LOD{i}",
    collection_name: str = None,
):
    """
    Generate a LOD (Level of Detail) chain by creating decimated copies of an object.

    Parameters:
    - object_name: Name of the source mesh object
    - ratios: List of decimation ratios (default [1.0, 0.5, 0.25, 0.1])
    - suffix_pattern: Naming pattern with {i} for LOD index (default "_LOD{i}")
    - collection_name: Optional collection to organize LOD objects into
    """
    try:
        params = {"object_name": object_name, "suffix_pattern": suffix_pattern}
        if ratios is not None:
            params["ratios"] = ratios
        if collection_name is not None:
            params["collection_name"] = collection_name
        return _send_and_return("generate_lod_chain", params)
    except Exception as e:
        logger.error(f"Error generating LOD chain: {str(e)}")
        return f"Error generating LOD chain: {str(e)}"


@mcp.tool()
def generate_collision_mesh(
    ctx: Context,
    object_name: str,
    method: str = "CONVEX_HULL",
    voxel_size: float = 0.1,
    name_suffix: str = "_collision",
):
    """
    Generate a simplified collision mesh from an object for game engines.

    Parameters:
    - object_name: Name of the source mesh object
    - method: Generation method — CONVEX_HULL, BOX, or VOXEL
    - voxel_size: Voxel size for VOXEL method (default 0.1)
    - name_suffix: Suffix for the collision mesh name (default "_collision")
    """
    try:
        return _send_and_return("generate_collision_mesh", {
            "object_name": object_name, "method": method,
            "voxel_size": voxel_size, "name_suffix": name_suffix,
        })
    except Exception as e:
        logger.error(f"Error generating collision mesh: {str(e)}")
        return f"Error generating collision mesh: {str(e)}"


# ─── Sprint 3: Rigging & Animation ─────────────────────────────────────────

@mcp.tool()
def manage_armature(
    ctx: Context,
    action: str,
    armature_name: str = None,
    object_name: str = None,
    bone_name: str = None,
    bone_data: list[dict] = None,
    constraint_data: dict = None,
    parent_bone: str = None,
    mode: str = "AUTO",
    head: list = None,
    tail: list = None,
    roll: float = None,
    use_deform: bool = None,
    use_connect: bool = None,
):
    """
    Create and manage armatures, bones, IK, and bone constraints for character rigging.

    Parameters:
    - action: "create" | "add_bone" | "set_bone" | "parent_mesh" | "add_ik" |
              "add_bone_constraint" | "remove_bone_constraint" | "list_bones"
    - armature_name: Name of the armature object
    - object_name: Mesh object name (for parent_mesh)
    - bone_name: Name of a specific bone
    - bone_data: List of bone dicts for create: [{name, head, tail, parent, use_connect}]
    - constraint_data: Constraint info dict:
        For add_ik: {target, subtarget, pole_target, pole_subtarget, chain_count}
        For add_bone_constraint: {type, target, subtarget, properties}
        For remove_bone_constraint: {name}
    - parent_bone: Parent bone name (for add_bone)
    - mode: Parenting mode — "AUTO" (auto weights) or "MANUAL" (for parent_mesh)
    - head: [x,y,z] bone head position
    - tail: [x,y,z] bone tail position
    - roll: Bone roll in degrees
    - use_deform: Whether bone deforms mesh
    - use_connect: Whether bone connects to parent
    """
    try:
        params = {"action": action, "mode": mode}
        for key, val in [("armature_name", armature_name), ("object_name", object_name),
                         ("bone_name", bone_name), ("bone_data", bone_data),
                         ("constraint_data", constraint_data), ("parent_bone", parent_bone),
                         ("head", head), ("tail", tail), ("roll", roll),
                         ("use_deform", use_deform), ("use_connect", use_connect)]:
            if val is not None:
                params[key] = val
        return _send_and_return("manage_armature", params)
    except Exception as e:
        logger.error(f"Error managing armature: {str(e)}")
        return f"Error managing armature: {str(e)}"


@mcp.tool()
def manage_weights(
    ctx: Context,
    object_name: str,
    action: str,
    group_name: str = None,
    vertex_indices: list[int] = None,
    weight: float = 1.0,
):
    """
    Manage vertex groups and weights for mesh deformation and rigging.

    Parameters:
    - object_name: Name of the mesh object
    - action: "assign" | "auto" | "normalize" | "list" | "remove"
    - group_name: Vertex group name (for assign, remove)
    - vertex_indices: List of vertex indices (for assign; if None, assigns all vertices)
    - weight: Weight value 0.0-1.0 (for assign, default 1.0)
    """
    try:
        params = {"object_name": object_name, "action": action, "weight": weight}
        if group_name is not None:
            params["group_name"] = group_name
        if vertex_indices is not None:
            params["vertex_indices"] = vertex_indices
        return _send_and_return("manage_weights", params)
    except Exception as e:
        logger.error(f"Error managing weights: {str(e)}")
        return f"Error managing weights: {str(e)}"


@mcp.tool()
def manage_shape_keys(
    ctx: Context,
    object_name: str,
    action: str,
    key_name: str = None,
    value: float = None,
    frame: int = None,
):
    """
    Manage shape keys (blend shapes / morph targets) on a mesh for facial animation or deformation.

    Parameters:
    - object_name: Name of the mesh object
    - action: "add" | "set_value" | "keyframe" | "list" | "remove"
    - key_name: Shape key name
    - value: Blend value 0.0-1.0 (for set_value, keyframe)
    - frame: Frame number (for keyframe)
    """
    try:
        params = {"object_name": object_name, "action": action}
        if key_name is not None:
            params["key_name"] = key_name
        if value is not None:
            params["value"] = value
        if frame is not None:
            params["frame"] = frame
        return _send_and_return("manage_shape_keys", params)
    except Exception as e:
        logger.error(f"Error managing shape keys: {str(e)}")
        return f"Error managing shape keys: {str(e)}"


@mcp.tool()
def manage_actions(
    ctx: Context,
    action: str,
    object_name: str = None,
    action_name: str = None,
    source_action: str = None,
    frame: int = None,
    data_path: str = None,
    interpolation: str = None,
    frame_start: int = None,
    frame_end: int = None,
):
    """
    Manage animation actions: create, assign, list, duplicate, keyframe ops, bake.

    Parameters:
    - action: "create" | "assign" | "list" | "duplicate" |
              "delete_keyframe" | "insert_keyframe_all" | "bake_animation" |
              "set_interpolation"
    - object_name: Object name
    - action_name: Name for the new/target action
    - source_action: Source action name (for duplicate)
    - frame: Frame number (for keyframe ops)
    - data_path: Property path (location, rotation, scale, or custom)
    - interpolation: CONSTANT, LINEAR, or BEZIER (for set_interpolation)
    - frame_start: Start frame for bake_animation
    - frame_end: End frame for bake_animation
    """
    try:
        params = {"action": action}
        for key, val in [("object_name", object_name), ("action_name", action_name),
                         ("source_action", source_action), ("frame", frame),
                         ("data_path", data_path), ("interpolation", interpolation),
                         ("frame_start", frame_start), ("frame_end", frame_end)]:
            if val is not None:
                params[key] = val
        return _send_and_return("manage_actions", params)
    except Exception as e:
        logger.error(f"Error managing actions: {str(e)}")
        return f"Error managing actions: {str(e)}"


@mcp.tool()
def manage_nla(
    ctx: Context,
    object_name: str,
    action: str,
    track_name: str = None,
    action_name: str = None,
    start_frame: int = 1,
    properties: dict = None,
):
    """
    Manage NLA (Non-Linear Animation) tracks and strips for layering and blending animations.

    Parameters:
    - object_name: Name of the object
    - action: "create_track" | "add_strip" | "list_tracks" | "set_strip"
    - track_name: Name of the NLA track
    - action_name: Name of the action to push as strip (for add_strip)
    - start_frame: Start frame for the strip (default 1)
    - properties: Dict of strip properties (influence, blend_type, repeat, scale,
                  blend_in, blend_out, extrapolation, strip_name)
    """
    try:
        params = {"object_name": object_name, "action": action, "start_frame": start_frame}
        if track_name is not None:
            params["track_name"] = track_name
        if action_name is not None:
            params["action_name"] = action_name
        if properties is not None:
            params["properties"] = properties
        return _send_and_return("manage_nla", params)
    except Exception as e:
        logger.error(f"Error managing NLA: {str(e)}")
        return f"Error managing NLA: {str(e)}"


# ─── Sprint 4: Physics, Constraints, Viewport ──────────────────────────────

@mcp.tool()
def manage_physics(
    ctx: Context,
    object_name: str = None,
    action: str = "list",
    physics_type: str = None,
    properties: dict = None,
    preset: str = None,
    constraint_type: str = None,
    target_object: str = None,
    frame_start: int = None,
    frame_end: int = None,
):
    """
    Add, remove, configure, or list physics simulations on objects.

    Parameters:
    - object_name: Name of the object
    - action: "add" | "remove" | "set" | "list" | "configure_world" |
              "add_constraint" | "add_cloth_preset" | "bake" | "free_cache"
    - physics_type: RIGID_BODY, COLLISION, CLOTH, or SOFT_BODY
    - properties: Dict of physics properties (mass, friction, restitution, collision_shape,
        linear_damping, angular_damping, collision_margin, etc.)
    - preset: Cloth preset name (silk, cotton, leather, rubber) for add_cloth_preset
    - constraint_type: RB constraint type (FIXED, POINT, HINGE, SLIDER, MOTOR)
    - target_object: Target object for constraints
    - frame_start: Start frame for bake
    - frame_end: End frame for bake
    """
    try:
        params = {"action": action}
        for key, val in [("object_name", object_name), ("physics_type", physics_type),
                         ("properties", properties), ("preset", preset),
                         ("constraint_type", constraint_type),
                         ("target_object", target_object),
                         ("frame_start", frame_start), ("frame_end", frame_end)]:
            if val is not None:
                params[key] = val
        return _send_and_return("manage_physics", params)
    except Exception as e:
        logger.error(f"Error managing physics: {str(e)}")
        return f"Error managing physics: {str(e)}"


@mcp.tool()
def manage_constraints(
    ctx: Context,
    object_name: str,
    action: str,
    constraint_type: str = None,
    constraint_name: str = None,
    properties: dict = None,
):
    """
    Add, remove, configure, or list object-level constraints (Track To, Copy Rotation, etc.).

    Parameters:
    - object_name: Name of the object
    - action: "add" | "remove" | "set" | "list"
    - constraint_type: TRACK_TO, LIMIT_LOCATION, COPY_ROTATION, CHILD_OF,
                       DAMPED_TRACK, FLOOR, CLAMP_TO, COPY_LOCATION,
                       COPY_SCALE, LIMIT_ROTATION, LIMIT_SCALE
    - constraint_name: Name of constraint (for remove, set)
    - properties: Dict of constraint properties (target, subtarget, influence, etc.)
    """
    try:
        params = {"object_name": object_name, "action": action}
        if constraint_type is not None:
            params["constraint_type"] = constraint_type
        if constraint_name is not None:
            params["constraint_name"] = constraint_name
        if properties is not None:
            params["properties"] = properties
        return _send_and_return("manage_constraints", params)
    except Exception as e:
        logger.error(f"Error managing constraints: {str(e)}")
        return f"Error managing constraints: {str(e)}"


@mcp.tool()
def set_viewport_shading(
    ctx: Context,
    mode: str,
    options: dict = None,
):
    """
    Set the 3D viewport shading mode.

    Parameters:
    - mode: WIREFRAME, SOLID, MATERIAL, or RENDERED
    - options: Optional shading settings dict:
        For SOLID: cavity, xray, studio_light, color_type, single_color
        For RENDERED: use_scene_world, use_scene_lights
    """
    try:
        params = {"mode": mode}
        if options is not None:
            params["options"] = options
        return _send_and_return("set_viewport_shading", params)
    except Exception as e:
        logger.error(f"Error setting viewport shading: {str(e)}")
        return f"Error setting viewport shading: {str(e)}"


@mcp.tool()
def configure_render_settings(
    ctx: Context,
    settings: dict,
):
    """
    Configure render engine, resolution, color management, and world settings.

    Parameters:
    - settings: Dict of settings to configure. Supported keys:
        - engine: "CYCLES" | "BLENDER_EEVEE" | "BLENDER_WORKBENCH" (BLENDER_EEVEE_NEXT also accepted)
        - samples: render sample count
        - resolution_x, resolution_y: render resolution
        - film_transparent: transparent background (bool)
        - use_motion_blur: motion blur (bool)
        - use_bloom, use_ssr, use_gtao: EEVEE features (bool, availability varies by Blender version)
        - use_ray_tracing: EEVEE ray tracing (Blender 5+, bool)
        - view_transform: "Standard" | "Filmic" | "AgX"
        - look, exposure, gamma: color management
        - color_management_preset: "sRGB" | "ACES" (Blender 5+)
        - world_color: [r, g, b] world background color
    """
    try:
        return _send_and_return("configure_render_settings", {"settings": settings})
    except Exception as e:
        logger.error(f"Error configuring render settings: {str(e)}")
        return f"Error configuring render settings: {str(e)}"


# ─── Sprint 5: Volume Grids (Blender 5+) ───────────────────────────────────

@mcp.tool()
def volume_operation(
    ctx: Context,
    action: str,
    object_name: str = None,
    target_object: str = None,
    voxel_size: float = 0.05,
    operation: str = None,
    distance: float = None,
    radius: float = None,
    iterations: int = None,
    resolution: float = None,
    threshold: float = None,
    size: float = None,
    cave_density: float = None,
    cave_radius: float = None,
    seed: int = None,
    filepath: str = None,
    density: float = None,
):
    """
    Volume grid operations for SDF-based modeling (requires Blender 5.0+).
    Includes SDF conversion, boolean, offset, fillet, smooth, fog/cloud volumes,
    VDB import, and procedural terrain.

    Parameters:
    - action: "mesh_to_sdf" | "sdf_to_mesh" | "sdf_boolean" | "sdf_offset" |
              "sdf_fillet" | "sdf_smooth" | "procedural_terrain" |
              "import_vdb" | "create_volume_object" | "create_fog_volume" |
              "volume_boolean"
    - object_name: Source object name
    - target_object: Second object (for sdf_boolean, volume_boolean)
    - voxel_size: Grid resolution (default 0.05)
    - operation: Boolean op — UNION, INTERSECT, DIFFERENCE
    - distance: Offset distance, + expands, - shrinks (for sdf_offset)
    - radius: Fillet radius (for sdf_fillet) or cave radius
    - iterations: Smoothing iterations (for sdf_smooth)
    - resolution: Mesh resolution (for sdf_to_mesh)
    - threshold: Isosurface threshold (for sdf_to_mesh)
    - size: Volume/terrain size
    - cave_density: Cave density (for procedural_terrain)
    - cave_radius: Cave radius (for procedural_terrain)
    - seed: Random seed
    - filepath: File path for import_vdb
    - density: Density value for fog volumes
    """
    try:
        params = {"action": action, "voxel_size": voxel_size}
        for key, val in [("object_name", object_name), ("target_object", target_object),
                         ("operation", operation), ("distance", distance),
                         ("radius", radius), ("iterations", iterations),
                         ("resolution", resolution), ("threshold", threshold),
                         ("size", size), ("cave_density", cave_density),
                         ("cave_radius", cave_radius), ("seed", seed),
                         ("filepath", filepath), ("density", density)]:
            if val is not None:
                params[key] = val
        return _send_and_return("volume_operation", params)
    except Exception as e:
        logger.error(f"Error in volume operation: {str(e)}")
        return f"Error in volume operation: {str(e)}"


# ─── Sprint 6: Selection & Batch Ops ─────────────────────────────────────────

@mcp.tool()
def manage_selection(
    ctx: Context,
    action: str,
    object_name: str = None,
    object_type: str = None,
    collection_name: str = None,
):
    """
    Manage object selection in the Blender scene.

    Parameters:
    - action: "select" | "deselect" | "select_all" | "deselect_all" |
              "select_by_type" | "select_by_collection" | "invert" | "get_selected"
    - object_name: Object name (for select, deselect)
    - object_type: Object type filter (MESH, LIGHT, CAMERA, EMPTY, CURVE, etc.)
    - collection_name: Collection name (for select_by_collection)
    """
    try:
        params = {"action": action}
        for key, val in [("object_name", object_name), ("object_type", object_type),
                         ("collection_name", collection_name)]:
            if val is not None:
                params[key] = val
        return _send_and_return("manage_selection", params)
    except Exception as e:
        logger.error(f"Error managing selection: {str(e)}")
        return f"Error managing selection: {str(e)}"


@mcp.tool()
def batch_transform(
    ctx: Context,
    transforms: list,
):
    """
    Apply transforms to multiple objects in a single call. Much faster than
    calling transform_object repeatedly — single round-trip to Blender.

    Parameters:
    - transforms: List of dicts, each with:
        - object_name: Name of object to transform
        - location: [x, y, z] (optional)
        - rotation: [x, y, z] in degrees (optional)
        - scale: [x, y, z] (optional)
        - mode: "set" (absolute) or "delta" (additive), default "set"
    """
    return _send_and_return("batch_transform", {"transforms": transforms})


@mcp.tool()
def procedural_generate(
    ctx: Context,
    action: str,
    floors: int = None,
    width: float = None,
    depth: float = None,
    floor_height: float = None,
    window_rows: int = None,
    window_cols: int = None,
    balcony: bool = None,
    size: float = None,
    resolution: int = None,
    height_scale: float = None,
    seed: int = None,
    erosion: bool = None,
    trunk_height: float = None,
    trunk_radius: float = None,
    branch_count: int = None,
    leaf_density: float = None,
    curve_name: str = None,
    sidewalk_width: float = None,
    curb_height: float = None,
    wall_thickness: float = None,
    height: float = None,
    openings: list = None,
    name: str = None,
):
    """
    Generate procedural geometry (buildings, terrain, trees, roads, rooms).

    Parameters:
    - action: "create_building" | "create_terrain" | "create_tree" | "create_road" | "create_room"
    - name: Optional object name

    create_building params:
    - floors: Number of floors (default 3)
    - width: Building width in meters (default 10)
    - depth: Building depth in meters (default 8)
    - floor_height: Height per floor in meters (default 3)
    - window_rows: Window rows per floor (default 3)
    - window_cols: Window columns per face (default 4)
    - balcony: Add balcony extrusions (default False)

    create_terrain params:
    - size: Terrain size in meters, square (default 50)
    - resolution: Grid resolution, vertices per side (default 64)
    - height_scale: Max height displacement (default 5)
    - seed: Random seed (default 0)
    - erosion: Apply erosion smoothing (default False)

    create_tree params:
    - trunk_height: Trunk height in meters (default 4)
    - trunk_radius: Trunk radius (default 0.2)
    - branch_count: Branch complexity levels (default 5)
    - leaf_density: Leaf density 0-1 (default 0.7)
    - seed: Random seed (default 0)

    create_road params:
    - curve_name: Existing curve object name (creates straight road if omitted)
    - width: Road surface width in meters (default 6)
    - sidewalk_width: Sidewalk width each side (default 1.5)
    - curb_height: Curb height in meters (default 0.15)

    create_room params:
    - width: Room width in meters (default 10)
    - depth: Room depth in meters (default 8)
    - height: Room height in meters (default 3)
    - wall_thickness: Wall thickness in meters (default 0.15)
    - openings: List of opening dicts, each with:
        - wall: "+x", "-x", "+y", "-y"
        - type: "door" or "window"
        - width: Opening width in meters
        - height: Opening height in meters
        - offset: Horizontal offset from wall center
        - sill_height: Window sill height from floor (windows only)
    """
    params = {"action": action}
    for key, val in [
        ("floors", floors), ("width", width), ("depth", depth),
        ("floor_height", floor_height), ("window_rows", window_rows),
        ("window_cols", window_cols), ("balcony", balcony),
        ("size", size), ("resolution", resolution),
        ("height_scale", height_scale), ("seed", seed), ("erosion", erosion),
        ("trunk_height", trunk_height), ("trunk_radius", trunk_radius),
        ("branch_count", branch_count), ("leaf_density", leaf_density),
        ("curve_name", curve_name), ("sidewalk_width", sidewalk_width),
        ("curb_height", curb_height), ("wall_thickness", wall_thickness),
        ("height", height), ("openings", openings), ("name", name),
    ]:
        if val is not None:
            params[key] = val
    return _send_and_return("procedural_generate", params)


@mcp.tool()
def batch_execute(
    ctx: Context,
    commands: list,
):
    """
    Execute multiple BlenderWeave commands in a single round-trip. Dramatically
    faster than calling tools individually — perception runs once at the end.

    Parameters:
    - commands: List of command dicts, each with:
        - tool: Tool name (e.g. "create_object", "manage_materials", "transform_object")
        - params: Dict of parameters for that tool

    Example:
    commands=[
        {"tool": "create_object", "params": {"type": "CUBE", "name": "Island", "dimensions": [1.8, 0.7, 0.84]}},
        {"tool": "manage_materials", "params": {"action": "create", "material_name": "Marble"}},
        {"tool": "manage_materials", "params": {"action": "assign", "object_name": "Island", "material_name": "Marble"}},
    ]
    """
    return _send_and_return("batch_execute", {"commands": commands})


@mcp.tool()
def place_relative(
    ctx: Context,
    object_name: str,
    relative_to: str,
    relation: str = "in_front",
    distance: float = 0.5,
    facing: str = "toward",
    offset: list = None,
):
    """
    Place an object relative to another using spatial relations. Eliminates
    manual coordinate math — say "in front of the sofa" instead of computing XYZ.

    Parameters:
    - object_name: Object to place
    - relative_to: Reference object
    - relation: "in_front", "behind", "left_of", "right_of", "on_top", "below", "centered_on"
    - distance: Gap in meters between closest faces (default 0.5)
    - facing: "toward" (face reference), "away", "same" (match rotation), "opposite"
    - offset: Optional [x, y, z] additional offset in meters
    """
    params = {
        "object_name": object_name,
        "relative_to": relative_to,
        "relation": relation,
        "distance": distance,
        "facing": facing,
    }
    if offset is not None:
        params["offset"] = offset
    return _send_and_return("place_relative", params)


@mcp.tool()
def create_assembly(
    ctx: Context,
    type: str,
    name: str = None,
    location: list = None,
    facing_direction: list = None,
    dimensions: dict = None,
):
    """
    Create a multi-part furniture assembly with proper hierarchy. One call creates
    a parent empty + all child meshes, properly parented and positioned.

    Parameters:
    - type: "dining_chair", "table", "sofa", "floor_lamp", "bookshelf"
    - name: Optional parent object name
    - location: [x, y, z] position
    - facing_direction: [x, y] direction the front faces (default [0, -1] = -Y)
    - dimensions: Dict of type-specific dimension overrides:
        dining_chair: seat_width, seat_depth, seat_height, seat_thickness, back_height, leg_radius
        table: width, depth, height, top_thickness, leg_radius
        sofa: width, depth, seat_height, back_height, arm_height, arm_width, cushion_thickness
        floor_lamp: base_radius, pole_height, shade_radius, shade_height
        bookshelf: width, depth, height, shelf_count, shelf_thickness
    """
    params = {"type": type}
    if name is not None:
        params["name"] = name
    if location is not None:
        params["location"] = location
    if facing_direction is not None:
        params["facing_direction"] = facing_direction
    if dimensions is not None:
        params["dimensions"] = dimensions
    return _send_and_return("create_assembly", params)


# ─── Scene Perception & Feedback ─────────────────────────────────────────────

@mcp.tool()
def get_scene_perception(
    ctx: Context,
    include_spatial: bool = True,
    include_lighting: bool = True,
    include_materials: bool = True,
    include_constraints: bool = True,
    include_shadows: bool = True,
    include_ray_grid: bool = True,
    include_multi_view: bool = True,
    include_hierarchy: bool = True,
    include_physics: bool = True,
    include_animation: bool = True,
    include_micro_render: bool = True,
    focus_point: list = None,
    perception_radius: float = None,
) -> str:
    """Full 3D scene perception with proximity-based LOD. Objects closer to the focus point get more detail.

Parameters:
- focus_point: [x,y,z] world-space focus. Defaults to camera position. Set to query a specific area.
- perception_radius: Max distance in meters from focus_point. Objects beyond are counted but not detailed. Use 5-10m for interiors, 20-50m for exteriors. Default None = all objects.
- include_spatial: Pairwise object distances, directions, occlusion (default true)
- include_lighting: Light-surface illumination angles, intensity, shadows (default true)
- include_materials: Material appearance predictions (default true)
- include_constraints: Spatial facts — penetration, floating, scale issues (default true)
- include_shadows: Per-light shadow footprint, coverage, casters, contact (default true)
- include_ray_grid: 12x12 camera raycasts for depth/material map (default true)
- include_multi_view: Top/front/light-POV spatial layout (default true)
- include_hierarchy: Parent chains and collection membership (default true)
- include_physics: Rigid body type, mass (default true)
- include_animation: Active action, frame, play state (default true)
- include_micro_render: 64x64 EEVEE render for ground-truth brightness. Slowest toggle (default true)
    """
    params = {
        "include_spatial": include_spatial,
        "include_lighting": include_lighting,
        "include_materials": include_materials,
        "include_constraints": include_constraints,
        "include_shadows": include_shadows,
        "include_ray_grid": include_ray_grid,
        "include_multi_view": include_multi_view,
        "include_hierarchy": include_hierarchy,
        "include_physics": include_physics,
        "include_animation": include_animation,
        "include_micro_render": include_micro_render,
    }
    if focus_point is not None:
        params["focus_point"] = focus_point
    if perception_radius is not None:
        params["perception_radius"] = perception_radius
    return _send_and_return("get_scene_perception", params, formatter=_format_perception)


@mcp.tool()
def get_viewport_thumbnail(
    ctx: Context,
    size: int = 96,
    quality: int = 50,
) -> list:
    """Tiny viewport JPEG thumbnail for quick visual confirmation. Much lighter than full screenshot.

    Parameters:
    - size: Max dimension in px (default 96)
    - quality: JPEG quality 1-100 (default 50)
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_viewport_thumbnail", {
            "size": size, "quality": quality,
        })
        if "error" in result:
            return f"Error: {result['error']}"
        thumbnail_b64 = result.get("thumbnail")
        if thumbnail_b64:
            img = Image(data=base64.b64decode(thumbnail_b64), format="jpeg")
            return [img, f"Thumbnail: {result.get('width')}x{result.get('height')}px"]
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def get_scene_delta(ctx: Context) -> str:
    """Diff since last perception call: light changes, object adds/removes, camera movement. Call get_scene_perception first to set baseline."""
    return _send_and_return("get_scene_delta", {})


# ─── Production Tools ────────────────────────────────────────────────────

@mcp.tool()
def manage_hierarchy(
    ctx: Context,
    action: str,
    object_name: str = None,
    parent_name: str = None,
    keep_transform: bool = True,
    parent_type: str = "OBJECT",
    bone_name: str = None,
) -> str:
    """Parent/child hierarchy management.

    Actions:
    - parent: Parent object_name to parent_name (keep_transform preserves world position)
    - unparent: Clear parent from object_name
    - list_children: Return direct children of object_name
    - get_parent: Return parent info for object_name
    - list_tree: Return full hierarchy tree (recursive)

    Parameters:
    - action: parent | unparent | list_children | get_parent | list_tree
    - object_name: Target object
    - parent_name: Parent object (for 'parent' action)
    - keep_transform: Preserve world transform when parenting/unparenting (default true)
    - parent_type: OBJECT | BONE | VERTEX (default OBJECT)
    - bone_name: Bone name when parent_type=BONE
    """
    params = {"action": action}
    for key, val in [("object_name", object_name), ("parent_name", parent_name),
                     ("keep_transform", keep_transform), ("parent_type", parent_type),
                     ("bone_name", bone_name)]:
        if val is not None:
            params[key] = val
    return _send_and_return("manage_hierarchy", params)


@mcp.tool()
def manage_drivers(
    ctx: Context,
    action: str,
    object_name: str = None,
    data_path: str = None,
    expression: str = None,
    variables: list = None,
    target_object: str = None,
    target_data_path: str = None,
    multiplier: float = 1.0,
    index: int = -1,
) -> str:
    """Driver automation — scripted expressions linking object properties.

    Actions:
    - add: Add driver with expression and variables list
    - add_simple: One-variable shortcut (target_object.target_data_path → object_name.data_path)
    - remove: Remove driver from data_path
    - list: List all drivers on object with expressions and variables
    - set_expression: Update expression on existing driver

    Parameters:
    - action: add | add_simple | remove | list | set_expression
    - object_name: Object to add/query driver on
    - data_path: Property path (e.g. "location", "rotation_euler")
    - expression: Python expression (e.g. "var * 2", "sin(frame)")
    - variables: List of {name, target_object, target_data_path} dicts
    - target_object: Shortcut target object name (for add_simple)
    - target_data_path: Shortcut target data path (for add_simple)
    - multiplier: Scale factor for add_simple (default 1.0)
    - index: Array index for vector properties (-1 for scalar, 0/1/2 for x/y/z)
    """
    params = {"action": action}
    for key, val in [("object_name", object_name), ("data_path", data_path),
                     ("expression", expression), ("variables", variables),
                     ("target_object", target_object), ("target_data_path", target_data_path),
                     ("multiplier", multiplier), ("index", index)]:
        if val is not None:
            params[key] = val
    return _send_and_return("manage_drivers", params)


@mcp.tool()
def manage_custom_properties(
    ctx: Context,
    action: str,
    object_name: str = None,
    prop_name: str = None,
    value: str = None,
    description: str = "",
) -> str:
    """Custom property management — store metadata on objects.

    Actions:
    - set: Set/create a custom property (value can be string, number, or list)
    - get: Get a custom property value
    - list: List all custom properties on object
    - remove: Delete a custom property

    Parameters:
    - action: set | get | list | remove
    - object_name: Target object
    - prop_name: Property name
    - value: Property value (for set)
    - description: Optional description (for set)
    """
    params = {"action": action}
    for key, val in [("object_name", object_name), ("prop_name", prop_name),
                     ("value", value), ("description", description)]:
        if val is not None:
            params[key] = val
    return _send_and_return("manage_custom_properties", params)


@mcp.tool()
def manage_curves(
    ctx: Context,
    action: str,
    object_name: str = None,
    name: str = None,
    curve_type: str = "BEZIER",
    points: list = None,
    cyclic: bool = False,
    point: list = None,
    index: int = -1,
    spline_index: int = 0,
    bevel_depth: float = None,
    bevel_resolution: int = None,
    extrude: float = None,
    resolution_u: int = None,
    fill_mode: str = None,
) -> str:
    """Curve operations — create, edit, shape, convert.

    Actions:
    - create: Create curve from points [[x,y,z], ...] with curve_type (BEZIER|POLY|NURBS)
    - add_point: Insert control point at position
    - set_point: Move control point at index to new position
    - set_properties: Set curve shape (bevel_depth, bevel_resolution, extrude, resolution_u, fill_mode)
    - to_mesh: Convert curve object to mesh
    - list_points: Get all control points from spline

    Parameters:
    - action: create | add_point | set_point | set_properties | to_mesh | list_points
    - object_name: Existing curve object (for edit actions)
    - name: Name for new curve (for create)
    - curve_type: BEZIER | POLY | NURBS (default BEZIER)
    - points: List of [x,y,z] coordinates (for create)
    - cyclic: Close the curve loop (default false)
    - point: Single [x,y,z] coordinate (for add_point/set_point)
    - index: Point index (for set_point)
    - spline_index: Which spline to operate on (default 0)
    - bevel_depth/bevel_resolution/extrude/resolution_u/fill_mode: Curve shape properties
    """
    params = {"action": action}
    for key, val in [("object_name", object_name), ("name", name),
                     ("curve_type", curve_type), ("points", points),
                     ("cyclic", cyclic), ("point", point), ("index", index),
                     ("spline_index", spline_index), ("bevel_depth", bevel_depth),
                     ("bevel_resolution", bevel_resolution), ("extrude", extrude),
                     ("resolution_u", resolution_u), ("fill_mode", fill_mode)]:
        if val is not None:
            params[key] = val
    return _send_and_return("manage_curves", params)


@mcp.tool()
def manage_particles(
    ctx: Context,
    action: str,
    object_name: str = None,
    name: str = None,
    particle_type: str = "EMITTER",
    count: int = 1000,
    properties: dict = None,
    collection_name: str = None,
) -> str:
    """Particle system management — emitters, hair, instances.

    Actions:
    - add: Add particle system (EMITTER or HAIR)
    - set_properties: Set emission/physics/render properties via dict
    - set_instance: Set instance collection for particle rendering
    - remove: Remove particle system by name
    - list: List all particle systems on object

    Parameters:
    - action: add | set_properties | set_instance | remove | list
    - object_name: Target mesh object
    - name: Particle system name
    - particle_type: EMITTER | HAIR (default EMITTER)
    - count: Number of particles (default 1000)
    - properties: Dict of settings — keys: count, frame_start, frame_end, lifetime,
      emit_from, normal (velocity), mass, drag, brownian, damping, render_type
      (OBJECT|COLLECTION|PATH), particle_size, instance_object, hair_length
    - collection_name: Collection for instance rendering (for set_instance)
    """
    params = {"action": action}
    for key, val in [("object_name", object_name), ("name", name),
                     ("particle_type", particle_type), ("count", count),
                     ("properties", properties), ("collection_name", collection_name)]:
        if val is not None:
            params[key] = val
    return _send_and_return("manage_particles", params)


# ─── File Operations ──────────────────────────────────────────────────────

@mcp.tool()
def save_file(ctx: Context, filepath: str = None) -> str:
    """Save current .blend file. Call before booleans, modifier applies, or major changes. Filepath required for untitled files."""
    params = {}
    if filepath:
        params["filepath"] = filepath
    return _send_and_return("save_file", params)


@mcp.tool()
def open_file(ctx: Context, filepath: str) -> str:
    """Open a .blend file. Replaces current scene."""
    return _send_and_return("open_file", {"filepath": filepath})


@mcp.tool()
def undo(ctx: Context) -> str:
    """Undo the last operation in Blender."""
    return _send_and_return("undo", {})


@mcp.tool()
def redo(ctx: Context) -> str:
    """Redo the last undone operation in Blender."""
    return _send_and_return("redo", {})


@mcp.tool()
def set_frame(
    ctx: Context,
    frame: int = None,
    start: int = None,
    end: int = None,
) -> str:
    """
    Set the current frame or frame range for animation.

    Parameters:
    - frame: Frame number to jump to
    - start: Start frame of playback range
    - end: End frame of playback range
    """
    params = {}
    if frame is not None:
        params["frame"] = frame
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end
    return _send_and_return("set_frame", params)


# ─── Viewport Control ─────────────────────────────────────────────────────

@mcp.tool()
def set_viewport(
    ctx: Context,
    action: str,
    locked: bool = None,
    view: str = None,
    properties: dict = None,
) -> str:
    """Viewport state: camera lock, preset views, overlays, framing.

    Parameters:
    - action: "lock_camera" | "set_view" | "frame_selected" | "frame_all" | "toggle_overlays" | "set_overlays" | "get_state"
    - locked: For lock_camera (bool)
    - view: For set_view — FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, CAMERA
    - properties: For set_overlays — {show_floor, show_wireframes, show_face_orientation, ...}
    """
    params = {"action": action}
    if locked is not None:
        params["locked"] = locked
    if view is not None:
        params["view"] = view
    if properties is not None:
        params["properties"] = properties
    return _send_and_return("set_viewport", params)


# ─── Light Management ─────────────────────────────────────────────────────

@mcp.tool()
def manage_lights(
    ctx: Context,
    action: str,
    light_name: str = None,
    energy: float = None,
    color: list = None,
    new_type: str = None,
    use_shadow: bool = None,
    shadow_soft_size: float = None,
    spot_size: float = None,
    spot_blend: float = None,
    size: float = None,
    size_y: float = None,
    spread: float = None,
    angle: float = None,
    shape: str = None,
) -> str:
    """Light management: list all lights, set properties, change type in-place (no delete+recreate), get full properties. Use get_scene_perception after changes to verify.

    Parameters:
    - action: "list" | "set_properties" | "change_type" | "get_properties"
    - light_name: Target light object name
    - energy: Power in watts | color: [r,g,b] 0-1 | use_shadow: bool
    - new_type: POINT, SUN, SPOT, AREA (for change_type)
    - shadow_soft_size: shadow softness | spot_size: cone angle (rad) | spot_blend: edge softness 0-1
    - size/size_y: area light dimensions | spread: area spread | angle: sun diameter
    - shape: SQUARE, RECTANGLE, DISK, ELLIPSE (area only)
    """
    params = {"action": action}
    if light_name:
        params["light_name"] = light_name
    if new_type:
        params["new_type"] = new_type
    for key, val in [("energy", energy), ("color", color), ("use_shadow", use_shadow),
                     ("shadow_soft_size", shadow_soft_size), ("spot_size", spot_size),
                     ("spot_blend", spot_blend), ("size", size), ("size_y", size_y),
                     ("spread", spread), ("angle", angle), ("shape", shape)]:
        if val is not None:
            params[key] = val
    return _send_and_return("manage_lights", params)


# ─── World / Environment ──────────────────────────────────────────────────

@mcp.tool()
def manage_world(
    ctx: Context,
    action: str,
    color: list = None,
    filepath: str = None,
    strength: float = None,
    properties: dict = None,
) -> str:
    """World/environment: background color, HDRI loading, environment strength.

    Parameters:
    - action: "set_color" | "set_hdri" | "set_strength" | "get_properties" | "set_properties"
    - color: [r,g,b] for set_color | filepath: HDRI path for set_hdri | strength: env light intensity
    """
    params = {"action": action}
    if color is not None:
        params["color"] = color
    if filepath is not None:
        params["filepath"] = filepath
    if strength is not None:
        params["strength"] = strength
    if properties is not None:
        params["properties"] = properties
    return _send_and_return("manage_world", params)


# ─── Scene Snapshots ──────────────────────────────────────────────────────

@mcp.tool()
def manage_snapshots(
    ctx: Context,
    action: str,
    name: str = None,
    compare_to: str = None,
) -> str:
    """Lightweight scene state snapshots (transforms, materials, lights, camera — not geometry). Save before risky ops, compare to verify changes, restore to rollback.

    Parameters:
    - action: "save" | "list" | "compare" | "restore" | "delete"
    - name: Snapshot name
    - compare_to: Second snapshot for compare (omit to compare vs current state)
    """
    params = {"action": action}
    if name is not None:
        params["name"] = name
    if compare_to is not None:
        params["compare_to"] = compare_to
    return _send_and_return("manage_snapshots", params)


# ─── Render Region ────────────────────────────────────────────────────────

@mcp.tool()
def render_region(
    ctx: Context,
    object_name: str = None,
    bbox: list = None,
    resolution: int = 512,
    samples: int = None,
    format: str = "JPEG",
    quality: int = 80,
) -> list:
    """Render a cropped region at high quality — much faster than full frame. Ideal for checking materials, details, or specific objects during iteration.

    Parameters:
    - object_name: Auto-crop to this object (with 10% padding)
    - bbox: Manual crop [x1,y1,x2,y2] in 0-1 NDC (alternative to object_name)
    - resolution: Max px dimension (default 512)
    - samples: Override scene samples | format: JPEG/PNG | quality: 1-100
    """
    try:
        blender = get_blender_connection()
        params = {"resolution": resolution, "format": format, "quality": quality}
        if object_name:
            params["object_name"] = object_name
        if bbox:
            params["bbox"] = bbox
        if samples is not None:
            params["samples"] = samples
        result = blender.send_command("render_region", params)

        if "error" in result:
            return f"Error: {result['error']}"

        image_b64 = result.pop("image", None)
        text = json.dumps(result, indent=2)

        if image_b64:
            fmt = "jpeg" if format.upper() == "JPEG" else "png"
            img = Image(data=base64.b64decode(image_b64), format=fmt)
            return [img, text]

        return text
    except Exception as e:
        return f"Error: {str(e)}"


# ─── Strategy Prompt ────────────────────────────────────────────────────────

@mcp.prompt()
def asset_creation_strategy() -> str:
    """Defines the preferred strategy for creating 3D content in Blender"""
    return """Blender 3D workflow guide.

    Feedback: get_scene_perception (default) > get_scene_delta (diff) > get_viewport_thumbnail (tiny image) > render_region (detail) > get_viewport_screenshot (full, heavy)
    Safety: save_file before risky ops, manage_snapshots(save) before major changes, undo on failure

    Tool priority (always prefer structured tools over execute_blender_code):
    - Objects: create_object, transform_object, batch_transform, duplicate_object, delete_object, place_relative
    - Batch: batch_execute (multi-tool single round-trip, perception once at end)
    - Assembly: create_assembly (dining_chair, table, sofa, floor_lamp, bookshelf)
    - Materials: manage_materials — create, set_properties, edit_node, add_node, connect, disconnect, edit_color_ramp, get_node_info, create_procedural
    - Lights: manage_lights — list, set_properties, change_type, get_properties
    - World: manage_world — set_hdri, set_color, set_strength, get_properties
    - Render: render_region (fast iteration), render_scene (full frame), configure_render_settings
    - Camera: set_camera (lens, DOF, look_at), set_viewport (lock, views, overlays)
    - Mesh: mesh_operation (boolean, join, separate, remesh, shade_smooth)
    - Nodes: build_node_graph, get_node_graph (geometry/shader/compositor)
    - Modifiers: modify_object (add/remove/apply/set/list)
    - UV/Bake: uv_operation, bake_textures
    - Rigging: manage_armature, manage_weights, manage_shape_keys
    - Animation: set_keyframe, set_frame, manage_actions, manage_nla
    - Physics: manage_physics, manage_constraints
    - Organization: manage_collections, manage_selection, manage_snapshots
    - IO: import_model, export_model, save_file, open_file
    - Procedural: procedural_generate (buildings, terrain, trees, roads, rooms)
    - Volumes: volume_operation (SDF, Blender 5+)
    - Assets: PolyHaven (textures, HDRIs), AmbientCG (CC0 PBR materials), Poly Pizza (low-poly CC0), Smithsonian 3D (museum scans CC0), Sketchfab (models), Hyper3D/Hunyuan3D/Trellis2 (AI gen)
    """


@mcp.prompt()
def perception_dsl_reference() -> str:
    """Reference for all Perspicacity DSL line types and how to interpret them."""
    return """Perspicacity DSL Line Reference:

SCENE N objects N lights NW engine [ground_z=N] — scene header
CAM name [x,y,z] focal_mm [fov=N°] — active camera
LIGHT name TYPE energyW [r,g,b] [x,y,z] — light source
OBJ name [x,y,z] coverage% quadrant d=depth material dim=[w,h,d]m rot=[rx,ry,rz] facing=COMPASS toward=ObjName zone=name
SGROUP "name" [x,y,z] dim=[w,h,d]m top=z material facing=DIR members=N
REL A→B dist direction overlap=% aabb_overlap=% occ=%
LIT light→surface @angle° i=normalized raw=value
SHAD light→surface coverage% casters:names contact
MAT material: appearance -- needs X; warnings
SPATIAL obj fact_type key=value — objective measurements (not judgments)
ASSEMBLY "name" members=[...] center=[x,y,z] types=[MESH,...]
HARMONY types=wood(40%)+metal(25%) temp=warm
PALETTE lum=N #hex1 #hex2 ... — micro-render ground truth
CONTAIN outer contains inner mode
RAY 12x12 obj=coverage%
MVIEW view: positions/tiers
HIER child > parent > grandparent
GRP collection: member1, member2
PHYS obj type mass=kg
ANIM obj action=name frame=N/total playing/stopped
VERIFY FAIL obj message — transform failure (only on failure, silent on success)

Key SPATIAL fact types:
- bbox_below_surface: object sunk into surface (pct>25% = problem)
- bbox_extends_into: AABB overlap with another object
- surface_intersect: center at surface level, half inside (suggest_z provided)
- no_material_slots: renders as default grey
- no_ground_below: floating object (check if intentional)
- inside_bbox: light/object trapped in geometry (check transparency)
- no_light_sources: scene will render black
- scale_diagonal: extreme object size
- near_plane: object clipped by camera near plane
"""


@mcp.prompt()
def error_recovery_playbook() -> str:
    """What to do when transforms fail, VERIFY reports errors, or tools return unexpected results."""
    return """Error Recovery Playbook:

VERIFY FAIL — parent moved but mesh didn't:
  → Use transform_object with recursive=True
  → If still failing: undo, use execute_blender_code with bpy.ops.transform

VERIFY FAIL — rotation_not_inherited:
  → Parent was rotated but children show identity rotation
  → Fix: transform_object(recursive=True) forces depsgraph update

surface_intersect detected:
  → Object center is at surface level, bottom half inside
  → Fix: move Z up by the depth amount (suggest_z provided in SPATIAL line)

bbox_below_surface pct > 25%:
  → Object is sunk into another object's surface
  → Fix: raise Z position until pct < 5%

no_material_slots on visible object:
  → Will render as default grey
  → Fix: manage_materials(action="create"...) then assign

Tool returns error:
  → Log via qa-auditor agent
  → Try alternative tool or execute_blender_code as fallback
  → Always undo failed operations before retrying

Orphaned objects after delete:
  → delete_object now cascades to all descendants automatically
  → If orphans exist from old operations: select and delete manually
"""


@mcp.prompt()
def material_setup_guide() -> str:
    """PBR material creation reference with common recipes."""
    return """Material Setup Guide:

Quick create with PBR values:
  manage_materials(action="create", material_name="Oak", color=[0.3,0.15,0.08], roughness=0.4,
                   properties={"specular": 0.3, "normal_strength": 0.8})

Common recipes:
  Wood:     color=[0.3,0.15,0.08] roughness=0.3-0.6 specular=0.2-0.4
  Metal:    metallic=1.0 roughness=0.05-0.4 color=neutral
  Glass:    properties={"transmission": 1.0, "ior": 1.45} roughness=0.0
  Fabric:   roughness=0.7-0.9 properties={"sheen_weight": 0.5, "subsurface_weight": 0.1}
  Concrete: roughness=0.85 color=[0.4,0.38,0.35] properties={"normal_strength": 0.5}
  Plastic:  roughness=0.3-0.5 specular=0.5 saturated colors

Procedural presets (one-call full node graph):
  manage_materials(action="create_procedural", material_name="MarbleTop", preset="marble")
  Presets: wood, marble, metal_brushed, glass, fabric, concrete, water

Texture from Poly Haven:
  search_polyhaven_assets(query="wood floor", type="textures")
  set_texture(object_name="Floor", texture_path="/path/to/texture.jpg")

Properties dict keys: color, base_color, metallic, roughness, specular, specular_tint,
  ior, transmission, subsurface_weight, emission_color, emission_strength, alpha,
  coat_weight, coat_roughness, sheen_weight, sheen_tint, normal_strength
"""


# ─── MCP Resources ─────────────────────────────────────────────────────────


@mcp.resource("blender://scene/perception")
def scene_perception_resource() -> str:
    """Current scene perception snapshot — structured 3D spatial intelligence."""
    try:
        result = _send_and_return("get_scene_perception", {})
        return result if isinstance(result, str) else json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


@mcp.resource("blender://scene/info")
def scene_info_resource() -> str:
    """Basic scene information — object counts, types, render settings."""
    try:
        result = _send_and_return("get_scene_info", {})
        return result if isinstance(result, str) else json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


@mcp.resource("blender://tools/reference")
def tools_reference_resource() -> str:
    """Complete BlenderWeave tool reference."""
    return """BlenderWeave Tool Categories:
Object: create_object, get_object_info, duplicate_object, delete_object, transform_object(recursive, look_at), batch_transform, place_relative
Batch: batch_execute
Assembly: create_assembly (dining_chair, table, sofa, floor_lamp, bookshelf)
Materials: manage_materials (create, assign, set_properties, get_properties, create_procedural, edit_node, add_node, connect, disconnect, edit_color_ramp, get_node_info)
Nodes: build_node_graph, get_node_graph, list_node_types, set_texture, bake_textures
Lighting: manage_lights, set_camera, manage_world
Mesh: mesh_operation, uv_operation, manage_curves, volume_operation
Procedural: procedural_generate (buildings, terrain, trees, roads, rooms), generate_lod_chain, generate_collision_mesh
Render: render_scene(animation=True), render_region, configure_render_settings, camera_walkthrough
Viewport: set_viewport, set_viewport_shading, get_viewport_thumbnail, get_viewport_screenshot
Animation: set_keyframe, manage_actions, manage_nla, manage_drivers, set_frame
Physics: manage_physics, manage_particles, manage_constraints
Rigging: manage_armature, manage_weights, manage_shape_keys
Scene: manage_collections, manage_hierarchy, manage_selection, manage_custom_properties, manage_snapshots
File: save_file, open_file, import_model, export_model, undo, redo
Assets: Poly Haven, Sketchfab, Hyper3D, Trellis2, Hunyuan3D
Perception: get_scene_info, get_scene_perception, get_scene_delta"""


# Main execution

def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()