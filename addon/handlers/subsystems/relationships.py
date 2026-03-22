"""Spatial relationships subsystem — pairwise object analysis."""
import math

from ..perception_registry import register


def _aabb_sample_points(obj, grid_size=3):
    """Return 9 sample points across the object's AABB: 8 corners + center.

    Using world-space AABB corners covers the object's full silhouette from
    any camera angle (no camera-facing-face calculation needed).
    """
    import mathutils
    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    center = mathutils.Vector((0, 0, 0))
    for c in corners:
        center += c
    center /= len(corners)
    # 8 corners + center = 9 points
    return corners + [center]


def _compute_spatial_relationships(mesh_objects, scene, cam, depsgraph, max_distance=None, semantic_groups=None):
    """Pairwise object analysis for mesh objects with > 2% screen coverage.

    Args:
        max_distance: If set, only emit REL for pairs closer than this distance.
                      Default None = emit all pairs (full mode).
    """
    # Filter to objects with any meaningful presence
    significant = [(obj, data) for obj, data in mesh_objects
                    if data.get("screen_coverage_pct", 0) > 0.5 or data.get("dimensions")]

    if len(significant) < 2:
        return []

    # Deduplicate SGROUP members — keep one representative per group for REL diversity
    sgroup_seen = set()
    sgroup_map = {}
    for sg in (semantic_groups or []):
        for member_name in sg.get("members", []):
            sgroup_map[member_name] = sg.get("display_name", sg.get("root", ""))

    deduplicated = []
    for item in sorted(significant, key=lambda x: x[1].get("screen_coverage_pct", 0), reverse=True):
        name = item[1].get("name", "")
        group = sgroup_map.get(name)
        if group and group in sgroup_seen:
            continue  # skip additional members of same SGROUP
        if group:
            sgroup_seen.add(group)
        deduplicated.append(item)

    significant = deduplicated[:20]

    import mathutils
    cam_matrix = cam.matrix_world
    cam_pos = cam_matrix.translation
    cam_forward = -cam_matrix.col[2].to_3d().normalized()
    cam_right = cam_matrix.col[0].to_3d().normalized()
    cam_up = cam_matrix.col[1].to_3d().normalized()

    relationships = []
    for i in range(len(significant)):
        for j in range(i + 1, len(significant)):
            obj_a, data_a = significant[i]
            obj_b, data_b = significant[j]

            pos_a = obj_a.matrix_world.translation
            pos_b = obj_b.matrix_world.translation
            delta = pos_b - pos_a
            distance = delta.length

            # Distance filter for compact mode
            if max_distance is not None and distance > max_distance:
                continue

            # Direction in camera space
            if distance > 0.001:
                delta_norm = delta.normalized()
                right_dot = delta_norm.dot(cam_right)
                forward_dot = delta_norm.dot(cam_forward)

                # Horizontal direction (from A to B)
                if abs(right_dot) > abs(forward_dot):
                    direction = "right" if right_dot > 0 else "left"
                else:
                    direction = "behind" if forward_dot > 0 else "in_front"

                # Vertical relationship
                vert_diff = pos_b.z - pos_a.z
                if vert_diff > 0.5:
                    vertical = "above"
                elif vert_diff < -0.5:
                    vertical = "below"
                else:
                    vertical = "same_level"
            else:
                direction = "coincident"
                vertical = "same_level"

            # Screen overlap (AABB intersection area percentage)
            bbox_a = data_a.get("screen_bbox")
            bbox_b = data_b.get("screen_bbox")
            screen_overlap = False
            overlap_pct = 0.0
            if bbox_a and bbox_b:
                # Intersection rectangle
                ix_min = max(bbox_a[0], bbox_b[0])
                iy_min = max(bbox_a[1], bbox_b[1])
                ix_max = min(bbox_a[2], bbox_b[2])
                iy_max = min(bbox_a[3], bbox_b[3])
                if ix_min < ix_max and iy_min < iy_max:
                    screen_overlap = True
                    inter_area = (ix_max - ix_min) * (iy_max - iy_min)
                    # Percentage relative to the smaller object's AABB
                    area_a = max((bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1]), 0.0001)
                    area_b = max((bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1]), 0.0001)
                    overlap_pct = round(inter_area / min(area_a, area_b) * 100, 1)

            # Partial occlusion check via 3x3 ray grid on B's AABB
            occludes = False
            occlusion_pct = 0.0
            try:
                sample_points = _aabb_sample_points(obj_b, 3)
                occ_hits = 0
                occ_total = len(sample_points)
                for corner in sample_points:
                    ray_dir = (corner - cam_pos).normalized()
                    hit, loc, normal, idx, hit_obj, matrix = scene.ray_cast(
                        depsgraph, cam_pos, ray_dir
                    )
                    if hit and hit_obj and hit_obj.name == obj_a.name:
                        occ_hits += 1
                if occ_total > 0:
                    occlusion_pct = round(occ_hits / occ_total * 100, 1)
                    if occ_hits > 0:
                        occludes = True
            except Exception:
                pass

            # World-space AABB overlap (camera-independent)
            aabb_overlap_pct = 0.0
            try:
                corners_a = [obj_a.matrix_world @ mathutils.Vector(c) for c in obj_a.bound_box]
                corners_b = [obj_b.matrix_world @ mathutils.Vector(c) for c in obj_b.bound_box]
                min_a = [min(c[i] for c in corners_a) for i in range(3)]
                max_a = [max(c[i] for c in corners_a) for i in range(3)]
                min_b = [min(c[i] for c in corners_b) for i in range(3)]
                max_b = [max(c[i] for c in corners_b) for i in range(3)]
                overlap_dims = [min(max_a[i], max_b[i]) - max(min_a[i], min_b[i]) for i in range(3)]
                if all(d > 0 for d in overlap_dims):
                    inter_vol = overlap_dims[0] * overlap_dims[1] * overlap_dims[2]
                    vol_a = max((max_a[0]-min_a[0]) * (max_a[1]-min_a[1]) * (max_a[2]-min_a[2]), 1e-9)
                    vol_b = max((max_b[0]-min_b[0]) * (max_b[1]-min_b[1]) * (max_b[2]-min_b[2]), 1e-9)
                    smaller_vol = min(vol_a, vol_b)
                    aabb_overlap_pct = round(inter_vol / smaller_vol * 100, 1)
            except Exception:
                pass

            rel = {
                "a": data_a["name"],
                "b": data_b["name"],
                "distance": round(distance, 2),
                "direction": direction,
                "vertical": vertical,
                "screen_overlap": screen_overlap,
                "overlap_pct": overlap_pct,
                "aabb_overlap_pct": aabb_overlap_pct,
                "occludes": occludes,
                "occlusion_pct": occlusion_pct,
            }

            # Contact detection
            if distance < 0.1:
                rel["contact"] = True

            relationships.append(rel)

    # Sort by interaction priority: close/contacting pairs first, Room→X suppressed
    def _rel_priority(r):
        dist = r.get("distance", 999)
        dist_score = 1.0 / max(dist, 0.1)
        contact_bonus = 5.0 if r.get("contact") else 0
        overlap_bonus = 3.0 if r.get("screen_overlap") else 0
        room_penalty = -10.0 if r["a"] == "Room" or r["b"] == "Room" else 0
        return dist_score + contact_bonus + overlap_bonus + room_penalty

    relationships.sort(key=_rel_priority, reverse=True)

    return relationships[:30]


def compute(ctx):
    if not ctx.include_flags.get("spatial"):
        return {}
    if not ctx.cam or len(ctx.mesh_objects) < 2:
        return {}
    rels = _compute_spatial_relationships(ctx.mesh_objects, ctx.scene, ctx.cam, ctx.depsgraph,
                                          semantic_groups=ctx.semantic_groups)
    # Suppress REL between objects in the same SGROUP (they're parts of one thing)
    sgroup_map = {}  # obj_name → group_name
    sgroups = getattr(ctx, 'semantic_groups', None) or ctx.result.get("semantic_groups", []) or []
    for sg in sgroups:
        gname = sg.get("display_name", sg.get("root", ""))
        for m in sg.get("members", []):
            sgroup_map[m] = gname
    before_count = len(rels)
    if sgroup_map:
        rels = [r for r in rels
                if not (r["a"] in sgroup_map and r["b"] in sgroup_map
                        and sgroup_map[r["a"]] == sgroup_map[r["b"]])]
    ctx.spatial_relationships = rels
    return {"spatial_relationships": rels}


register("relationships", compute, emits=["spatial_relationships"])
