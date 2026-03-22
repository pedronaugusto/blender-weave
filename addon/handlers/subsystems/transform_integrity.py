import bpy
import math
from ..perception_registry import register

def compute(ctx):
    """Check transform integrity — parent rotation should propagate to children."""
    verify_failures = ctx.result.get("verify", [])

    for obj, data in ctx.mesh_objects:
        # Only check hierarchy roots with children
        if not obj.children:
            continue

        parent_rot = obj.rotation_euler
        has_rotation = any(abs(math.degrees(r)) > 1.0 for r in parent_rot)
        if not has_rotation:
            continue

        # Check if any MESH children have identity rotation in world space
        for child in obj.children:
            if child.type != 'MESH':
                continue
            try:
                child_world_rot = child.matrix_world.to_euler()
                child_has_rotation = any(abs(math.degrees(r)) > 1.0 for r in child_world_rot)

                if not child_has_rotation:
                    # Report max delta across all 3 axes
                    parent_degs = [round(math.degrees(r)) for r in parent_rot]
                    child_degs = [round(math.degrees(r)) for r in child_world_rot]
                    deltas = [abs(parent_degs[i] - child_degs[i]) for i in range(3)]
                    max_axis = "XYZ"[deltas.index(max(deltas))]
                    max_delta = max(deltas)
                    verify_failures.append({
                        "result": "FAIL",
                        "object": obj.name,
                        "message": (
                            f"rotation_not_inherited parent_rot=[{parent_degs[0]},{parent_degs[1]},{parent_degs[2]}]° "
                            f"child={child.name} child_rot=[{child_degs[0]},{child_degs[1]},{child_degs[2]}]° "
                            f"max_delta={max_delta}°({max_axis})"
                        ),
                    })
                    break  # One failure per parent is enough
            except Exception:
                pass

    return {"verify": verify_failures} if verify_failures else {}

register("transform_integrity", compute, phase="post", emits=["verify"])
