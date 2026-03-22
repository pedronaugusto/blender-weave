import bpy
import mathutils
from ..perception_registry import register

def compute(ctx):
    """Detect object assemblies — co-located objects that form a unit."""
    assemblies = []
    processed = set()

    for obj, data in ctx.mesh_objects:
        if obj.name in processed:
            continue

        # Check if this object has siblings (same parent) of different types
        parent = obj.parent
        if not parent:
            continue

        siblings = []
        for child in parent.children:
            if child.visible_get():
                siblings.append(child)

        # Need at least 3 siblings to form a meaningful assembly
        types = set(s.type for s in siblings)
        if len(siblings) < 3:
            continue

        # Compute center
        positions = [s.matrix_world.translation for s in siblings]
        center = sum(positions, mathutils.Vector((0, 0, 0))) / len(positions)

        members = [s.name for s in siblings]
        for m in members:
            processed.add(m)

        assemblies.append({
            "name": parent.name,
            "members": members,
            "member_count": len(members),
            "types": sorted(types),
            "center": [round(center.x, 2), round(center.y, 2), round(center.z, 2)],
        })

    # Also detect proximity-based assemblies (no shared parent)
    # Objects within 0.1m with different types
    if ctx.spatial_grid:
        for obj, data in ctx.mesh_objects:
            if obj.name in processed:
                continue
            wc = data.get("world_center", [0, 0, 0])
            neighbors = ctx.spatial_grid.query_radius(wc, 0.1) if hasattr(ctx.spatial_grid, 'query_radius') else ctx.spatial_grid.neighbors(wc, radius=0.1)

            nearby = []
            for n_obj, n_data in neighbors:
                if n_obj.name == obj.name or n_obj.name in processed:
                    continue
                nearby.append(n_obj)

            if len(nearby) >= 2:  # need ≥3 total members for a meaningful assembly
                members = [obj.name] + [n.name for n in nearby]
                types = set([obj.type] + [n.type for n in nearby])
                positions = [obj.matrix_world.translation] + [n.matrix_world.translation for n in nearby]
                center = sum(positions, mathutils.Vector((0, 0, 0))) / len(positions)

                for m in members:
                    processed.add(m)

                assemblies.append({
                    "name": f"Assembly_{obj.name}",
                    "members": members,
                    "member_count": len(members),
                    "types": sorted(types),
                    "center": [round(center.x, 2), round(center.y, 2), round(center.z, 2)],
                })

    # Filter: skip assemblies where all members are already in a SGROUP
    sgroup_members = set()
    for sg in ctx.result.get("semantic_groups", []):
        for m in sg.get("members", []):
            sgroup_members.add(m)

    filtered = []
    for asm in assemblies:
        members_in_sgroup = sum(1 for m in asm["members"] if m in sgroup_members)
        if members_in_sgroup < len(asm["members"]):
            filtered.append(asm)  # Keep if at least one member isn't in a SGROUP

    return {"assemblies": filtered} if filtered else {}

register("assembly_detect", compute, phase="post", emits=["assemblies"])
