"""Shadow analysis subsystem — per-light shadow footprint via raycasts."""
import bpy

from ..perception_registry import register


def _compute_shadow_analysis(lights, mesh_objects, scene, cam, depsgraph, ray_resolution=6):
    """Per-light shadow footprint via raycasts.

    For each (light, target surface) pair:
    - Shadow coverage: % of target surface area in shadow (6x6 ray grid)
    - Shadow casters: which objects intercept light-to-surface rays
    - Contact shadow: downward raycasts from object bbox bottom to detect ground gap
    """
    import mathutils

    significant = [(obj, data) for obj, data in mesh_objects
                    if data.get("screen_coverage_pct", 0) > 0.5 or data.get("dimensions")]
    if not significant:
        return []

    results = []

    for light_info in lights:
        light_pos = mathutils.Vector(light_info["location"])
        light_type = light_info["type"]

        light_obj = bpy.data.objects.get(light_info["name"])
        if not light_obj:
            continue

        # SUN lights have a constant direction; non-SUN use per-sample direction
        sun_dir = None
        if light_type == 'SUN':
            sun_dir = -(light_obj.matrix_world.col[2].to_3d().normalized())

        for obj, data in significant:
            # Get object world-space AABB
            try:
                bbox_corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
            except Exception:
                continue

            min_c = mathutils.Vector([min(c[i] for c in bbox_corners) for i in range(3)])
            max_c = mathutils.Vector([max(c[i] for c in bbox_corners) for i in range(3)])

            # Cast rays from grid of points on surface toward light
            shadow_hits = 0
            total_rays = 0
            casters = set()

            for gy in range(ray_resolution):
                for gx in range(ray_resolution):
                    # Sample point on top face of AABB
                    u = (gx + 0.5) / ray_resolution
                    v = (gy + 0.5) / ray_resolution
                    sample = mathutils.Vector((
                        min_c.x + u * (max_c.x - min_c.x),
                        min_c.y + v * (max_c.y - min_c.y),
                        max_c.z,  # top of object
                    ))

                    if light_type == 'SUN':
                        ray_dir_to_light = -sun_dir
                        ray_dist = 100.0
                    else:
                        ray_dir_to_light = (light_pos - sample).normalized()
                        ray_dist = (light_pos - sample).length - 0.02

                    try:
                        hit, loc, normal, idx, hit_obj, matrix = scene.ray_cast(
                            depsgraph, sample + ray_dir_to_light * 0.01, ray_dir_to_light,
                            distance=max(0.01, ray_dist)
                        )
                        total_rays += 1
                        if hit and hit_obj and hit_obj.name != obj.name:
                            shadow_hits += 1
                            casters.add(hit_obj.name)
                    except Exception:
                        total_rays += 1

            coverage_pct = round(shadow_hits / max(total_rays, 1) * 100, 1)

            # Contact shadow: 4 downward raycasts from bbox bottom corners
            has_contact = False
            contact_gap = 0
            try:
                bottom_z = min_c.z
                center_xy = (min_c + max_c) / 2
                contact_points = [
                    mathutils.Vector((min_c.x, min_c.y, bottom_z)),
                    mathutils.Vector((max_c.x, min_c.y, bottom_z)),
                    mathutils.Vector((min_c.x, max_c.y, bottom_z)),
                    mathutils.Vector((max_c.x, max_c.y, bottom_z)),
                ]
                gaps = []
                for pt in contact_points:
                    hit, loc, normal, idx, hit_obj, matrix = scene.ray_cast(
                        depsgraph, pt, mathutils.Vector((0, 0, -1)),
                        distance=1.0
                    )
                    if hit:
                        gaps.append((pt - loc).length)
                if gaps:
                    contact_gap = round(min(gaps), 3)
                    has_contact = contact_gap < 0.05
            except Exception:
                pass

            entry = {
                "light": light_info["name"],
                "surface": data["name"],
                "shadow_coverage_pct": coverage_pct,
            }
            if casters:
                entry["casters"] = sorted(casters)
            if has_contact:
                entry["contact_shadow"] = True
            elif contact_gap > 0:
                entry["contact_gap"] = contact_gap

            results.append(entry)

    return results


def compute(ctx):
    if not ctx.include_flags.get("shadows"):
        return {}
    if not ctx.lights or not ctx.mesh_objects:
        return {}
    analysis = _compute_shadow_analysis(ctx.lights, ctx.mesh_objects, ctx.scene, ctx.cam, ctx.depsgraph)
    # Skip 100% shadow entries (interior lights shadow everything — obvious)
    analysis = [a for a in analysis if a.get("shadow_coverage_pct", 0) < 99]
    return {"shadow_analysis": analysis}


register("shadows", compute, emits=["shadow_analysis"])
