---
name: materials
description: Auto-create and apply materials to unmaterialed objects
user_invocable: true
---

Find and fix objects without materials:

1. Run `get_scene_perception` to find `no_material_slots` SPATIAL facts
2. For each unmaterialed object:
   - Infer material type from object name
   - Create appropriate PBR material
   - Assign to object
3. Report what was created and applied
4. Show HARMONY summary
