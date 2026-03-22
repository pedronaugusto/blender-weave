# BlenderWeave — Claude Code Instructions

## Feedback Strategy

Scene perception is always-on. Every modifying command returns a compact DSL with depth-sorted objects, spatial relationships, light analysis, shadow footprints, material predictions, spatial facts, and multi-view ray grids.

| When | Tool |
|---|---|
| After every change | Auto-attached perception DSL (no call needed) |
| Explicit spatial query | `get_scene_perception` |
| Quick diff check | `get_scene_delta` |
| Visual glance | `get_viewport_thumbnail` |
| Check specific object/material | `render_region(object_name=...)` |
| User says "show me" / final review | `get_viewport_screenshot` |

Never use `analyze_scene` for routine checks — it sends a full screenshot.

## Spatial Intelligence

The perception DSL auto-attached to every command gives you:
- `OBJ` lines: depth-sorted, mesh AABB center position, coverage, quadrant, material info, `dim=[w,h,d]`, `rot=[rx,ry,rz]` (euler degrees), `facing=N|NE|E|...` (compass), `toward=ObjectName` (facing context), `zone=name`, `transparent` flag, `has_uv`/`no_uv`, visible face, `lum=` (luminance), containment, mesh quality flags
- `VERIFY` lines: post-transform mechanical verification (ONLY on failure). Catches hierarchy bugs where parent moved but mesh didn't. Also catches `rotation_not_inherited` when children don't inherit parent rotation.
- `REL` lines: pairwise distance, direction (camera-relative), `overlap=` (screen-space), `aabb_overlap=` (world-space, camera-independent), occlusion %
- `SPATIAL` lines: objective spatial facts — `bbox_below_surface`, `bbox_extends_into`, `surface_intersect` (center at surface level, half inside), `scale_diagonal`, `scale_ratio`, `no_material_slots`, `near_plane`, `inside_bbox`, `no_ground_below`, `no_light_sources`, `energy_zero`, `off_camera`, `zero_dimensions`
- `ASSEMBLY` lines: co-located multi-type objects forming a unit (e.g., bulb+filament+wire). Lists all members — check when duplicating/deleting.
- `HARMONY` line: material distribution summary — types, temperature (warm/cool/neutral/mixed)
- `LIT` lines: light-surface angle, normalized + raw intensity, shadow casters
- `SHAD` lines: per-light shadow footprint, coverage %, casters, contact shadow
- `MAT` lines: appearance prediction, requirements, warnings
- `COMP` lines: thirds score, balance, depth layer distribution, edge proximity
- `RAY` lines: camera ray grid coverage map (12x12, object hit percentages)
- `MVIEW` lines: top view (XY positions + floor-plane overlap), front view (floor/mid/ceiling tiers), light-POV coverage
- `HIER` lines: parent chain (child > parent > grandparent)
- `GRP` lines: collection/group membership
- `PHYS` lines: rigid body type, mass, sleeping state
- `ANIM` lines: active action, current frame, play state

Use this to reason spatially without screenshots. Example: "Move vase so it doesn't block key light on wall" — REL, LIT, and SHAD lines tell you exactly where things are and what's casting shadows.

## SPATIAL Facts Reasoning

SPATIAL lines are **objective measurements**, not judgments. Use context to interpret:
- `inside_bbox` + OBJ has `transparent` flag → Expected (light in glass)
- `inside_bbox` + OBJ is opaque → Problem (trapped light)
- `bbox_below_surface` pct > 25% → Problem (sunk object)
- `bbox_below_surface` pct < 5% → Expected (resting contact)
- `no_material_slots` + coverage > 2% → Warning (renders grey)
- `no_light_sources` → Problem (scene is black)
- `no_ground_below` → Check if object is meant to float (lamp, bird) or not (chair)

## VERIFY Protocol

After every modifying tool call, check for VERIFY FAIL lines. These indicate the transform mechanically failed:
- **Parent moved but mesh didn't** — Sketchfab hierarchy bug. Fix: use `recursive=True`
- **NaN/Inf values** — degenerate transform. Undo and retry differently
- VERIFY is silent on success — no output means transform worked

## Sketchfab Import Protocol

Sketchfab models import as deep empty hierarchies. Always:
- Use `transform_object(recursive=True)` for any Sketchfab-imported object — this forces depsgraph update so children inherit transforms
- Use `look_at` parameter for orientation: `transform_object(object_name="Chair", look_at=[0,0,0], recursive=True)`
- `delete_object` now recursively deletes all descendants (bottom-up) — no more orphaned children
- Check `mesh_world_center` in `get_object_info` to see where mesh geometry actually is
- OBJ positions in perception use mesh AABB center, not parent empty origin

## Camera Bias Awareness

Screen-space metrics (`coverage%`, `overlap=`, `occ=`) change when the camera moves. World-space metrics (`dim=`, `aabb_overlap=`, `distance`, SPATIAL facts) don't. For placement and physics reasoning, prefer world-space metrics. For composition and framing, use screen-space.

## Hierarchy & Drivers

- `manage_hierarchy(action="parent", object_name="Lid", parent_name="Pot")` — parent/child
- `manage_hierarchy(action="list_tree", object_name="Root")` — full hierarchy
- `manage_drivers(action="add_simple", ...)` — link properties between objects
- `manage_custom_properties(action="set", ...)` — store metadata on objects

## Safety

- `save_file()` before booleans, modifier applies, material rewiring
- `manage_snapshots(action="save", name="before_X")` before major changes
- `undo()` on failure, then `get_scene_delta()` to verify

## Material Editing

Use structured actions, not `execute_blender_code`. Create materials with PBR values in one call:

```
manage_materials(action="create", material_name="WoodFloor", color=[0.3, 0.15, 0.08], roughness=0.4, metallic=0.0,
                 properties={"specular": 0.3, "normal_strength": 0.8})
manage_materials(action="get_node_info", material_name="Wood", node_name="Color Ramp")
manage_materials(action="edit_node", material_name="Wood", node_name="Noise Texture", input_name="Scale", value=12.0)
manage_materials(action="edit_color_ramp", material_name="Wood", node_name="Color Ramp",
                 stops=[{"position": 0.0, "color": [0.1, 0.05, 0.02]}, {"position": 1.0, "color": [0.4, 0.2, 0.1]}])
manage_materials(action="add_node", material_name="Wood", node_type="ShaderNodeMixRGB", location=[-200, 0])
manage_materials(action="connect", material_name="Wood", from_node="Mix", from_socket="Color", to_node="Principled BSDF", to_socket="Base Color")
```

## Lighting

- `manage_lights(action="list")` — see all lights
- `manage_lights(action="set_properties", light_name="Key", energy=500, color=[1, 0.95, 0.9])`
- `manage_lights(action="change_type", light_name="Fill", new_type="AREA")` — in-place type change
- Perception auto-feedback after adjustments verifies everything automatically

## Rendering

- Iteration: `render_region(object_name="Bottle", resolution=512)`
- Final still: `render_scene(output_path=..., samples=256)`
- Animation: `render_scene(output_path="/tmp/frames/", animation=True, frame_start=1, frame_end=120, format="PNG")`
- Camera walkthrough: `camera_walkthrough(waypoints=[{"location": [5,-5,2], "look_at": [0,0,1]}, ...])`
- Use `BLENDER_EEVEE` for Blender 5+ (BLENDER_EEVEE_NEXT also accepted)

## World

- `manage_world(action="set_hdri", filepath="...", strength=1.0)`
- `manage_world(action="set_color", color=[0.05, 0.05, 0.05])`

## Viewport

- `set_viewport(action="lock_camera", locked=True)`
- `set_viewport(action="set_view", view="CAMERA")`
- `set_viewport(action="frame_selected")`

## Full Tool Coverage

All BlenderWeave tools are structured. Key categories:
- **Object ops**: create_object, get_object_info, duplicate_object, delete_object, transform_object, batch_transform, modify_object, place_relative
- **Batch**: batch_execute (multi-tool single round-trip)
- **Assembly**: create_assembly (dining_chair, table, sofa, floor_lamp, bookshelf)
- **Materials**: manage_materials, build_node_graph, get_node_graph, list_node_types, set_texture, bake_textures
- **Lighting**: manage_lights, set_camera, manage_world
- **Mesh**: mesh_operation, uv_operation, manage_curves, volume_operation
- **Procedural**: procedural_generate (buildings, terrain, trees, roads, rooms), generate_lod_chain, generate_collision_mesh
- **Render**: render_scene, render_region, configure_render_settings, get_viewport_thumbnail, get_viewport_screenshot
- **Viewport**: set_viewport, set_viewport_shading, analyze_scene
- **Animation**: set_keyframe, manage_actions, manage_nla, manage_drivers, set_frame
- **Physics**: manage_physics, manage_particles, manage_constraints
- **Rigging**: manage_armature, manage_weights, manage_shape_keys
- **Scene**: manage_collections, manage_hierarchy, manage_selection, manage_custom_properties, manage_snapshots
- **File**: save_file, open_file, import_model, export_model, undo, redo
- **Assets**: Poly Haven (CC0 HDRIs/textures), AmbientCG (CC0 PBR materials), Sketchfab (3D models), Poly Pizza (low-poly CC0), Smithsonian 3D (museum scans CC0); generate via Hyper3D, Trellis2, Hunyuan3D
- **Perception**: get_scene_info, get_scene_perception, get_scene_delta

## Spatial Power Tools

### Batch Execute
Combine multiple tool calls into a single round-trip. Perception runs once at end.
```
batch_execute(commands=[
    {"tool": "create_object", "params": {"type": "CUBE", "name": "Island", "dimensions": [1.8,0.7,0.84]}},
    {"tool": "manage_materials", "params": {"action": "create", "material_name": "Marble"}},
    {"tool": "manage_materials", "params": {"action": "assign", "object_name": "Island", "material_name": "Marble"}},
])
```

### Room Builder
Watertight interior rooms via `procedural_generate(action="create_room")`. Inward normals, wall thickness, door/window openings, UV unwrapped, origin at floor center.
```
procedural_generate(action="create_room", width=10, depth=8, height=3, wall_thickness=0.15,
    openings=[{"wall": "+x", "type": "door", "width": 1.0, "height": 2.2}])
```

### Place Relative
Semantic object placement — no coordinate math.
```
place_relative(object_name="CoffeeTable", relative_to="Sofa", relation="in_front", distance=0.8, facing="toward")
```
Relations: `in_front`, `behind`, `left_of`, `right_of`, `on_top`, `below`, `centered_on`

### Create Assembly
Multi-part furniture with proper hierarchy. One call, one parent, all parts parented.
```
create_assembly(type="dining_chair", name="Chair_0", location=[1, -0.5, 0], facing_direction=[0, 1])
```
Types: `dining_chair`, `table`, `sofa`, `floor_lamp`, `bookshelf`

## Priority

1. Structured tools over `execute_blender_code`
2. Auto-perception (always on) over manual `get_scene_perception`
3. `manage_lights` over `create_object` for light changes
4. `render_region` over `render_scene` for iteration
5. `manage_snapshots` before destructive operations
6. `manage_hierarchy` for parent/child over raw bpy
7. `manage_curves` for curve ops over `execute_blender_code`
8. World-space metrics (`dim=`, `aabb_overlap=`) over screen-space for placement reasoning
