"""Groups subsystem — collection membership computation."""

import bpy

from ..perception_registry import register


def _compute_groups():
    """Compute collection membership for visible objects."""
    groups = []
    for col in bpy.data.collections:
        members = [o.name for o in col.objects if o.visible_get()]
        if members:
            groups.append({"name": col.name, "members": members})
    return groups


def compute(ctx):
    if not ctx.include_flags.get("hierarchy"):
        return {}
    return {"groups": _compute_groups()}


register("groups", compute, emits=["groups"])
