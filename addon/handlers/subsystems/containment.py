"""Containment detection subsystem — objects inside other objects."""

import mathutils

from ..perception_registry import register


def _compute_containment(mesh_objects, scene, depsgraph):
    """Detect objects fully or partially contained inside other objects.

    Phase 1: AABB containment check (all 8 corners of A inside B's AABB).
    Phase 2: Raycast confirmation (6 axis-aligned rays from inner center).
    """
    import mathutils

    if len(mesh_objects) < 2:
        return []

    # Pre-compute world AABBs
    aabbs = {}
    for obj, data in mesh_objects:
        try:
            corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
            min_c = mathutils.Vector([min(c[i] for c in corners) for i in range(3)])
            max_c = mathutils.Vector([max(c[i] for c in corners) for i in range(3)])
            aabbs[data["name"]] = (obj, data, min_c, max_c, corners)
        except Exception:
            continue

    containment = []

    def _test_containment(outer_name, outer_obj, o_min, o_max,
                          inner_name, inner_obj, i_min, i_max, i_corners):
        """Test if inner is contained in outer. Appends to containment list if so."""
        # Quick reject: inner must be smaller
        inner_diag = (i_max - i_min).length
        outer_diag = (o_max - o_min).length
        if inner_diag >= outer_diag * 0.95:
            return

        # AABB containment: all 8 corners of inner inside outer AABB
        if not all(o_min.x <= c.x <= o_max.x and
                   o_min.y <= c.y <= o_max.y and
                   o_min.z <= c.z <= o_max.z
                   for c in i_corners):
            return

        # Center-distance rejection
        inner_center = (i_min + i_max) / 2
        outer_center = (o_min + o_max) / 2
        if (inner_center - outer_center).length > outer_diag * 0.4:
            return

        # Raycast confirmation: 6 axis-aligned rays from inner center
        directions = [
            mathutils.Vector((1, 0, 0)), mathutils.Vector((-1, 0, 0)),
            mathutils.Vector((0, 1, 0)), mathutils.Vector((0, -1, 0)),
            mathutils.Vector((0, 0, 1)), mathutils.Vector((0, 0, -1)),
        ]
        hits_outer = 0
        for d in directions:
            try:
                origin = inner_center.copy()
                for _bounce in range(10):
                    hit, loc, normal, idx, hit_obj, matrix = scene.ray_cast(
                        depsgraph, origin, d, distance=100.0
                    )
                    if not hit or not hit_obj:
                        break
                    if hit_obj.name == outer_obj.name:
                        hits_outer += 1
                        break
                    origin = loc + d * 0.001
            except Exception:
                pass

        if hits_outer >= 4:
            mode = "full" if hits_outer == 6 else "partial"
            containment.append({
                "outer": outer_name, "inner": inner_name,
                "mode": mode, "ray_hits": hits_outer,
            })

    # Use spatial grid for large scenes — O(n*k) instead of O(n^2)
    try:
        from .._utils import SpatialGrid
    except ImportError:
        SpatialGrid = None

    if SpatialGrid and len(aabbs) > 30:
        grid = SpatialGrid(cell_size=2.0)
        for name, entry in aabbs.items():
            min_c, max_c = entry[2], entry[3]
            center = [(min_c[i] + max_c[i]) / 2 for i in range(3)]
            grid.insert(name, entry, center)

        checked = set()
        for outer_name, (outer_obj, outer_data, o_min, o_max, _) in aabbs.items():
            center = [(o_min[i] + o_max[i]) / 2 for i in range(3)]
            outer_diag = (o_max - o_min).length
            for inner_name, (inner_obj, inner_data, i_min, i_max, i_corners) in grid.neighbors(center, radius=max(outer_diag, 3.0)):
                if outer_name == inner_name:
                    continue
                pair = (outer_name, inner_name)
                if pair in checked:
                    continue
                checked.add(pair)
                _test_containment(outer_name, outer_obj, o_min, o_max,
                                  inner_name, inner_obj, i_min, i_max, i_corners)
    else:
        for outer_name, (outer_obj, outer_data, o_min, o_max, _) in aabbs.items():
            for inner_name, (inner_obj, inner_data, i_min, i_max, i_corners) in aabbs.items():
                if outer_name == inner_name:
                    continue
                _test_containment(outer_name, outer_obj, o_min, o_max,
                                  inner_name, inner_obj, i_min, i_max, i_corners)

    return containment


def _enrich_containment(visible_objects, containment, mesh_objects):
    """Add inside= and contains: fields to visible_objects based on containment."""
    # Build lookup
    inner_to_outer = {}  # inner_name -> outer_name
    outer_to_inners = {}  # outer_name -> [inner_names]

    for c in containment:
        inner_to_outer[c["inner"]] = c["outer"]
        outer_to_inners.setdefault(c["outer"], []).append(c["inner"])

    # Check if outer is transparent (container flagging)
    mat_lookup = {}
    for _, data in mesh_objects:
        mat = data.get("material", {})
        if mat.get("name"):
            mat_lookup[data["name"]] = mat

    for obj_data in visible_objects:
        name = obj_data.get("name")
        if name in inner_to_outer:
            obj_data["inside"] = inner_to_outer[name]
        if name in outer_to_inners:
            obj_data["contains"] = outer_to_inners[name]


def compute(ctx):
    if not ctx.include_flags.get("spatial"):
        return {}
    if not ctx.mesh_objects:
        return {}
    containment = _compute_containment(ctx.mesh_objects, ctx.scene, ctx.depsgraph)
    ctx.containment = containment
    if containment:
        _enrich_containment(ctx.visible_objects, containment, ctx.mesh_objects)
    return {"containment": containment} if containment else {}


register("containment", compute, emits=["containment"])
