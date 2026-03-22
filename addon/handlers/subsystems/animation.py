"""Animation subsystem — action and playback state computation."""

import bpy

from ..perception_registry import register


def _compute_animation_states(mesh_objects, scene):
    """Compute animation state for objects with active actions."""
    # Check if animation is actually playing back globally
    is_playing = False
    try:
        for screen in bpy.data.screens:
            if screen.is_animation_playing:
                is_playing = True
                break
    except Exception:
        pass

    states = []
    for obj, data in mesh_objects:
        ad = obj.animation_data
        if ad and ad.action:
            act = ad.action
            start, end = act.frame_range
            current = scene.frame_current
            in_range = start <= current <= end
            states.append({
                "name": data["name"],
                "action": act.name,
                "frame": current,
                "frame_total": int(end),
                "playing": is_playing and in_range,
            })
    return states


def compute(ctx):
    if not ctx.include_flags.get("animation"):
        return {}
    return {"animation_states": _compute_animation_states(ctx.mesh_objects, ctx.scene)}


register("animation", compute, emits=["animation_states"])
