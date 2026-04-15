# op_blender_mcp/server.py - OpenCode-optimized Blender MCP Server
from mcp.server.fastmcp import FastMCP, Context, Image
import socket
import json
import asyncio
import logging
import tempfile
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List
import os
from pathlib import Path
import base64
from urllib.parse import urlparse

# Import telemetry
from .telemetry import record_startup, get_telemetry
from .telemetry_decorator import telemetry_tool

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("OpBlenderMCPServer")

# Default configuration
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9876

# OpenCode-specific constants
OPENCODE_TOOL_PREFIX = "[Blender] "
MAX_RESPONSE_LENGTH = 4000


@dataclass
class BlenderConnection:
    host: str
    port: int
    sock: socket.socket = None

    def connect(self) -> bool:
        if self.sock:
            return True

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Blender at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Blender: {str(e)}")
            self.sock = None
            return False

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Blender: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        chunks = []
        sock.settimeout(180.0)

        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception(
                                "Connection closed before receiving any data"
                            )
                        break

                    chunks.append(chunk)

                    try:
                        data = b"".join(chunks)
                        json.loads(data.decode("utf-8"))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except socket.timeout:
            logger.warning("Socket timeout during chunked receive")
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise

        if chunks:
            data = b"".join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode("utf-8"))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(
        self, command_type: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Blender")

        command = {"type": command_type, "params": params or {}}

        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            self.sock.sendall(json.dumps(command).encode("utf-8"))
            logger.info(f"Command sent, waiting for response...")
            self.sock.settimeout(180.0)
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            response = json.loads(response_data.decode("utf-8"))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")

            if response.get("status") == "error":
                logger.error(f"Blender error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Blender"))

            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Blender")
            self.sock = None
            raise Exception(
                "Timeout waiting for Blender response - try simplifying your request"
            )
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Blender lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Blender: {str(e)}")
            raise Exception(f"Invalid response from Blender: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Blender: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Blender: {str(e)}")


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("op-blender-mcp server starting up")
        try:
            record_startup()
        except Exception as e:
            logger.debug(f"Failed to record startup telemetry: {e}")

        try:
            blender = get_blender_connection()
            logger.info("Successfully connected to Blender on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Blender on startup: {str(e)}")
            logger.warning(
                "Make sure the Blender addon is running before using Blender resources or tools"
            )

        yield {}
    finally:
        global _blender_connection
        if _blender_connection:
            logger.info("Disconnecting from Blender on shutdown")
            _blender_connection.disconnect()
            _blender_connection = None
        logger.info("op-blender-mcp server shut down")


mcp = FastMCP("op-blender-mcp", lifespan=server_lifespan)

_blender_connection = None
_polyhaven_enabled = False


def get_blender_connection():
    """Get or create a persistent Blender connection"""
    global _blender_connection, _polyhaven_enabled

    if _blender_connection is not None:
        try:
            result = _blender_connection.send_command("get_polyhaven_status")
            _polyhaven_enabled = result.get("enabled", False)
            return _blender_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _blender_connection.disconnect()
            except:
                pass
            _blender_connection = None

    if _blender_connection is None:
        host = os.getenv("BLENDER_HOST", DEFAULT_HOST)
        port = int(os.getenv("BLENDER_PORT", DEFAULT_PORT))
        _blender_connection = BlenderConnection(host=host, port=port)
        if not _blender_connection.connect():
            logger.error("Failed to connect to Blender")
            _blender_connection = None
            raise Exception(
                "Could not connect to Blender. Make sure the Blender addon is running."
            )
        logger.info("Created new persistent connection to Blender")

    return _blender_connection


def _format_for_opencode(result: str, tool_name: str) -> str:
    """Format result for OpenCode consumption with consistent prefix"""
    formatted = f"{OPENCODE_TOOL_PREFIX}{tool_name}\n\n{result}"
    if len(formatted) > MAX_RESPONSE_LENGTH:
        return formatted[:MAX_RESPONSE_LENGTH] + "\n\n[Output truncated]"
    return formatted


def _format_error(error: str, tool_name: str) -> str:
    """Format error for OpenCode with actionable message"""
    return f"{OPENCODE_TOOL_PREFIX}{tool_name} Error: {error}"


@telemetry_tool("get_scene_info")
@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """Get detailed information about the current Blender scene"""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_scene_info")
        return _format_for_opencode(json.dumps(result, indent=2), "get_scene_info")
    except Exception as e:
        logger.error(f"Error getting scene info from Blender: {str(e)}")
        return _format_error(str(e), "get_scene_info")


@telemetry_tool("get_object_info")
@mcp.tool()
def get_object_info(ctx: Context, object_name: str) -> str:
    """Get detailed information about a specific object in the Blender scene."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_object_info", {"name": object_name})
        return _format_for_opencode(json.dumps(result, indent=2), "get_object_info")
    except Exception as e:
        logger.error(f"Error getting object info from Blender: {str(e)}")
        return _format_error(str(e), "get_object_info")


@telemetry_tool("get_viewport_screenshot")
@mcp.tool()
def get_viewport_screenshot(ctx: Context, max_size: int = 800) -> Image:
    """Capture a screenshot of the current Blender 3D viewport."""
    try:
        blender = get_blender_connection()
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"blender_screenshot_{os.getpid()}.png")

        result = blender.send_command(
            "get_viewport_screenshot",
            {"max_size": max_size, "filepath": temp_path, "format": "png"},
        )

        if "error" in result:
            raise Exception(result["error"])

        if not os.path.exists(temp_path):
            raise Exception("Screenshot file was not created")

        with open(temp_path, "rb") as f:
            image_bytes = f.read()

        os.remove(temp_path)
        return Image(data=image_bytes, format="png")

    except Exception as e:
        logger.error(f"Error capturing screenshot: {str(e)}")
        raise Exception(f"Screenshot failed: {str(e)}")


@telemetry_tool("execute_blender_code")
@mcp.tool()
def execute_blender_code(ctx: Context, code: str) -> str:
    """Execute arbitrary Python code in Blender. Make sure to do it step-by-step."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("execute_code", {"code": code})
        output = f"Code executed successfully:\n{result.get('result', '')}"
        return _format_for_opencode(output, "execute_blender_code")
    except Exception as e:
        logger.error(f"Error executing code: {str(e)}")
        return _format_error(str(e), "execute_blender_code")


@telemetry_tool("get_polyhaven_categories")
@mcp.tool()
def get_polyhaven_categories(ctx: Context, asset_type: str = "hdris") -> str:
    """Get a list of categories for a specific asset type on Polyhaven."""
    try:
        blender = get_blender_connection()
        if not _polyhaven_enabled:
            return f"{OPENCODE_TOOL_PREFIX}PolyHaven disabled. Enable in Blender sidebar, then run again."
        result = blender.send_command(
            "get_polyhaven_categories", {"asset_type": asset_type}
        )

        if "error" in result:
            return _format_error(result["error"], "get_polyhaven_categories")

        categories = result["categories"]
        formatted_output = f"Categories for {asset_type}:\n\n"
        sorted_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)

        for category, count in sorted_categories:
            formatted_output += f"- {category}: {count} assets\n"

        return _format_for_opencode(formatted_output, "get_polyhaven_categories")
    except Exception as e:
        logger.error(f"Error getting Polyhaven categories: {str(e)}")
        return _format_error(str(e), "get_polyhaven_categories")


@telemetry_tool("search_polyhaven_assets")
@mcp.tool()
def search_polyhaven_assets(
    ctx: Context, asset_type: str = "all", categories: str = None
) -> str:
    """Search for assets on Polyhaven with optional filtering."""
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "search_polyhaven_assets",
            {"asset_type": asset_type, "categories": categories},
        )

        if "error" in result:
            return _format_error(result["error"], "search_polyhaven_assets")

        assets = result["assets"]
        total_count = result["total_count"]
        returned_count = result["returned_count"]

        formatted_output = f"Found {total_count} assets"
        if categories:
            formatted_output += f" in categories: {categories}"
        formatted_output += f"\nShowing {returned_count} assets:\n\n"

        sorted_assets = sorted(
            assets.items(), key=lambda x: x[1].get("download_count", 0), reverse=True
        )

        for asset_id, asset_data in sorted_assets:
            formatted_output += (
                f"- {asset_data.get('name', asset_id)} (ID: {asset_id})\n"
            )
            formatted_output += (
                f"  Type: {['HDRI', 'Texture', 'Model'][asset_data.get('type', 0)]}\n"
            )
            formatted_output += (
                f"  Categories: {', '.join(asset_data.get('categories', []))}\n"
            )
            formatted_output += (
                f"  Downloads: {asset_data.get('download_count', 'Unknown')}\n\n"
            )

        return _format_for_opencode(formatted_output, "search_polyhaven_assets")
    except Exception as e:
        logger.error(f"Error searching Polyhaven assets: {str(e)}")
        return _format_error(str(e), "search_polyhaven_assets")


@telemetry_tool("download_polyhaven_asset")
@mcp.tool()
def download_polyhaven_asset(
    ctx: Context,
    asset_id: str,
    asset_type: str,
    resolution: str = "1k",
    file_format: str = None,
) -> str:
    """Download and import a Polyhaven asset into Blender."""
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "download_polyhaven_asset",
            {
                "asset_id": asset_id,
                "asset_type": asset_type,
                "resolution": resolution,
                "file_format": file_format,
            },
        )

        if "error" in result:
            return _format_error(result["error"], "download_polyhaven_asset")

        if result.get("success"):
            message = result.get(
                "message", "Asset downloaded and imported successfully"
            )

            if asset_type == "hdris":
                output = f"{message}. The HDRI has been set as the world environment."
            elif asset_type == "textures":
                material_name = result.get("material", "")
                maps = ", ".join(result.get("maps", []))
                output = (
                    f"{message}. Created material '{material_name}' with maps: {maps}."
                )
            elif asset_type == "models":
                output = (
                    f"{message}. The model has been imported into the current scene."
                )
            else:
                output = message
            return _format_for_opencode(output, "download_polyhaven_asset")
        else:
            return _format_error(
                result.get("message", "Unknown error"), "download_polyhaven_asset"
            )
    except Exception as e:
        logger.error(f"Error downloading Polyhaven asset: {str(e)}")
        return _format_error(str(e), "download_polyhaven_asset")


@telemetry_tool("set_texture")
@mcp.tool()
def set_texture(ctx: Context, object_name: str, texture_id: str) -> str:
    """Apply a previously downloaded Polyhaven texture to an object."""
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "set_texture", {"object_name": object_name, "texture_id": texture_id}
        )

        if "error" in result:
            return _format_error(result["error"], "set_texture")

        if result.get("success"):
            material_name = result.get("material", "")
            maps = ", ".join(result.get("maps", []))
            output = f"Successfully applied texture '{texture_id}' to {object_name}.\n"
            output += f"Using material '{material_name}' with maps: {maps}."
            return _format_for_opencode(output, "set_texture")
        else:
            return _format_error(result.get("message", "Unknown error"), "set_texture")
    except Exception as e:
        logger.error(f"Error applying texture: {str(e)}")
        return _format_error(str(e), "set_texture")


@telemetry_tool("get_polyhaven_status")
@mcp.tool()
def get_polyhaven_status(ctx: Context) -> str:
    """Check if PolyHaven integration is enabled in Blender."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_polyhaven_status")
        enabled = result.get("enabled", False)
        message = result.get("message", "")
        if enabled:
            message += "PolyHaven is good at Textures, and has a wider variety of textures than Sketchfab."
        return message
    except Exception as e:
        logger.error(f"Error checking PolyHaven status: {str(e)}")
        return _format_error(str(e), "get_polyhaven_status")


@telemetry_tool("get_hyper3d_status")
@mcp.tool()
def get_hyper3d_status(ctx: Context) -> str:
    """Check if Hyper3D Rodin integration is enabled in Blender."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_hyper3d_status")
        message = result.get("message", "")
        return message
    except Exception as e:
        logger.error(f"Error checking Hyper3D status: {str(e)}")
        return _format_error(str(e), "get_hyper3d_status")


@telemetry_tool("get_sketchfab_status")
@mcp.tool()
def get_sketchfab_status(ctx: Context) -> str:
    """Check if Sketchfab integration is enabled in Blender."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_sketchfab_status")
        message = result.get("message", "")
        if result.get("enabled"):
            message += "Sketchfab is good at Realistic models, and has a wider variety of models than PolyHaven."
        return message
    except Exception as e:
        logger.error(f"Error checking Sketchfab status: {str(e)}")
        return _format_error(str(e), "get_sketchfab_status")


@telemetry_tool("search_sketchfab_models")
@mcp.tool()
def search_sketchfab_models(
    ctx: Context,
    query: str,
    categories: str = None,
    count: int = 20,
    downloadable: bool = True,
) -> str:
    """Search for models on Sketchfab with optional filtering."""
    try:
        blender = get_blender_connection()
        logger.info(f"Searching Sketchfab models with query: {query}")
        result = blender.send_command(
            "search_sketchfab_models",
            {
                "query": query,
                "categories": categories,
                "count": count,
                "downloadable": downloadable,
            },
        )

        if "error" in result:
            return _format_error(result["error"], "search_sketchfab_models")

        if result is None:
            return _format_error(
                "Received no response from Sketchfab search", "search_sketchfab_models"
            )

        models = result.get("results", []) or []
        if not models:
            return _format_for_opencode(
                f"No models found matching '{query}'", "search_sketchfab_models"
            )

        formatted_output = f"Found {len(models)} models matching '{query}':\n\n"

        for model in models:
            if model is None:
                continue
            model_name = model.get("name", "Unnamed model")
            model_uid = model.get("uid", "Unknown ID")
            formatted_output += f"- {model_name} (UID: {model_uid})\n"

            user = model.get("user") or {}
            username = (
                user.get("username", "Unknown author")
                if isinstance(user, dict)
                else "Unknown author"
            )
            formatted_output += f"  Author: {username}\n"

            license_data = model.get("license") or {}
            license_label = (
                license_data.get("label", "Unknown")
                if isinstance(license_data, dict)
                else "Unknown"
            )
            formatted_output += f"  License: {license_label}\n"

            face_count = model.get("faceCount", "Unknown")
            is_downloadable = "Yes" if model.get("isDownloadable") else "No"
            formatted_output += f"  Face count: {face_count}\n"
            formatted_output += f"  Downloadable: {is_downloadable}\n\n"

        return _format_for_opencode(formatted_output, "search_sketchfab_models")
    except Exception as e:
        logger.error(f"Error searching Sketchfab models: {str(e)}")
        return _format_error(str(e), "search_sketchfab_models")


@telemetry_tool("get_sketchfab_model_preview")
@mcp.tool()
def get_sketchfab_model_preview(ctx: Context, uid: str) -> Image:
    """Get a preview thumbnail of a Sketchfab model by its UID."""
    try:
        blender = get_blender_connection()
        logger.info(f"Getting Sketchfab model preview for UID: {uid}")
        result = blender.send_command("get_sketchfab_model_preview", {"uid": uid})

        if result is None:
            raise Exception("Received no response from Blender")

        if "error" in result:
            raise Exception(result["error"])

        image_data = base64.b64decode(result["image_data"])
        img_format = result.get("format", "jpeg")

        model_name = result.get("model_name", "Unknown")
        author = result.get("author", "Unknown")
        logger.info(f"Preview retrieved for '{model_name}' by {author}")

        return Image(data=image_data, format=img_format)

    except Exception as e:
        logger.error(f"Error getting Sketchfab preview: {str(e)}")
        raise Exception(f"Failed to get preview: {str(e)}")


@telemetry_tool("download_sketchfab_model")
@mcp.tool()
def download_sketchfab_model(ctx: Context, uid: str, target_size: float) -> str:
    """Download and import a Sketchfab model by its UID."""
    try:
        blender = get_blender_connection()
        logger.info(f"Downloading Sketchfab model: {uid}, target_size={target_size}")

        result = blender.send_command(
            "download_sketchfab_model",
            {"uid": uid, "normalize_size": True, "target_size": target_size},
        )

        if result is None:
            return _format_error(
                "Received no response from Sketchfab download request",
                "download_sketchfab_model",
            )

        if "error" in result:
            return _format_error(result["error"], "download_sketchfab_model")

        if result.get("success"):
            imported_objects = result.get("imported_objects", [])
            object_names = ", ".join(imported_objects) if imported_objects else "none"

            output = f"Successfully imported model.\n"
            output += f"Created objects: {object_names}\n"

            if result.get("dimensions"):
                dims = result["dimensions"]
                output += f"Dimensions (X, Y, Z): {dims[0]:.3f} x {dims[1]:.3f} x {dims[2]:.3f} meters\n"

            if result.get("world_bounding_box"):
                bbox = result["world_bounding_box"]
                output += f"Bounding box: min={bbox[0]}, max={bbox[1]}\n"

            if result.get("normalized"):
                scale = result.get("scale_applied", 1.0)
                output += f"Size normalized: scale factor {scale:.6f} applied (target size: {target_size}m)\n"

            return _format_for_opencode(output, "download_sketchfab_model")
        else:
            return _format_error(
                result.get("message", "Unknown error"), "download_sketchfab_model"
            )
    except Exception as e:
        logger.error(f"Error downloading Sketchfab model: {str(e)}")
        return _format_error(str(e), "download_sketchfab_model")


def _process_bbox(original_bbox: list[float] | list[int] | None) -> list[int] | None:
    if original_bbox is None:
        return None
    if all(isinstance(i, int) for i in original_bbox):
        return original_bbox
    if any(i <= 0 for i in original_bbox):
        raise ValueError("Incorrect number range: bbox must be bigger than zero!")
    return (
        [int(float(i) / max(original_bbox) * 100) for i in original_bbox]
        if original_bbox
        else None
    )


@telemetry_tool("generate_hyper3d_model_via_text")
@mcp.tool()
def generate_hyper3d_model_via_text(
    ctx: Context, text_prompt: str, bbox_condition: list[float] = None
) -> str:
    """Generate 3D asset using Hyper3D by giving description of the desired asset."""
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "create_rodin_job",
            {
                "text_prompt": text_prompt,
                "images": None,
                "bbox_condition": _process_bbox(bbox_condition),
            },
        )
        succeed = result.get("submit_time", False)
        if succeed:
            return _format_for_opencode(
                json.dumps(
                    {
                        "task_uuid": result["uuid"],
                        "subscription_key": result["jobs"]["subscription_key"],
                    },
                    indent=2,
                ),
                "generate_hyper3d_model_via_text",
            )
        else:
            return _format_for_opencode(
                json.dumps(result, indent=2), "generate_hyper3d_model_via_text"
            )
    except Exception as e:
        logger.error(f"Error generating Hyper3D task: {str(e)}")
        return _format_error(str(e), "generate_hyper3d_model_via_text")


@telemetry_tool("generate_hyper3d_model_via_images")
@mcp.tool()
def generate_hyper3d_model_via_images(
    ctx: Context,
    input_image_paths: list[str] = None,
    input_image_urls: list[str] = None,
    bbox_condition: list[float] = None,
) -> str:
    """Generate 3D asset using Hyper3D by giving images of the wanted asset."""
    if input_image_paths is not None and input_image_urls is not None:
        return _format_error(
            "Conflict parameters given!", "generate_hyper3d_model_via_images"
        )
    if input_image_paths is None and input_image_urls is None:
        return _format_error("No image given!", "generate_hyper3d_model_via_images")
    if input_image_paths is not None:
        if not all(os.path.exists(i) for i in input_image_paths):
            return _format_error(
                "Not all image paths are valid!", "generate_hyper3d_model_via_images"
            )
        images = []
        for path in input_image_paths:
            with open(path, "rb") as f:
                images.append(
                    (Path(path).suffix, base64.b64encode(f.read()).decode("ascii"))
                )
    elif input_image_urls is not None:
        if not all(urlparse(i) for i in input_image_paths):
            return _format_error(
                "Not all image URLs are valid!", "generate_hyper3d_model_via_images"
            )
        images = input_image_urls.copy()
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "create_rodin_job",
            {
                "text_prompt": None,
                "images": images,
                "bbox_condition": _process_bbox(bbox_condition),
            },
        )
        succeed = result.get("submit_time", False)
        if succeed:
            return _format_for_opencode(
                json.dumps(
                    {
                        "task_uuid": result["uuid"],
                        "subscription_key": result["jobs"]["subscription_key"],
                    },
                    indent=2,
                ),
                "generate_hyper3d_model_via_images",
            )
        else:
            return _format_for_opencode(
                json.dumps(result, indent=2), "generate_hyper3d_model_via_images"
            )
    except Exception as e:
        logger.error(f"Error generating Hyper3D task: {str(e)}")
        return _format_error(str(e), "generate_hyper3d_model_via_images")


@telemetry_tool("poll_rodin_job_status")
@mcp.tool()
def poll_rodin_job_status(
    ctx: Context,
    subscription_key: str = None,
    request_id: str = None,
):
    """Check if the Hyper3D Rodin generation task is completed."""
    try:
        blender = get_blender_connection()
        kwargs = {}
        if subscription_key:
            kwargs = {"subscription_key": subscription_key}
        elif request_id:
            kwargs = {"request_id": request_id}
        result = blender.send_command("poll_rodin_job_status", kwargs)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error polling Rodin job status: {str(e)}")
        return _format_error(str(e), "poll_rodin_job_status")


@telemetry_tool("import_generated_asset")
@mcp.tool()
def import_generated_asset(
    ctx: Context,
    name: str,
    task_uuid: str = None,
    request_id: str = None,
):
    """Import the asset generated by Hyper3D Rodin after the generation task is completed."""
    try:
        blender = get_blender_connection()
        kwargs = {"name": name}
        if task_uuid:
            kwargs["task_uuid"] = task_uuid
        elif request_id:
            kwargs["request_id"] = request_id
        result = blender.send_command("import_generated_asset", kwargs)
        return _format_for_opencode(
            json.dumps(result, indent=2), "import_generated_asset"
        )
    except Exception as e:
        logger.error(f"Error importing generated asset: {str(e)}")
        return _format_error(str(e), "import_generated_asset")


@telemetry_tool("get_hunyuan3d_status")
@mcp.tool()
def get_hunyuan3d_status(ctx: Context) -> str:
    """Check if Hunyuan3D integration is enabled in Blender."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_hunyuan3d_status")
        message = result.get("message", "")
        return message
    except Exception as e:
        logger.error(f"Error checking Hunyuan3D status: {str(e)}")
        return _format_error(str(e), "get_hunyuan3d_status")


@telemetry_tool("generate_hunyuan3d_model")
@mcp.tool()
def generate_hunyuan3d_model(
    ctx: Context, text_prompt: str = None, input_image_url: str = None
) -> str:
    """Generate 3D asset using Hunyuan3D by providing text description or image reference."""
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "create_hunyuan_job",
            {
                "text_prompt": text_prompt,
                "image": input_image_url,
            },
        )
        if "JobId" in result.get("Response", {}):
            job_id = result["Response"]["JobId"]
            formatted_job_id = f"job_{job_id}"
            return _format_for_opencode(
                json.dumps(
                    {
                        "job_id": formatted_job_id,
                    },
                    indent=2,
                ),
                "generate_hunyuan3d_model",
            )
        return _format_for_opencode(
            json.dumps(result, indent=2), "generate_hunyuan3d_model"
        )
    except Exception as e:
        logger.error(f"Error generating Hunyuan3D task: {str(e)}")
        return _format_error(str(e), "generate_hunyuan3d_model")


@telemetry_tool("poll_hunyuan_job_status")
@mcp.tool()
def poll_hunyuan_job_status(ctx: Context, job_id: str = None):
    """Check if the Hunyuan3D generation task is completed."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("poll_hunyuan_job_status", {"job_id": job_id})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error polling Hunyuan3D job status: {str(e)}")
        return _format_error(str(e), "poll_hunyuan_job_status")


@telemetry_tool("import_generated_asset_hunyuan")
@mcp.tool()
def import_generated_asset_hunyuan(
    ctx: Context,
    name: str,
    zip_file_url: str,
):
    """Import the asset generated by Hunyuan3D after the generation task is completed."""
    try:
        blender = get_blender_connection()
        kwargs = {"name": name, "zip_file_url": zip_file_url}
        result = blender.send_command("import_generated_asset_hunyuan", kwargs)
        return _format_for_opencode(
            json.dumps(result, indent=2), "import_generated_asset_hunyuan"
        )
    except Exception as e:
        logger.error(f"Error importing Hunyuan3D asset: {str(e)}")
        return _format_error(str(e), "import_generated_asset_hunyuan")


@mcp.prompt()
def asset_creation_strategy() -> str:
    """OpenCode-optimized strategy for creating 3D assets in Blender"""
    return """When creating 3D content in Blender via OpenCode, follow this workflow:

## Pre-Check
1. Always run get_scene_info() first to understand the current scene state

## Integration Status Check (Priority Order)
1. **PolyHaven** - Best for: textures, materials, HDRIs, generic models
   - Run get_polyhaven_status() to verify
2. **Sketchfab** - Best for: realistic models, specific objects, wide variety
   - Run get_sketchfab_status() to verify
3. **Hyper3D (Rodin)** - Best for: AI-generated single objects
   - Run get_hyper3d_status() to verify
4. **Hunyuan3D** - Best for: AI-generated single objects
   - Run get_hunyuan3d_status() to verify

## Asset Creation Workflow

### For Existing Assets (from libraries):
1. Search using appropriate integration
2. Preview if available
3. Download with target_size for models
4. Verify imported object with get_object_info()

### For AI-Generated Assets:
1. Generate via text/image
2. Poll status until completion
3. Import the generated asset
4. Check world_bounding_box and adjust location/scale

## Post-Import Checklist
- Check world_bounding_box for each imported object
- Ensure proper spatial relationships
- Verify objects are not clipping
- Adjust scale/location as needed

## Fallback Order
Only use execute_blender_code() when:
- All integrations are disabled
- Simple primitives requested
- Basic materials/colors needed
- AI generation failed

## Asset Source Priority
- Specific objects → Sketchfab → PolyHaven
- Generic objects → PolyHaven → Sketchfab  
- Custom items → Hyper3D / Hunyuan3D
- Textures → PolyHaven
- Environment → PolyHaven HDRIs"""


@mcp.prompt()
def blender_workflow() -> str:
    """OpenCode-specific Blender workflow guidance"""
    return """## OpenCode + Blender Workflow

### Session Start
1. Check scene state with get_scene_info()
2. Verify integration availability with status tools

### Modeling Tasks
- Use primitives from Blender API only when necessary
- Prefer downloaded assets for efficiency

### Material Tasks
- Use PolyHaven textures as first choice
- Apply via set_texture() after download

### Lighting Tasks
- Use PolyHaven HDRIs for environment lighting
- Download with asset_type="hdris"

### General Tips
- Always capture screenshots to verify changes
- Check object properties after import
- Use execute_blender_code() for custom operations
- Verify all spatial relationships with bounding boxes"""


def main():
    """Run the MCP server"""
    mcp.run()


if __name__ == "__main__":
    main()
