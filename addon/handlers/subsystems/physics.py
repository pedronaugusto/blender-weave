"""Physics subsystem — rigid body state computation."""

from ..perception_registry import register


def _compute_physics_states(mesh_objects):
    """Compute rigid body physics state for objects with physics.

    Maps Blender types: ACTIVE -> dynamic, PASSIVE -> static.
    Appends 'kinematic' flag when set on active bodies.
    """
    states = []
    for obj, data in mesh_objects:
        rb = obj.rigid_body
        if rb:
            # Map Blender types to Perspicacity spec types
            if rb.kinematic:
                phys_type = "kinematic"
            elif rb.type == 'ACTIVE':
                phys_type = "dynamic"
            else:
                phys_type = "static"
            entry = {
                "name": data["name"],
                "type": phys_type,
                "mass": round(rb.mass, 2),
            }
            # Sleeping state (deactivated by physics sim)
            try:
                if hasattr(rb, 'is_deactivated') and rb.is_deactivated:
                    entry["sleeping"] = True
            except Exception:
                pass
            states.append(entry)
    return states


def compute(ctx):
    if not ctx.include_flags.get("physics"):
        return {}
    return {"physics_states": _compute_physics_states(ctx.mesh_objects)}


register("physics", compute, emits=["physics_states"])
