---
name: fill
description: Analyze empty space and suggest items to fill the room
user_invocable: true
---

Identify empty areas and suggest additions:

1. Read MVIEW top from `get_scene_perception`
2. Identify occupied vs empty floor areas
3. Based on room type, suggest missing items
4. Present suggestions with positions
5. Execute user-approved placements
