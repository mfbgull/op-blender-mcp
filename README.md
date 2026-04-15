# op-blender-mcp

OpenCode-optimized Blender integration through the Model Context Protocol (MCP).

## Overview

This package provides OpenCode with native access to Blender through the MCP protocol. Control Blender's 3D environment, manipulate objects, execute Python code, and import assets from popular libraries.

## Requirements

- **Blender 3.0+** installed with the addon enabled
- **Python 3.10+**
- **OpenCode** installed

## Installation

### 1. Install the Python package

```bash
pip install op-blender-mcp
```

Or for development:

```bash
git clone https://github.com/mfbgull/op-blender-mcp.git
cd op-blender-mcp
pip install -e .
```

### 2. Install the Blender Addon

1. Open Blender
2. Go to **Edit > Preferences > Add-ons**
3. Click **Install** and select `addon/addon.py` from this repository
4. Enable the "Blender MCP" addon
5. Configure integrations (PolyHaven, Sketchfab, Hyper3D, Hunyuan3D) in the sidebar

### 3. Configure OpenCode

Add the following to your OpenCode config (`~/.config/opencode/config.json` or project-level):

```json
{
  "mcp": {
    "blender": {
      "type": "local",
      "command": ["op-blender-mcp"]
    }
  }
}
```

Or use the CLI:

```bash
opencode mcp add
# Select "local" and enter "op-blender-mcp" as the command
```

## Available Tools

### Scene & Object Management
| Tool | Description |
|------|-------------|
| `get_scene_info` | Get detailed information about the current Blender scene |
| `get_object_info` | Get detailed information about a specific object |
| `get_viewport_screenshot` | Capture a screenshot of the 3D viewport |
| `execute_blender_code` | Execute arbitrary Python code in Blender |

### Asset Libraries
| Tool | Description |
|------|-------------|
| `search_polyhaven_assets` | Search PolyHaven for textures, models, HDRIs |
| `download_polyhaven_asset` | Download and import PolyHaven assets |
| `search_sketchfab_models` | Search Sketchfab for 3D models |
| `download_sketchfab_model` | Download and import Sketchfab models |
| `get_sketchfab_model_preview` | Get preview thumbnail of a model |

### AI Generation
| Tool | Description |
|------|-------------|
| `generate_hyper3d_model_via_text` | Generate 3D models using Hyper3D (text) |
| `generate_hyper3d_model_via_images` | Generate 3D models using Hyper3D (images) |
| `generate_hunyuan3d_model` | Generate 3D models using Hunyuan3D |
| `poll_rodin_job_status` | Check Hyper3D generation status |
| `poll_hunyuan_job_status` | Check Hunyuan3D generation status |
| `import_generated_asset` | Import generated assets into Blender |

### Status Checks
| Tool | Description |
|------|-------------|
| `get_polyhaven_status` | Check if PolyHaven integration is enabled |
| `get_sketchfab_status` | Check if Sketchfab integration is enabled |
| `get_hyper3d_status` | Check if Hyper3D integration is enabled |
| `get_hunyuan3d_status` | Check if Hunyuan3D integration is enabled |

## Usage Example

```
opencode > Get the current scene state
[Blender] get_scene_info

Scene contains 5 objects:
- Cube
- Suzanne
- Light
- Camera
- Ground

opencode > Add a realistic wood texture to the cube
opencode > Use execute_blender_code to add a material
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BLENDER_HOST` | localhost | Blender addon host address |
| `BLENDER_PORT` | 9876 | Blender addon port |

### Blender Addon Settings

In Blender's sidebar (N-panel), you can configure:

- **PolyHaven Integration**: Enable/disable and manage API access
- **Sketchfab Integration**: Enable/disable and configure API key
- **Hyper3D Rodin**: Enable/disable and configure API key (free trial available)
- **Hunyuan3D**: Enable/disable and configure API credentials

## Troubleshooting

### Connection Issues

If OpenCode can't connect to Blender:

1. Ensure the Blender addon is installed and enabled
2. Check that Blender is running
3. Verify the host/port configuration matches
4. Check Blender's console for connection messages

### Telemetry

This package includes optional anonymous telemetry. To disable:

```python
import os
os.environ["DISABLE_TELEMETRY"] = "true"
```

Or disable via Blender addon preferences.

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- Original blender-mcp by [ahujasid](https://github.com/ahujasid/blender-mcp)
- Built on [Model Context Protocol](https://modelcontextprotocol.io)
