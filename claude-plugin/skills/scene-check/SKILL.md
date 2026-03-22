---
name: scene-check
description: Run Scene Doctor to diagnose and fix scene issues
user_invocable: true
---

Run a comprehensive scene check using perception data:

1. Call `get_scene_perception` with all analysis enabled
2. Parse ALL DSL line types looking for issues:
   - VERIFY FAIL → transform failures (critical)
   - SPATIAL surface_intersect → objects embedded in surfaces
   - SPATIAL bbox_below_surface pct > 25% → sunk objects
   - SPATIAL no_material_slots → grey/untextured objects
   - SPATIAL no_light_sources → dark scene
   - SPATIAL no_ground_below → potentially floating objects
   - ASSEMBLY → co-located parts (info for duplicating)
   - HARMONY → material consistency report
3. Group by severity: Critical > Warning > Info
4. Report findings with fix suggestions
5. Ask before applying any fixes
