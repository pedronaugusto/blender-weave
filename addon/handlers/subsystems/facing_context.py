import math
import mathutils
from ..perception_registry import register

def compute(ctx):
    """Add facing_toward context to OBJ lines."""
    # compass directions to unit vectors (Blender: -Y=N, +X=E)
    compass_to_vec = {
        "N": mathutils.Vector((0, -1, 0)),
        "NE": mathutils.Vector((0.707, -0.707, 0)),
        "E": mathutils.Vector((1, 0, 0)),
        "SE": mathutils.Vector((0.707, 0.707, 0)),
        "S": mathutils.Vector((0, 1, 0)),
        "SW": mathutils.Vector((-0.707, 0.707, 0)),
        "W": mathutils.Vector((-1, 0, 0)),
        "NW": mathutils.Vector((-0.707, -0.707, 0)),
    }

    # Build lookup of all mesh objects with world positions
    all_positions = {}
    for obj_data in ctx.visible_objects:
        wc = obj_data.get("world_center")
        if wc:
            all_positions[obj_data["name"]] = mathutils.Vector(wc)

    for obj_data in ctx.visible_objects:
        facing = obj_data.get("facing")
        if not facing or facing not in compass_to_vec:
            continue

        facing_vec = compass_to_vec[facing]
        obj_pos = mathutils.Vector(obj_data.get("world_center", [0, 0, 0]))

        best_dot = 0.7  # threshold
        best_name = None
        best_away_dot = -0.7
        best_away_name = None

        for other_name, other_pos in all_positions.items():
            if other_name == obj_data["name"]:
                continue
            direction = (other_pos - obj_pos)
            # Only consider objects within 5m (world-space distance)
            if direction.length > 5.0:
                continue
            direction.z = 0  # XY plane only
            if direction.length < 0.01:
                continue
            direction.normalize()

            dot = facing_vec.dot(direction)
            if dot > best_dot:
                best_dot = dot
                best_name = other_name
            if dot < best_away_dot:
                best_away_dot = dot
                best_away_name = other_name

        if best_name:
            obj_data["facing_toward"] = best_name
        elif best_away_name:
            obj_data["facing_away_from"] = best_away_name

    return {}  # Modifies ctx.visible_objects in-place

register("facing_context", compute, phase="post", depends_on=["semantic_groups"])
