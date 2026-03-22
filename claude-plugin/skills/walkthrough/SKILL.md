---
name: walkthrough
description: Plan and render a camera walkthrough animation
user_invocable: true
---

Create an automated camera walkthrough:

1. Analyze scene layout via `get_scene_perception` (MVIEW top view)
2. Plan 4-6 waypoints visiting key areas
3. Set up camera path via `camera_walkthrough`
4. Preview first and last frames via `render_region`
5. Ask user to confirm or adjust waypoints
6. Render animation to PNG sequence
7. Report output directory and frame count
