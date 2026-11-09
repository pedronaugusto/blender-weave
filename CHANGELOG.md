# Changelog

## v1.1.0

### Blender's documentation, built in
- `search_blender_api` / `get_blender_api`: the connected Blender's Python API read from the running Blender itself:
  every type with its own properties (types, enum items, defaults, units), functions with parameters and returns,
  every operator, the Python modules, and every shader, geometry and compositor node's sockets with defaults
- `search_blender_manual` / `get_blender_manual`: the Blender manual for the same version, fetched once as text
  (CC BY-SA 4.0, the Blender Foundation's), split into sections and searched
- Built and cached per version in `~/.blenderweave/docs/`; nothing of Blender's is shipped

### Window, navigation, the .blend, background jobs
- `get_window_screenshot`, `get_area_screenshot` (any editor), fitted to a byte budget; `get_window_layout`
- `jump_to_workspace`, `jump_to_object`
- `get_blendfile_summary`, `get_blendfile_paths` (missing files), `get_linked_libraries`
- `run_blender_background`, `get_background_job`, `cancel_background_job`: scripts in a fresh headless Blender

### Better
- `execute_blender_code`: stderr captured, a `result` value returned, full tracebacks, an optional persistent namespace
- An error Blender reports no longer drops the connection (every later call failed until it reconnected)
- Every reply is JSON-safe (vectors, matrices, colours, sets, datablocks)
- The first camera created becomes the scene's camera, as Blender's Add menu does

### Blender 5.2
- `manage_actions` and keyframe interpolation read layered actions' channel bags
- `volume_operation` sets Mesh to Volume's resolution on its menu input
- `generate_lod_chain` works on meshes with shape keys (it decimates the evaluated mesh)

### Tests
- `tests/test_docs.py`, `tests/test_transport.py` without Blender; `tests/e2e_new_tools.py`, `tests/e2e_smoke.py`
  (69 structured calls) against a headless Blender 5.2; `tests/e2e_window.py` with a window


## v1.0.0 — BlenderWeave

### Scene Perception (always-on spatial intelligence)
- `get_scene_perception` — full 3D spatial intelligence, auto-attached to every modifying command
- Perspicacity DSL output: depth-sorted objects, spatial relationships, light analysis, shadow footprints, material predictions, spatial facts
- Auto-delta: every modifying command computes DELTA between previous and current perception
- VERIFY lines: post-transform mechanical verification catches hierarchy bugs
- SPATIAL lines: objective spatial facts (intersections, floating objects, missing materials, scale issues)
- 20 perception subsystems with auto-discovery registry
- Configurable budget caps for all line types
- Smart mode: auto-tuned perception radius from scene AABB, materials included
- 12x12 camera ray grid, multi-view coverage (top/front/light-POV)
- Semantic groups (SGROUP), assemblies, containment detection, material harmony analysis

### 90+ Structured Tools
- Object CRUD, mesh operations, materials, UV, baking, LOD/collision
- Rigging (armature, weights, shape keys), animation (actions, NLA)
- Physics, constraints, procedural generation (buildings, terrain, trees, roads, rooms)
- Node graph engine (geometry, shader, compositor nodes)
- `render_region` — render single object at high quality (10-50x faster)
- Scene snapshots — save/compare/restore transforms, materials, lights, camera
- Hierarchy, drivers, custom properties, curves, particles, volumes (Blender 5.0+)
- `batch_execute` — multi-tool single round-trip with undo grouping
- `place_relative` — semantic object placement
- `create_assembly` — multi-part furniture in one call

### Asset Integrations
- Poly Haven (CC0 HDRIs, PBR textures, 3D models)
- AmbientCG (CC0 PBR materials, HDRIs)
- Sketchfab (3D models with auto-normalization)
- Poly Pizza (CC0 low-poly models)
- Smithsonian 3D (CC0 museum scans)

### AI 3D Generation
- Hyper3D Rodin (text/image to 3D)
- Hunyuan3D (local or official API)
- Trellis2 (local API)

### Claude Code Plugin
- `claude-plugin/` — bundles MCP server, agents, hooks, commands, and Perspicacity skill
- 8 specialized agents: blender-weave, scene-doctor, space-planner, material-designer, render-director, qa-auditor, scene-analyst, project-wizard
- Safety hooks: PreToolUse guards for destructive ops, PostToolUse perception checks
- Perspicacity skill for DSL reasoning

### Blender 5 Compatibility
- EEVEE engine rename handled automatically
- EEVEE ray tracing and ACES color management support
- Volume/SDF operations (Blender 5.0+)
