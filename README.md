# BlenderWeave

MCP server that connects AI to Blender's 3D pipeline — 91 tools covering objects, materials, rigging, animation, physics, node graphs, rendering, and asset integrations. Every modifying command returns structured scene perception in the [Perspicacity](https://github.com/pedronaugusto/perspicacity) format — no screenshots needed for routine feedback.

## Architecture

```
Claude Code / Cursor / Codex / any MCP client
    │ stdio (MCP Protocol)
    ▼
BlenderWeave MCP Server         ← pip install / uvx / bundled via plugin
    │ unix socket (~/.blenderweave/servers/)
    │ length-prefixed JSON
    ▲
BlenderWeave Addon               ← installed in Blender
    │ auto-discover + auto-reconnect
    │ bpy.app.timers (main thread)
    ▼
Blender 4.2+ / 5.0+ (bpy API)
```

## Installation

### Blender Addon

Download `blender_weave.zip` from [Releases](https://github.com/pedronaugusto/blender-weave/releases) and install it in Blender:

1. Open Blender → **Edit** → **Preferences** → **Extensions**
2. Click **Install from Disk** (dropdown arrow next to the search bar)
3. Select the downloaded `blender_weave.zip`
4. Enable **BlenderWeave** in the extensions list

For development, symlink instead:
```bash
# macOS
ln -s /path/to/blender-weave/addon \
  ~/Library/Application\ Support/Blender/5.0/extensions/user_default/blender_weave

# Linux
ln -s /path/to/blender-weave/addon \
  ~/.config/blender/5.0/extensions/user_default/blender_weave
```

### MCP Server

**Claude Code** (recommended — includes agent + Perspicacity skill):
```bash
/plugin marketplace add pedronaugusto/claude-marketplace
/plugin install blender-weave@gusto-plugins
```

**Cursor / VS Code / Claude Desktop / other MCP clients:**
```bash
pip install blender-weave
# or: uvx blender-weave
```

Then add to your client's MCP config:
```json
{
    "mcpServers": {
        "blender-weave": {
            "command": "uvx",
            "args": ["blender-weave"]
        }
    }
}
```

### Connect

1. Start your AI (Claude Code, Cursor, etc.) — the MCP server starts and creates a unix socket
2. Open Blender — the addon auto-discovers the server and connects
3. In Blender's 3D View sidebar (press **N**), find the **BlenderWeave** tab
4. The panel has two tabs: **Core** (always on) and **External** (asset integrations)
5. Enable integrations you want (Poly Haven, Sketchfab, etc.) — AmbientCG is enabled by default
6. Start talking to your AI

Zero configuration needed. The addon auto-reconnects if Blender is restarted, and auto-discovers if multiple MCP servers are running.

### Blender Panel

Open the sidebar in 3D View (press **N**) and find the **BlenderWeave** tab.

| Section | What it does |
|---------|-------------|
| **Connection** | Shows status (Connected / Connecting / No server). Auto-connects on startup; Connect button for manual retry. If multiple AI sessions are running, a dropdown lets you pick which one. |
| **Core tab** | Perception mode (Smart / Full / Compact), budget caps (OBJ, REL, LIT, etc.), radius filter, ray grid resolution, micro render size |
| **External tab** | Enable/disable asset libraries (Poly Haven, AmbientCG, Sketchfab, Poly Pizza, Smithsonian) and AI generation (Hyper3D, Hunyuan3D, Trellis2) with API keys |

**Perception modes:**
- **Smart** (default) — full perception minus physics/animation, radius-filtered. Best for most workflows.
- **Full** — everything enabled, all objects, all pairs. For deep scene audits.
- **Compact** — OBJ + DELTA + VERIFY only. Fastest response.

## Spatial Intelligence (Always-On)

Every modifying command returns a compact Perspicacity DSL with full 3D spatial perception. Sections are separated by blank lines for fast scanning:

```
DELTA Bottle moved [0.00,0.00,0.50] (+Z)

SCENE 12 objects 3 lights 1500W BLENDER_EEVEE ground_z=0.0
CAM Camera [2.1,-3.4,1.8] 50mm fov=39.6°
WORLD bg=[0.05,0.05,0.05] strength=1.0

LIGHT Key AREA 800W [1.0,0.95,0.9] [3,1,4]

OBJ Bottle [0,0,0.5] 23% mid-center d=2.3m Glass(clear,ior=1.45) dim=[0.08,0.08,0.3] lum=0.6 toward=Wall_Back
OBJ Wall_Back [0,3,1.5] 40% mid-center d=4.1m Concrete(textured) dim=[6,0.2,3] lum=0.3

ASSEMBLY FloorLamp members=[Base,Shade,Bulb] center=[2,1,0.8] types=[MESH]

REL Bottle→Wall_Back 1.8m behind overlap
LIT Key→Bottle @35° i=0.72
LIT Key→Wall_Back @62° i=0.31 shadow:Bottle
SHAD Key→Floor 65% casters:Bottle contact
MAT Glass: clear glass -- needs env reflections, objects behind
HARMONY types=glass(30%)+stone(50%)+metal(20%) temp=cool

PHYS Bottle active mass=0.5kg
COMP thirds=0.82 3/3_visible balance=0.65 depth=3/3
RAY 12x12 Bottle=25% Floor=60% empty=15%
MVIEW top: Floor=60% Bottle=5%
HIER Lid > Pot > Scene
GRP Kitchenware: Pot, Lid, Spoon
ANIM Bottle action=Spin frame=12/60 playing
```

Individual features can be toggled in the addon panel under "Scene Perception".

| Tool | When to use |
|------|-------------|
| Auto-perception | Always on — attached to every modifying command |
| `get_scene_perception` | Explicit full spatial query |
| `get_scene_delta` | What changed since last perception call |
| `render_region` | Check a specific object at high quality |
| `get_viewport_screenshot` | Final review or explicit "show me" |

## Tool Catalog (90+ tools)

### Scene Perception & Feedback
| Tool | What it does |
|------|-------------|
| `get_scene_perception` | Full 3D spatial intelligence — depth-sorted objects, relationships, light analysis, material predictions, constraints |
| `get_scene_delta` | What changed since last perception call (~200 bytes) |
| `get_viewport_thumbnail` | Tiny 96px JPEG viewport capture (~4KB) |
| `analyze_scene` | Full scene analysis with screenshot + structured data |
| `get_scene_info` | Scene overview — objects, materials, render engine |
| `get_object_info` | Object details — transform, mesh data, world bounding box |
| `get_viewport_screenshot` | Full viewport screenshot as PNG |
| `execute_blender_code` | Run arbitrary Python in Blender (fallback) |

### File & Undo
| Tool | What it does |
|------|-------------|
| `save_file` / `open_file` | File management |
| `undo` / `redo` | Undo stack navigation |
| `set_frame` | Animation timeline control |

### Viewport
| Tool | What it does |
|------|-------------|
| `set_viewport_shading` | Wireframe, solid, material, rendered |
| `set_viewport` | Camera lock, preset views, overlays, frame selected/all |

### Object Management
| Tool | What it does |
|------|-------------|
| `create_object` | Create meshes, lights, cameras, empties |
| `transform_object` | Move, rotate, scale — absolute or delta. Supports `recursive` and `look_at` |
| `batch_transform` | Transform multiple objects in one call |
| `duplicate_object` | Copy objects, optionally linked |
| `delete_object` | Remove objects by name list (recursive) |
| `place_relative` | Semantic placement — `in_front`, `behind`, `on_top`, etc. |
| `create_assembly` | Multi-part furniture (dining_chair, table, sofa, floor_lamp, bookshelf) |
| `batch_execute` | Multi-tool single round-trip, perception once at end |
| `manage_selection` | Select, deselect, invert, by type |
| `manage_collections` | Create, delete, nest collections; move objects; purge orphans |

### Mesh Operations
| Tool | What it does |
|------|-------------|
| `mesh_operation` | Join, separate, boolean, shade smooth/flat, apply transforms, set origin, remesh |
| `generate_lod_chain` | Create LOD levels with automatic decimation |
| `generate_collision_mesh` | Generate collision meshes (convex hull, box, voxel) |

### Materials & Textures
| Tool | What it does |
|------|-------------|
| `manage_materials` | Create PBR materials, assign, list, edit nodes, add nodes, connect/disconnect, color ramps, get node info |
| `set_texture` | Apply Poly Haven PBR texture to object |

### UV Mapping & Baking
| Tool | What it does |
|------|-------------|
| `uv_operation` | Smart UV project, lightmap pack, unwrap, create/set/list UV layers |
| `bake_textures` | Bake high-to-low poly textures: diffuse, normal, AO, roughness, combined, emit |

### Node Graph Engine
| Tool | What it does |
|------|-------------|
| `build_node_graph` | Create/replace geometry nodes, shader nodes, or compositor nodes |
| `get_node_graph` | Read back any node tree as structured JSON |
| `list_node_types` | Discover available nodes by category |

### Modifiers
| Tool | What it does |
|------|-------------|
| `modify_object` | Add, remove, apply, or configure any modifier |

### Rigging & Weights
| Tool | What it does |
|------|-------------|
| `manage_armature` | Create armatures, add/modify bones, parent meshes, IK, bone constraints |
| `manage_weights` | Vertex group assignment, auto weights, normalize, list, remove |
| `manage_shape_keys` | Blend shapes / morph targets |

### Animation
| Tool | What it does |
|------|-------------|
| `set_keyframe` | Keyframe loc/rot/scale/custom with interpolation control |
| `manage_actions` | Create, assign, list, duplicate animation actions |
| `manage_nla` | NLA tracks and strips for non-linear animation |

### Physics & Constraints
| Tool | What it does |
|------|-------------|
| `manage_physics` | Rigid body, collision, cloth, soft body |
| `manage_constraints` | Track To, Copy Rotation, Limit Location, Child Of, etc. |

### Camera & Rendering
| Tool | What it does |
|------|-------------|
| `set_camera` | Focal length, sensor, DOF, focus object/distance |
| `camera_walkthrough` | Animated camera path with waypoints and look_at targets |
| `configure_render_settings` | Engine, samples, resolution, color management, EEVEE features |
| `render_scene` | Render to file — supports `animation=True` for sequences |
| `render_region` | Render just a region around an object (10-50x faster) |

### Lighting & World
| Tool | What it does |
|------|-------------|
| `manage_lights` | List, create, set properties, change type |
| `manage_world` | HDRI, background color, environment strength |

### Snapshots
| Tool | What it does |
|------|-------------|
| `manage_snapshots` | Save, list, compare, restore, delete scene snapshots |

### Import / Export
| Tool | What it does |
|------|-------------|
| `import_model` | Import GLB, FBX, OBJ, USD, STL, ABC, PLY, DAE |
| `export_model` | Export scene or selection to any format |

### Hierarchy & Drivers
| Tool | What it does |
|------|-------------|
| `manage_hierarchy` | Parent/unparent objects, list children, hierarchy tree |
| `manage_drivers` | Scripted drivers — link properties between objects |
| `manage_custom_properties` | Set/get/list/remove custom properties on objects |

### Curves
| Tool | What it does |
|------|-------------|
| `manage_curves` | Create curves from points, edit, bevel, convert to mesh |

### Particles
| Tool | What it does |
|------|-------------|
| `manage_particles` | Emitter/hair particle systems with instance collections |

### Procedural Generation
| Tool | What it does |
|------|-------------|
| `procedural_generate` | Procedural buildings, terrain, trees, roads, rooms |

### Volume Grids (Blender 5.0+)
| Tool | What it does |
|------|-------------|
| `volume_operation` | Mesh-to-SDF, SDF boolean/offset/fillet/smooth, procedural terrain, fog volumes |

### Spatial Power Tools
| Tool | What it does |
|------|-------------|
| `batch_execute` | Combine multiple tools in one call — perception runs once at end |
| `place_relative` | Semantic placement: `in_front`, `behind`, `left_of`, `on_top`, `centered_on` |
| `create_assembly` | Multi-part furniture with proper hierarchy in one call |
| `camera_walkthrough` | Animated camera path from waypoint list with look_at targets |

### Asset Libraries (free, search + download)

| Integration | API Key | What it provides |
|-------------|---------|-----------------|
| **Poly Haven** | None (CC0) | HDRIs, PBR textures, 3D models |
| **AmbientCG** | None (CC0) | PBR materials, HDRIs, 3D models |
| **Poly Pizza** | Free key required | Low-poly CC0/CC-BY 3D models (GLB) |
| **Smithsonian 3D** | Free key (api.data.gov) | Museum-quality 3D scans (fossils, aircraft, artifacts) |
| **Sketchfab** | API key | Extensive 3D model library with auto-normalization |

| Tool | What it does |
|------|-------------|
| `get_polyhaven_status` / `get_polyhaven_categories` | Poly Haven integration status and categories |
| `search_polyhaven_assets` / `download_polyhaven_asset` | Search and download Poly Haven assets |
| `set_texture` | Apply downloaded PBR texture to object |
| `get_ambientcg_status` | AmbientCG integration status |
| `search_ambientcg_assets` / `download_ambientcg_asset` | Search and download AmbientCG materials |
| `get_sketchfab_status` | Sketchfab integration status |
| `search_sketchfab_models` / `get_sketchfab_model_preview` | Browse and preview Sketchfab models |
| `download_sketchfab_model` | Download with automatic size normalization |
| `get_polypizza_status` | Poly Pizza integration status |
| `search_polypizza_models` / `download_polypizza_model` | Search and download Poly Pizza models |
| `get_smithsonian_status` | Smithsonian 3D integration status |
| `search_smithsonian_models` / `download_smithsonian_model` | Search and download Smithsonian scans |

### AI 3D Generation

| Integration | What it does |
|-------------|-------------|
| **Hyper3D Rodin** | Text-to-3D and image-to-3D via cloud API |
| **Hunyuan3D** | Text/image-to-3D via Tencent's model |
| **Trellis2** | Image-to-3D via local inference |

For local inference, we recommend these forks which support both CUDA and Apple Silicon (MLX/Metal):
- [trellis2-apple](https://github.com/pedronaugusto/trellis2-apple) — local HTTP server, MLX backend for macOS
- [hunyuan3d-apple](https://github.com/pedronaugusto/hunyuan3d-apple) — local HTTP server, MLX backend for macOS

| Tool | What it does |
|------|-------------|
| `get_hyper3d_status` / `generate_hyper3d_model_via_text` / `generate_hyper3d_model_via_images` | Hyper3D generation |
| `poll_rodin_job_status` / `import_generated_asset` | Poll and import Hyper3D results |
| `get_hunyuan3d_status` / `generate_hunyuan3d_model` | Hunyuan3D generation |
| `poll_hunyuan_job_status` / `import_generated_asset_hunyuan` | Poll and import Hunyuan3D results |
| `get_trellis2_status` / `generate_trellis2_model` | Trellis2 generation |
| `poll_trellis2_job_status` | Poll Trellis2 progress |

## Blender 5.0 Support

BlenderWeave auto-detects Blender version and handles breaking changes transparently. New Blender 5 features include EEVEE ray tracing, ACES color management, and volume/SDF operations.

## AI Setup

See [CLAUDE.md](CLAUDE.md) for optimal AI workflow guidelines — feedback strategy, tool priority, safety patterns, and material editing best practices.

For Claude Code users with the plugin installed, the bundled agent and Perspicacity skill provide enhanced spatial reasoning automatically.

## Troubleshooting

- **"No MCP server running"** — start your AI client first (it creates the server). The addon auto-discovers it.
- **Timeout errors** — break complex operations into smaller steps
- **First command fails** — normal on cold start, retry and it works
- **Blender restart** — the addon auto-reconnects, no need to restart the AI client
- **Multiple AI sessions** — use the Server dropdown in the BlenderWeave panel to pick which one
- **Restart both** — if things break, restart both the AI client and Blender

## Contributing

Contributions welcome.

## License

MIT — Pedro Augusto
