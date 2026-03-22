---
name: render
description: Set up and execute a render of the current camera view
user_invocable: true
---

Quick render from current camera:

1. Check scene state via `get_scene_perception`
2. Verify camera exists and is positioned
3. Choose engine:
   - EEVEE for speed (no glass/SSS)
   - Cycles for quality (glass, SSS, complex lighting)
4. Set appropriate samples:
   - EEVEE: 64 samples
   - Cycles: 128-256 samples based on complexity
5. Render to `/tmp/blenderweave_render_[timestamp].png`
6. Report output path
