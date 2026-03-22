"""Hierarchy subsystem — parent chain computation."""

from ..perception_registry import register


def _compute_hierarchy(mesh_objects):
    """Compute parent chain for each object (leaf-first)."""
    entries = []
    for obj, data in mesh_objects:
        if obj.parent:
            chain = []
            current = obj
            while current:
                chain.append(current.name)
                current = current.parent
            entries.append({"object": data["name"], "chain": chain})
    return entries


def compute(ctx):
    if not ctx.include_flags.get("hierarchy"):
        return {}
    return {"hierarchy": _compute_hierarchy(ctx.mesh_objects)}


register("hierarchy", compute, emits=["hierarchy"])
