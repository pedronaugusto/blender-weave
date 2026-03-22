"""Ray grid subsystem — camera ray grid coverage map."""
import math

from ..perception_registry import register


def _compute_ray_grid(scene, cam, depsgraph, resolution=12,
                      origin=None, direction_matrix=None, fov_x=None, fov_y=None):
    """Cast rays through a grid from a viewpoint.

    When origin/direction_matrix/fov are provided, uses those instead of camera.
    This allows multi-view ray grids from arbitrary viewpoints.
    """
    import mathutils

    if origin is not None and direction_matrix is not None:
        # Use provided viewpoint
        ray_origin = origin
        rot_matrix = direction_matrix
        fx = fov_x if fov_x is not None else math.radians(90)
        fy = fov_y if fov_y is not None else math.radians(90)
    else:
        # Use camera
        cam_matrix = cam.matrix_world
        ray_origin = cam_matrix.translation
        rot_matrix = cam_matrix.to_3x3()

        cam_data = cam.data
        aspect = scene.render.resolution_x / max(1, scene.render.resolution_y)

        if cam_data.sensor_fit == 'VERTICAL':
            fy = 2 * math.atan(cam_data.sensor_height / (2 * cam_data.lens))
            fx = 2 * math.atan(math.tan(fy / 2) * aspect)
        else:
            fx = 2 * math.atan(cam_data.sensor_width / (2 * cam_data.lens))
            fy = 2 * math.atan(math.tan(fx / 2) / aspect)

    hits = []
    coverage_map = {}

    for gy in range(resolution):
        for gx in range(resolution):
            # NDC coordinates (-1 to 1)
            ndc_x = (gx + 0.5) / resolution * 2 - 1
            ndc_y = (gy + 0.5) / resolution * 2 - 1

            # Ray direction in local space
            dir_x = math.tan(fx / 2) * ndc_x
            dir_y = math.tan(fy / 2) * ndc_y
            local_dir = mathutils.Vector((dir_x, dir_y, -1)).normalized()

            # Transform to world space
            world_dir = (rot_matrix @ local_dir).normalized()

            try:
                hit, loc, normal, face_idx, hit_obj, matrix = scene.ray_cast(
                    depsgraph, ray_origin, world_dir
                )
                if hit and hit_obj:
                    dist = (loc - ray_origin).length
                    mat_name = ""
                    try:
                        if hit_obj.type == 'MESH' and hit_obj.data.polygons:
                            mat_idx = hit_obj.data.polygons[face_idx].material_index
                            if mat_idx < len(hit_obj.material_slots):
                                mat = hit_obj.material_slots[mat_idx].material
                                if mat:
                                    mat_name = mat.name
                    except Exception:
                        pass

                    hits.append({
                        "gx": gx, "gy": gy,
                        "obj": hit_obj.name,
                        "dist": round(dist, 2),
                        "mat": mat_name,
                    })
                    coverage_map[hit_obj.name] = coverage_map.get(hit_obj.name, 0) + 1
                else:
                    coverage_map["empty"] = coverage_map.get("empty", 0) + 1
            except Exception:
                pass

    # Convert counts to percentages
    total = resolution * resolution
    coverage_pct = {k: round(v / total * 100, 1) for k, v in coverage_map.items()}

    return {
        "resolution": [resolution, resolution],
        "hits": hits,
        "coverage_map": coverage_pct,
    }


def compute(ctx):
    if not ctx.include_flags.get("ray_grid"):
        return {}
    if not ctx.cam:
        return {}
    grid = _compute_ray_grid(ctx.scene, ctx.cam, ctx.depsgraph)
    return {"ray_grid": grid}


register("ray_grid", compute, emits=["ray_grid"])
