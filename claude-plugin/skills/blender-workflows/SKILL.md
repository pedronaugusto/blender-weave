---
name: blender-workflows
description: Common Blender workflow patterns for BlenderWeave — game-ready pipelines, scene building, iteration loops, import/export, and production techniques.
---

# Blender Workflow Patterns

Proven sequences for common 3D tasks via BlenderWeave tools.

## Scene Building

### Room/Environment Setup
1. Create floor: `create_object(type="PLANE", size=10, name="Floor")`
2. Create walls: `create_object(type="CUBE")` + `transform_object` to position/scale as thin slabs
3. Apply materials: `manage_materials(action="create", name="Concrete", base_color=[0.5,0.5,0.5], roughness=0.8)` + `manage_materials(action="assign")`
4. Add lights: `manage_lights(action="set_properties")` — start with one key light, add fill after checking perception
5. Check perception after each step — SPATIAL lines catch floating objects, missing lights, overlaps

### Object Placement Loop
1. Create or import object
2. `transform_object` to position
3. Read DELTA — confirms placement
4. Read REL lines — verify spatial relationships (distance, contact)
5. Read LIT/SHAD lines — verify lighting on new object
6. Adjust and repeat

## Game-Ready Pipeline

### Full Export Workflow
1. Model at high poly
2. `uv_operation(action="smart_project")` — UV unwrap
3. `generate_lod_chain(object_name=..., ratios=[0.5, 0.25, 0.1])` — LOD levels
4. `generate_collision_mesh(object_name=..., type="CONVEX_HULL")` — collision
5. `bake_textures(type="NORMAL", resolution=2048)` — bake maps
6. `export_model(format="GLB")` — export

### Texture Baking
1. Create high-poly and low-poly versions
2. UV unwrap the low-poly: `uv_operation(action="smart_project", object_name="LowPoly")`
3. Bake: `bake_textures(type="NORMAL", high_poly="HighPoly", low_poly="LowPoly", resolution=2048)`
4. Repeat for AO, roughness as needed

## Iteration Patterns

### Material Iteration
1. Create material: `manage_materials(action="create", ...)`
2. Assign to object: `manage_materials(action="assign", ...)`
3. Quick check: `render_region(object_name="...", resolution=512)` — 10-50x faster than full render
4. Adjust: `manage_materials(action="edit_node", ...)`
5. Repeat render_region until satisfied
6. Final: `render_scene(samples=256)` for full quality

### Lighting Iteration
1. Set up lights with `manage_lights`
2. Check LIT/SHAD lines in perception — shows angles, intensity, shadows
3. Adjust energy/position: `manage_lights(action="set_properties", ...)`
4. Read DELTA — confirms what changed
5. `render_region` on key object for visual check
6. Repeat

## Safety Workflow

### Before Destructive Operations
```
save_file()
manage_snapshots(action="save", name="before_boolean")
mesh_operation(action="boolean", ...)
# If result is bad:
manage_snapshots(action="restore", name="before_boolean")
```

### Undo Recovery
```
undo()
get_scene_delta()  # Verify rollback
```

## Import/Export

### Import and Normalize
1. `import_model(filepath="...", format="GLB")`
2. Check perception — object may be huge/tiny/offset
3. `transform_object` to normalize position/scale
4. `manage_materials(action="list")` — check imported materials

### Multi-Format Export
```
export_model(format="GLB", filepath="model.glb")
export_model(format="FBX", filepath="model.fbx")
export_model(format="USD", filepath="model.usd")
```

## Rigging Workflow

1. Create armature: `manage_armature(action="create", name="Rig")`
2. Add bones: `manage_armature(action="add_bone", name="Spine", head=[0,0,0], tail=[0,0,0.5])`
3. Build chain: repeat for chest, neck, head, arms, legs
4. Parent mesh: `manage_armature(action="parent_mesh", armature="Rig", mesh="Character", type="AUTOMATIC")`
5. Test weights: `manage_weights(action="list", object_name="Character")`
6. Adjust: `manage_weights(action="assign", ...)` for problem areas

## Procedural Workflows

### Scatter Objects
1. Create base object and instance object
2. `manage_particles(action="create", object_name="Ground", type="EMITTER")`
3. Set instance collection for scattering
4. Adjust count, scale randomness via particle settings

### Geometry Nodes
1. `build_node_graph(target="Object", node_tree_type="GeometryNodes", nodes=[...], links=[...])`
2. Preview: `render_region(object_name="...")`
3. `get_node_graph(target="Object")` to inspect current state
