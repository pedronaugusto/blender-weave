"""Spatial facts subsystem — objective spatial measurements."""
import math

from ..perception_registry import register


def _compute_spatial_facts(mesh_objects, lights, world_info, cam, scene, depsgraph,
                           spatial_relationships=None, emissive_count=0, containment=None,
                           **kwargs):
    """Compute objective spatial facts about the scene.

    Returns list of dicts: {"object": name, "type": fact_type, "details": {...}}
    These are objective measurements — no judgment. The plugin reasoning layer
    decides whether a fact represents a problem, warning, or expected state.
    """
    import mathutils
    facts = []

    # Build containment lookup: {inner_name: outer_name} for filtering noise
    contained_in = {}
    container_of = {}
    if containment:
        for c in containment:
            contained_in[c["inner"]] = c["outer"]
            container_of.setdefault(c["outer"], set()).add(c["inner"])

    # Use shared spatial grid from Phase 1 (passed via spatial_grid param or kwargs)
    _spatial_grid = kwargs.get("spatial_grid")

    def _get_world_aabb(obj):
        corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
        min_c = [min(c[i] for c in corners) for i in range(3)]
        max_c = [max(c[i] for c in corners) for i in range(3)]
        return min_c, max_c, corners

    # ── Per-object spatial facts ──
    for obj, data in mesh_objects:
        try:
            min_c, max_c, corners = _get_world_aabb(obj)
            obj_height = max_c[2] - min_c[2]
            obj_diag = math.sqrt(sum((max_c[i] - min_c[i]) ** 2 for i in range(3)))

            # bbox_below_surface: check if this object is sunk into another object's top surface
            # Conditions:
            #   1. Object straddles the surface (top above, bottom below)
            #   2. Object is smaller than the surface (can't sink a table into a mug)
            #   3. XY overlap exists
            # No hardcoded Z=0 — terrain can be any height.
            # Use XY footprint area instead of volume — flat surfaces (planes, floors) have
            # zero volume but large footprint. An object sinks INTO something with a larger footprint.
            obj_footprint = max((max_c[0]-min_c[0]) * (max_c[1]-min_c[1]), 1e-9)
            _surface_candidates = (
                _spatial_grid.neighbors(data.get("world_center", [0,0,0]))
                if _spatial_grid else mesh_objects
            )
            for other_obj, other_data in _surface_candidates:
                if other_obj == obj:
                    continue
                try:
                    o_min, o_max, _ = _get_world_aabb(other_obj)
                    other_footprint = max((o_max[0]-o_min[0]) * (o_max[1]-o_min[1]), 1e-9)
                    # Object footprint must be smaller than or similar to surface footprint
                    if obj_footprint > other_footprint * 2:
                        continue
                    surface_z = o_max[2]
                    # obj straddles the surface: top above, bottom below
                    # XY overlap required
                    if (max_c[2] > surface_z and
                            min_c[2] < surface_z - 0.01 and
                            min_c[0] < o_max[0] and max_c[0] > o_min[0] and
                            min_c[1] < o_max[1] and max_c[1] > o_min[1]):
                        penetration = surface_z - min_c[2]
                        pct = round(penetration / obj_height * 100) if obj_height > 0 else 0
                        if pct > 5:
                            # Only report if surface is ground-level OR penetration is near-total
                            # Chairs under tables (pct ~74%, surface_z ~0.78) = expected, suppress
                            # Objects sunk into floor (surface_z ≈ ground_z) = real problem, report
                            ground_z = kwargs.get("ground_z", 0.0)
                            is_ground_surface = ground_z is not None and abs(surface_z - ground_z) < 0.3
                            is_extreme = pct > 90  # almost fully embedded
                            if is_ground_surface or is_extreme:
                                facts.append({
                                    "object": data["name"],
                                    "type": "bbox_below_surface",
                                    "details": {
                                        "surface": other_data["name"],
                                        "surface_z": round(surface_z, 2),
                                        "penetration": round(penetration, 2),
                                        "pct": pct,
                                    }
                                })
                except Exception:
                    pass

            # bbox_extends_into: this object's AABB overlaps another object's AABB
            # Only report for the SMALLER object (the one being embedded), not the container.
            # Uses spatial grid for O(n*k) when available, falls back to O(n^2).
            obj_vol = max((max_c[0]-min_c[0]) * (max_c[1]-min_c[1]) * (max_c[2]-min_c[2]), 1e-9)
            _extends_candidates = (
                _spatial_grid.neighbors(data.get("world_center", [0,0,0]))
                if _spatial_grid else mesh_objects
            )
            for other_obj, other_data in _extends_candidates:
                if other_obj == obj:
                    continue
                try:
                    o_min, o_max, _ = _get_world_aabb(other_obj)
                    other_vol = max((o_max[0]-o_min[0]) * (o_max[1]-o_min[1]) * (o_max[2]-o_min[2]), 1e-9)
                    # Only report if this object is smaller (or equal)
                    if obj_vol > other_vol:
                        continue
                    # Check 3D AABB overlap
                    overlap = [min(max_c[i], o_max[i]) - max(min_c[i], o_min[i]) for i in range(3)]
                    if all(d > 0.01 for d in overlap):
                        # OBB confirmation — skip AABB false positives for rotated objects
                        try:
                            from .._utils import compute_obb_overlap
                            if not compute_obb_overlap(obj, other_obj):
                                continue
                        except ImportError:
                            pass
                        inter_vol = overlap[0] * overlap[1] * overlap[2]
                        pct = round(inter_vol / obj_vol * 100)
                        if pct > 5:
                            # Skip obvious room-scale containment (everything is inside the room)
                            o_dims = [o_max[i] - o_min[i] for i in range(3)]
                            is_room_scale = sum(1 for d in o_dims if d > 5.0) >= 2
                            if not is_room_scale:
                                facts.append({
                                    "object": data["name"],
                                    "type": "bbox_extends_into",
                                    "details": {
                                        "other": other_data["name"],
                                        "overlap_vol": round(inter_vol, 4),
                                        "pct": pct,
                                    }
                                })
                except Exception:
                    pass

            # scale_diagonal: extreme size
            if obj_diag > 50:
                facts.append({
                    "object": data["name"],
                    "type": "scale_diagonal",
                    "details": {"diagonal": round(obj_diag)}
                })
            elif obj_diag < 0.005 and obj_diag > 0:
                facts.append({
                    "object": data["name"],
                    "type": "scale_diagonal",
                    "details": {"diagonal": round(obj_diag, 4)}
                })

            # scale_ratio: non-uniform scale >50:1 (raised from 10:1 to reduce noise)
            # Exempt architectural panels: thin (<0.3m) in one axis AND long (>1m) in another
            dims = [max_c[i] - min_c[i] for i in range(3)]
            nonzero_dims = [d for d in dims if d > 0.0001]
            if len(nonzero_dims) >= 2:
                ratio = max(nonzero_dims) / min(nonzero_dims)
                if ratio > 50:
                    # Architectural heuristic: thin + long = wall/floor/panel, skip
                    is_architectural = (min(nonzero_dims) < 0.3 and max(nonzero_dims) > 1.0)
                    if not is_architectural:
                        facts.append({
                            "object": data["name"],
                            "type": "scale_ratio",
                            "details": {
                                "ratio": f"{round(ratio)}:1",
                                "axes": [round(d, 3) for d in dims],
                            }
                        })

            # zero_dimensions: zero-volume AABB
            zero_axes = [i for i, d in enumerate(dims) if d < 0.0001]
            if zero_axes and obj_diag > 0:
                facts.append({
                    "object": data["name"],
                    "type": "zero_dimensions",
                    "details": {"zero_axes": ["XYZ"[a] for a in zero_axes]}
                })

            # no_material_slots: visible object with no materials
            if not obj.material_slots or all(s.material is None for s in obj.material_slots):
                facts.append({
                    "object": data["name"],
                    "type": "no_material_slots",
                    "details": {}
                })

            # no_ground_below: floating object (multi-ray downward from below AABB)
            if min_c[2] > 0.1:
                try:
                    cast_dist = max(obj_height * 3, 6.0)
                    down = mathutils.Vector((0, 0, -1))
                    z_start = min_c[2] - 0.001
                    cx, cy = (min_c[0]+max_c[0])/2, (min_c[1]+max_c[1])/2
                    # Cast from center + 4 corners of bottom face
                    cast_points = [
                        (cx, cy, z_start),
                        (min_c[0], min_c[1], z_start),
                        (max_c[0], min_c[1], z_start),
                        (min_c[0], max_c[1], z_start),
                        (max_c[0], max_c[1], z_start),
                    ]
                    any_hit = False
                    for pt in cast_points:
                        hit, loc, normal, idx, hit_obj, matrix = scene.ray_cast(
                            depsgraph, mathutils.Vector(pt), down, distance=cast_dist
                        )
                        if hit:
                            any_hit = True
                            break
                    if not any_hit:
                        facts.append({
                            "object": data["name"],
                            "type": "no_ground_below",
                            "details": {"cast_dist": round(cast_dist, 1)}
                        })
                except Exception:
                    pass

        except Exception:
            pass

    # ── Camera-relative facts ──
    if cam:
        cam_pos = cam.matrix_world.translation
        clip_start = cam.data.clip_start if cam.data else 0.1

        for obj, data in mesh_objects:
            try:
                min_c, max_c, corners = _get_world_aabb(obj)
                # near_plane: object bbox intersects camera near clip plane
                dist_to_nearest = min((mathutils.Vector(
                    [min_c[0], min_c[1], min_c[2]]) - cam_pos).length,
                    (mathutils.Vector([max_c[0], max_c[1], max_c[2]]) - cam_pos).length)
                # More precise: check closest point on AABB to camera
                closest = [max(min_c[i], min(cam_pos[i], max_c[i])) for i in range(3)]
                dist_to_closest = (mathutils.Vector(closest) - cam_pos).length
                if dist_to_closest < clip_start:
                    facts.append({
                        "object": data["name"],
                        "type": "near_plane",
                        "details": {
                            "dist": round(dist_to_closest, 2),
                            "clip_start": round(clip_start, 2),
                        }
                    })
            except Exception:
                pass

        # off_camera: objects with 0% ray grid coverage
        for obj, data in mesh_objects:
            cov = data.get("screen_coverage_pct", 0)
            if cov == 0:
                facts.append({
                    "object": data["name"],
                    "type": "off_camera",
                    "details": {}
                })

    # ── Light facts ──
    # inside_bbox: light source inside object AABB
    for l in lights:
        light_pos = mathutils.Vector(l["location"])
        for obj, data in mesh_objects:
            try:
                min_c, max_c, _ = _get_world_aabb(obj)
                if all(min_c[i] <= light_pos[i] <= max_c[i] for i in range(3)):
                    facts.append({
                        "object": l["name"],
                        "type": "inside_bbox",
                        "details": {
                            "container": data["name"],
                            "light_type": l["type"],
                        }
                    })
            except Exception:
                pass

    # energy_zero: lights with zero energy
    for l in lights:
        if l["energy"] <= 0:
            facts.append({
                "object": l["name"],
                "type": "energy_zero",
                "details": {}
            })

    # no_light_sources: scene has no illumination
    has_hdri = world_info.get("has_hdri", False)
    if not lights and not has_hdri and emissive_count == 0:
        facts.append({
            "object": "scene",
            "type": "no_light_sources",
            "details": {
                "lights": 0,
                "hdri": False,
                "emissive": 0,
            }
        })

    # ── Noise filtering ──
    filtered = []
    no_material_count = 0

    for f in facts:
        obj_name = f["object"]
        ftype = f["type"]

        # Aggregate no_material_slots into a single count
        if ftype == "no_material_slots":
            no_material_count += 1
            continue

        # Suppress bbox_extends_into when containment already covers it
        if ftype == "bbox_extends_into":
            other = f["details"]["other"]
            if obj_name in contained_in and contained_in[obj_name] == other:
                continue
            if other in contained_in and contained_in[other] == obj_name:
                continue

        # Suppress bbox_below_surface when the surface fully contains this object
        if ftype == "bbox_below_surface":
            surface = f["details"]["surface"]
            if obj_name in contained_in and contained_in[obj_name] == surface:
                continue

        # inside_bbox: only report the most specific container (smallest)
        if ftype == "inside_bbox":
            container = f["details"]["container"]
            # If this container also contains the light's most-specific container, skip
            # (e.g., Room contains BulbGlobe which contains light → only report BulbGlobe)
            light_name = obj_name
            other_containers = [ff for ff in facts
                                if ff["type"] == "inside_bbox"
                                and ff["object"] == light_name
                                and ff["details"]["container"] != container]
            if other_containers:
                # Check if any other container is INSIDE this container
                skip = False
                for oc in other_containers:
                    oc_name = oc["details"]["container"]
                    if oc_name in contained_in and contained_in[oc_name] == container:
                        skip = True
                        break
                if skip:
                    continue

        filtered.append(f)

    # Deduplicate bbox_extends_into pairs
    seen_extends = set()
    deduped = []
    for f in filtered:
        if f["type"] == "bbox_extends_into":
            pair = frozenset({f["object"], f["details"]["other"]})
            if pair in seen_extends:
                continue
            seen_extends.add(pair)
        deduped.append(f)

    # Emit aggregated no_material_slots
    if no_material_count > 0:
        deduped.append({
            "object": "scene",
            "type": "no_material_slots",
            "details": {"count": no_material_count}
        })

    return deduped


def _suppress_assembly_sgroup_noise(facts, result):
    """Remove surface_intersect/bbox_below_surface/bbox_extends_into between co-located objects."""
    co_located = set()

    # Assembly members
    for asm in result.get("assemblies", []):
        members = asm.get("members", [])
        for i, a in enumerate(members):
            for b in members[i+1:]:
                co_located.add((a, b))
                co_located.add((b, a))

    # Semantic group members
    for sg in result.get("semantic_groups", []):
        members = sg.get("members", [])
        for i, a in enumerate(members):
            for b in members[i+1:]:
                co_located.add((a, b))
                co_located.add((b, a))

    if not co_located:
        return facts

    suppress_types = {"surface_intersect", "bbox_below_surface", "bbox_extends_into"}
    filtered = []
    for f in facts:
        if f["type"] not in suppress_types:
            filtered.append(f)
            continue
        details = f.get("details", {})
        other = details.get("surface", details.get("other", ""))
        if (f["object"], other) in co_located:
            continue  # suppress
        filtered.append(f)
    return filtered


def compute(ctx):
    if not ctx.include_flags.get("constraints"):
        return {}
    facts = _compute_spatial_facts(
        ctx.mesh_objects, ctx.lights, ctx.world_info, ctx.cam, ctx.scene, ctx.depsgraph,
        spatial_relationships=ctx.spatial_relationships,
        emissive_count=ctx.emissive_count,
        containment=ctx.containment,
        spatial_grid=ctx.spatial_grid,
        ground_z=ctx.result.get("ground_z"),
    )
    # Suppress noise between co-located objects (ASSEMBLY/SGROUP members)
    facts = _suppress_assembly_sgroup_noise(facts, ctx.result)
    return {"spatial_facts": facts}


register("spatial_facts", compute, depends_on=["containment", "assembly_detect", "semantic_groups"], emits=["spatial_facts"])
