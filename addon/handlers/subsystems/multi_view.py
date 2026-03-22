"""Multi-view ray grid subsystem — top, front, and light-POV projections."""
import bpy
import math

from ..perception_registry import register
from .ray_grid import _compute_ray_grid


def _compute_multi_view(scene, cam, depsgraph, lights, resolution=8):
    """Compute multi-view projective spatial relationships.

    Top-down: objects sorted by XY position, showing floor-plane overlap.
    Front: objects sorted by height, showing vertical arrangement.
    Light-POV: ray grid coverage from primary light (kept as-is).
    """
    import mathutils

    # Gather visible mesh objects with AABB
    mesh_data = []
    for obj in scene.objects:
        if not obj.visible_get() or obj.type != 'MESH':
            continue
        try:
            corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
            bb_min = [min(c[i] for c in corners) for i in range(3)]
            bb_max = [max(c[i] for c in corners) for i in range(3)]
            center = [(bb_min[i] + bb_max[i]) / 2 for i in range(3)]
            mesh_data.append({
                "name": obj.name,
                "center": center,
                "min": bb_min,
                "max": bb_max,
                "obj": obj,
            })
        except Exception:
            continue

    if not mesh_data:
        return []

    views = []

    # ── Top-down view: XY layout + overlap detection ──
    # Sort by X position for spatial readout
    top_sorted = sorted(mesh_data, key=lambda m: m["center"][0])
    top_entries = {}
    for m in top_sorted:
        top_entries[m["name"]] = f"[{round(m['center'][0],1)},{round(m['center'][1],1)}]"

    # Detect XY overlap pairs (objects overlapping in the floor plane)
    overlaps = []
    for i in range(len(mesh_data)):
        for j in range(i + 1, len(mesh_data)):
            a, b = mesh_data[i], mesh_data[j]
            if (a["min"][0] < b["max"][0] and a["max"][0] > b["min"][0] and
                    a["min"][1] < b["max"][1] and a["max"][1] > b["min"][1]):
                overlaps.append(f"{a['name']}+{b['name']}")

    top_view = {
        "view": "top",
        "positions": top_entries,
    }
    if overlaps:
        top_view["overlaps"] = overlaps[:10]  # cap to avoid noise
    views.append(top_view)

    # ── Front view: vertical arrangement ──
    # Classify objects by height tier
    floor_objs = []
    mid_objs = []
    ceiling_objs = []
    for m in mesh_data:
        z_center = m["center"][2]
        height = m["max"][2] - m["min"][2]
        if m["min"][2] < 0.1 or z_center < 1.0:
            floor_objs.append(m["name"])
        elif z_center > 2.5 or m["max"][2] > 2.8:
            ceiling_objs.append(m["name"])
        else:
            mid_objs.append(m["name"])

    front_view = {"view": "front"}
    if floor_objs:
        front_view["floor"] = floor_objs
    if mid_objs:
        front_view["mid"] = mid_objs
    if ceiling_objs:
        front_view["ceiling"] = ceiling_objs
    views.append(front_view)

    # ── Light-POV coverage (ray grid from primary light) ──
    if lights:
        scene_center = mathutils.Vector((0, 0, 0))
        for m in mesh_data:
            scene_center += mathutils.Vector(m["center"])
        scene_center /= len(mesh_data)

        max_dist = max((mathutils.Vector(m["center"]) - scene_center).length
                       for m in mesh_data) if mesh_data else 5.0
        cam_dist = max(max_dist * 2, 3.0)

        primary = max(lights, key=lambda l: l["energy"])
        light_obj = bpy.data.objects.get(primary["name"])
        if light_obj:
            light_pos = mathutils.Vector(primary["location"])
            fov = math.radians(90)

            if primary["type"] == 'SUN':
                light_dir = -(light_obj.matrix_world.col[2].to_3d().normalized())
                light_origin = scene_center - light_dir * cam_dist
            else:
                light_origin = light_pos

            forward = (scene_center - light_origin).normalized()
            world_up = mathutils.Vector((0, 0, 1))
            if abs(forward.dot(world_up)) > 0.99:
                world_up = mathutils.Vector((0, 1, 0))
            right = forward.cross(world_up).normalized()
            up = right.cross(forward).normalized()

            light_matrix = mathutils.Matrix((
                right, up, -forward,
            )).transposed()

            light_grid = _compute_ray_grid(
                scene, cam, depsgraph, resolution=resolution,
                origin=light_origin, direction_matrix=light_matrix,
                fov_x=fov, fov_y=fov,
            )
            views.append({
                "view": f"light:{primary['name']}",
                "coverage_map": {k: v for k, v in light_grid["coverage_map"].items()
                                 if k != "empty"},
            })

    return views


def compute(ctx):
    if not ctx.include_flags.get("multi_view"):
        return {}
    if not ctx.cam:
        return {}
    views = _compute_multi_view(ctx.scene, ctx.cam, ctx.depsgraph, ctx.lights)
    return {"multi_view": views}


register("multi_view", compute, emits=["multi_view"])
