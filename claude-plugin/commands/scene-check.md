---
name: scene-check
description: Run scene perception and report render readiness
user_invocable: true
---

# Scene Check

Run a full scene perception analysis and report render readiness.

## Instructions

1. Call `mcp__blender-weave__get_scene_perception` to get the full scene DSL output.

2. Parse the output and report the following sections:

### Objects
- Total object count (from OBJ lines)
- Note `dim=[w,h,d]` for key objects — flag any with extreme dimensions (>50m or <0.005m diagonal)
- Note any objects with `no_uv` that have textures assigned
- Note any objects with `flipped_normals` or `non_manifold` flags

### Spatial Facts
- Parse all SPATIAL lines and classify each:
  - **PROBLEM**: `bbox_below_surface` pct>25%, `no_light_sources`, `scale_ratio` >50:1, `inside_bbox` with opaque container
  - **WARNING**: `no_material_slots` on visible objects, `energy_zero`, `near_plane`, `no_ground_below`, `scale_diagonal` extremes
  - **EXPECTED**: `inside_bbox` with `transparent` container, `bbox_below_surface` pct<5%, `off_camera`
- Use `transparent` flag on OBJ lines to determine if containment is intentional
- Present as structured list: `[PROBLEM]`, `[WARNING]`, `[EXPECTED]`

### Lighting
- Count of lights (from LIGHT lines)
- If zero lights and no HDRI: flag as "No lights in scene — render will be black" (SPATIAL `no_light_sources` confirms)
- Check light intensities — flag any `energy_zero` SPATIAL facts
- Report shadow coverage from SHAD lines
- Report WORLD line (bg color/HDRI, strength)

### Materials
- Count materials from MAT lines
- Flag any MAT lines with "needs" notes — these materials have unmet requirements
- Note any OBJ lines with `no_uv` that need textures
- Note any objects without materials (SPATIAL `no_material_slots`)

### Camera
- Report camera position and lens from CAM lines
- Report composition score from COMP lines if available
- Flag if no camera exists in the scene
- Note any `near_plane` SPATIAL facts

### Performance
- Report any objects with very high polygon counts
- Note total object count vs visible count

### Verdict

Based on the analysis, give one of:
- **Ready to render** — No problems, lighting and camera are set up
- **Needs work** — List the specific items that must be fixed before rendering, ordered by priority:
  1. Problems (from SPATIAL analysis)
  2. Unmet material requirements
  3. Warnings worth addressing

Keep the report concise. Use a checklist format where possible.
