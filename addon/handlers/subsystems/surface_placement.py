import mathutils
from ..perception_registry import register

def compute(ctx):
    """Detect objects placed at surfaces where center is AT surface level (half inside)."""
    if not ctx.include_flags.get("constraints"):
        return {}
    facts = []

    for obj, data in ctx.mesh_objects:
        dims = data.get("dimensions")
        wc = data.get("world_center")
        if not dims or not wc:
            continue

        half_height = dims[2] / 2  # Z half-extent
        center_z = wc[2]
        bottom_z = center_z - half_height

        # Check against surfaces: other objects' top_z
        candidates = (
            ctx.spatial_grid.neighbors(wc, radius=2.0)
            if ctx.spatial_grid and hasattr(ctx.spatial_grid, 'neighbors')
            else ctx.mesh_objects
        )

        for other_obj, other_data in candidates:
            if other_obj.name == obj.name:
                continue

            other_top = other_data.get("top_z")
            other_dims = other_data.get("dimensions")
            if other_top is None or not other_dims:
                continue

            # Surface must be roughly horizontal (wider than tall)
            if other_dims[2] > max(other_dims[0], other_dims[1]) * 0.5:
                continue  # Not a horizontal surface

            # Check if object center is within 0.1m of surface top
            if abs(center_z - other_top) < 0.1:
                # Object center is near the surface — check for intersection
                if bottom_z < other_top - 0.05:  # 5cm threshold — skip flush surfaces
                    depth = other_top - bottom_z
                    suggest_z = center_z + depth
                    facts.append({
                        "object": data["name"],
                        "type": "surface_intersect",
                        "details": {
                            "surface": other_data["name"],
                            "depth": round(depth, 3),
                            "suggest_z": round(suggest_z, 3),
                        }
                    })

    if not facts:
        return {}

    # Suppress between co-located objects (ASSEMBLY/SGROUP members)
    co_located = set()
    for asm in ctx.result.get("assemblies", []):
        members = asm.get("members", [])
        for i, a in enumerate(members):
            for b in members[i+1:]:
                co_located.add((a, b))
                co_located.add((b, a))
    for sg in ctx.result.get("semantic_groups", []):
        members = sg.get("members", [])
        for i, a in enumerate(members):
            for b in members[i+1:]:
                co_located.add((a, b))
                co_located.add((b, a))

    if co_located:
        facts = [f for f in facts
                 if (f["object"], f.get("details", {}).get("surface", "")) not in co_located]

    # Merge with existing spatial facts
    existing = ctx.result.get("spatial_facts", [])
    return {"spatial_facts": existing + facts} if facts else {}

register("surface_placement", compute, phase="post",
         depends_on=["spatial_facts"], emits=["spatial_facts"])
