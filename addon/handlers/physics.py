import bpy
import traceback

from ._utils import select_only, ensure_object_mode, set_properties_safe


# Cloth presets with preconfigured properties
_CLOTH_PRESETS = {
    "silk": {
        "quality_steps": 12, "mass": 0.15,
        "tension_stiffness": 5, "compression_stiffness": 5,
        "shear_stiffness": 5, "bending_stiffness": 0.05,
        "tension_damping": 0, "compression_damping": 0,
        "shear_damping": 0, "bending_damping": 0.5,
    },
    "cotton": {
        "quality_steps": 7, "mass": 0.3,
        "tension_stiffness": 15, "compression_stiffness": 15,
        "shear_stiffness": 15, "bending_stiffness": 0.5,
        "tension_damping": 5, "compression_damping": 5,
        "shear_damping": 5, "bending_damping": 0.5,
    },
    "leather": {
        "quality_steps": 7, "mass": 0.4,
        "tension_stiffness": 80, "compression_stiffness": 80,
        "shear_stiffness": 80, "bending_stiffness": 150,
        "tension_damping": 25, "compression_damping": 25,
        "shear_damping": 25, "bending_damping": 0.5,
    },
    "rubber": {
        "quality_steps": 7, "mass": 3.0,
        "tension_stiffness": 15, "compression_stiffness": 15,
        "shear_stiffness": 15, "bending_stiffness": 25,
        "tension_damping": 25, "compression_damping": 25,
        "shear_damping": 25, "bending_damping": 0.5,
    },
}


def manage_physics(object_name, action, physics_type=None, properties=None,
                   preset=None, constraint_type=None, target_object=None,
                   frame_start=None, frame_end=None):
    """Manage physics simulations on objects.

    Args:
        action: Operation —
            "add" — add physics type to object
            "remove" — remove physics from object
            "set" — set physics properties
            "list" — list physics on object
            "configure_world" — configure rigid body world settings
            "add_constraint" — add rigid body constraint between objects
            "add_cloth_preset" — add cloth with named preset
            "bake" — bake simulation cache
            "free_cache" — free simulation cache
        object_name: Name of the object
        physics_type: Physics type — RIGID_BODY, COLLISION, CLOTH, SOFT_BODY, SMOKE, FLUID
        properties: Dict of physics properties to set
        preset: Cloth preset name (silk, cotton, leather, rubber)
        constraint_type: RB constraint type (FIXED, POINT, HINGE, SLIDER, MOTOR)
        target_object: Target object for constraints
        frame_start: Start frame for bake
        frame_end: End frame for bake

    Returns:
        dict with operation result
    """
    try:
        if action == "configure_world":
            return _configure_world(properties)
        elif action == "bake":
            return _bake_simulation(object_name, physics_type, frame_start, frame_end)
        elif action == "free_cache":
            return _free_cache(object_name, physics_type)
        elif action == "add_constraint":
            return _add_rb_constraint(object_name, target_object, constraint_type, properties)

        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}

        if action == "add":
            return _add_physics(obj, physics_type)
        elif action == "remove":
            return _remove_physics(obj, physics_type)
        elif action == "set":
            return _set_physics(obj, physics_type, properties)
        elif action == "list":
            return _list_physics(obj)
        elif action == "add_cloth_preset":
            return _add_cloth_preset(obj, preset)
        else:
            return {"error": f"Unknown action: {action}. Use: add, remove, set, list, "
                    "configure_world, add_constraint, add_cloth_preset, bake, free_cache"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Physics operation failed: {str(e)}"}


def _add_physics(obj, physics_type):
    if not physics_type:
        return {"error": "physics_type is required for add"}

    select_only(obj)
    physics_type = physics_type.upper()

    if physics_type == "RIGID_BODY":
        # Ensure rigid body world exists
        if not bpy.context.scene.rigidbody_world:
            bpy.ops.rigidbody.world_add()
        bpy.ops.rigidbody.object_add()
    elif physics_type == "COLLISION":
        bpy.ops.object.modifier_add(type='COLLISION')
    elif physics_type == "CLOTH":
        bpy.ops.object.modifier_add(type='CLOTH')
    elif physics_type == "SOFT_BODY":
        bpy.ops.object.modifier_add(type='SOFT_BODY')
    else:
        return {"error": f"Unknown physics_type: {physics_type}. "
                "Use: RIGID_BODY, COLLISION, CLOTH, SOFT_BODY"}

    return {
        "success": True,
        "message": f"Added {physics_type} to '{obj.name}'",
    }


def _remove_physics(obj, physics_type):
    if not physics_type:
        return {"error": "physics_type is required for remove"}

    select_only(obj)
    physics_type = physics_type.upper()

    if physics_type == "RIGID_BODY":
        if obj.rigid_body:
            bpy.ops.rigidbody.object_remove()
        else:
            return {"error": f"No rigid body on '{obj.name}'"}
    elif physics_type in ("COLLISION", "CLOTH", "SOFT_BODY"):
        removed = False
        for mod in list(obj.modifiers):
            if mod.type == physics_type:
                obj.modifiers.remove(mod)
                removed = True
                break
        if not removed:
            return {"error": f"No {physics_type} modifier on '{obj.name}'"}
    else:
        return {"error": f"Unknown physics_type: {physics_type}"}

    return {
        "success": True,
        "message": f"Removed {physics_type} from '{obj.name}'",
    }


def _set_physics(obj, physics_type, properties):
    if not physics_type or not properties:
        return {"error": "physics_type and properties are required for set"}

    physics_type = physics_type.upper()

    if physics_type == "RIGID_BODY":
        rb = obj.rigid_body
        if not rb:
            return {"error": f"No rigid body on '{obj.name}'"}
        set_ok, failed = set_properties_safe(rb, properties)
        result = {
            "success": True,
            "message": f"Updated {physics_type} properties on '{obj.name}': {', '.join(set_ok)}",
            "changed": set_ok,
        }
        if failed:
            result["failed"] = failed
        return result

    elif physics_type in ("COLLISION", "CLOTH", "SOFT_BODY"):
        for mod in obj.modifiers:
            if mod.type == physics_type:
                # For cloth/soft body, properties live on mod.settings
                target = mod.settings if hasattr(mod, 'settings') else mod
                set_ok, failed = set_properties_safe(target, properties)
                # Also try on mod directly for anything not on settings
                for f in list(failed):
                    if hasattr(mod, f["name"]):
                        try:
                            setattr(mod, f["name"], properties[f["name"]])
                            set_ok.append(f["name"])
                            failed.remove(f)
                        except Exception:
                            pass
                result = {
                    "success": True,
                    "message": f"Updated {physics_type} properties on '{obj.name}': {', '.join(set_ok)}",
                    "changed": set_ok,
                }
                if failed:
                    result["failed"] = failed
                return result
        return {"error": f"No {physics_type} modifier on '{obj.name}'"}
    else:
        return {"error": f"Unknown physics_type: {physics_type}"}


def _list_physics(obj):
    physics = []

    if obj.rigid_body:
        rb = obj.rigid_body
        physics.append({
            "type": "RIGID_BODY",
            "rigid_body_type": rb.type,
            "mass": rb.mass,
            "friction": rb.friction,
            "restitution": rb.restitution,
            "collision_shape": rb.collision_shape,
            "enabled": rb.enabled,
            "linear_damping": rb.linear_damping,
            "angular_damping": rb.angular_damping,
            "collision_margin": rb.collision_margin,
        })

    for mod in obj.modifiers:
        if mod.type == "CLOTH":
            info = {"type": "CLOTH", "name": mod.name}
            if hasattr(mod, 'settings'):
                s = mod.settings
                info.update({
                    "quality_steps": s.quality_steps,
                    "mass": s.mass,
                    "tension_stiffness": s.tension_stiffness,
                    "bending_stiffness": s.bending_stiffness,
                })
            physics.append(info)
        elif mod.type == "SOFT_BODY":
            info = {"type": "SOFT_BODY", "name": mod.name}
            if hasattr(mod, 'settings'):
                s = mod.settings
                info.update({
                    "mass": s.mass,
                    "friction": s.friction,
                })
            physics.append(info)
        elif mod.type == "COLLISION":
            physics.append({"type": "COLLISION", "name": mod.name})

    return {
        "success": True,
        "object_name": obj.name,
        "physics": physics,
        "total": len(physics),
    }


def _configure_world(properties):
    """Configure rigid body world settings."""
    scene = bpy.context.scene

    if not scene.rigidbody_world:
        bpy.ops.rigidbody.world_add()

    rbw = scene.rigidbody_world
    if not properties:
        # Return current settings
        return {
            "success": True,
            "message": "Rigid body world settings",
            "settings": {
                "enabled": rbw.enabled,
                "time_scale": rbw.time_scale,
                "substeps_per_frame": rbw.substeps_per_frame,
                "solver_iterations": rbw.solver_iterations,
                "use_split_impulse": rbw.use_split_impulse,
                "frame_start": rbw.point_cache.frame_start,
                "frame_end": rbw.point_cache.frame_end,
            }
        }

    set_ok, failed = set_properties_safe(rbw, properties)

    result = {
        "success": True,
        "message": f"Updated rigid body world: {', '.join(set_ok)}",
        "changed": set_ok,
    }
    if failed:
        result["failed"] = failed
    return result


def _add_rb_constraint(object_name, target_object, constraint_type, properties):
    """Add a rigid body constraint between two objects."""
    if not object_name:
        return {"error": "object_name is required for add_constraint"}
    if not constraint_type:
        return {"error": "constraint_type is required (FIXED, POINT, HINGE, SLIDER, MOTOR)"}

    # Create empty at midpoint for constraint
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    target = None
    if target_object:
        target = bpy.data.objects.get(target_object)
        if not target:
            return {"error": f"Target object not found: {target_object}"}

    # Create empty for constraint
    loc = list(obj.location)
    if target:
        loc = [(obj.location[i] + target.location[i]) / 2 for i in range(3)]

    bpy.ops.object.empty_add(type='PLAIN_AXES', location=loc)
    empty = bpy.context.active_object
    empty.name = f"RBConstraint_{object_name}"

    # Ensure RB world exists
    if not bpy.context.scene.rigidbody_world:
        bpy.ops.rigidbody.world_add()

    select_only(empty)
    bpy.ops.rigidbody.constraint_add()

    rbc = empty.rigid_body_constraint
    rbc.type = constraint_type.upper()
    rbc.object1 = obj
    if target:
        rbc.object2 = target

    if properties:
        set_ok, failed = set_properties_safe(rbc, properties)

    return {
        "success": True,
        "message": f"Added {constraint_type} constraint between '{object_name}' "
                   f"and '{target_object or 'world'}'",
        "constraint_object": empty.name,
    }


def _add_cloth_preset(obj, preset):
    """Add cloth simulation with a named preset."""
    if not preset:
        return {"error": f"preset is required. Options: {', '.join(_CLOTH_PRESETS.keys())}"}

    preset = preset.lower()
    if preset not in _CLOTH_PRESETS:
        return {"error": f"Unknown preset: {preset}. Options: {', '.join(_CLOTH_PRESETS.keys())}"}

    select_only(obj)
    bpy.ops.object.modifier_add(type='CLOTH')

    # Find the cloth modifier
    cloth_mod = None
    for mod in obj.modifiers:
        if mod.type == 'CLOTH':
            cloth_mod = mod
            break

    if not cloth_mod or not hasattr(cloth_mod, 'settings'):
        return {"error": "Failed to add cloth modifier"}

    preset_props = _CLOTH_PRESETS[preset]
    set_ok, failed = set_properties_safe(cloth_mod.settings, preset_props)

    result = {
        "success": True,
        "message": f"Added cloth with '{preset}' preset to '{obj.name}'",
        "preset": preset,
        "properties_set": set_ok,
    }
    if failed:
        result["properties_failed"] = failed
    return result


def _bake_simulation(object_name, physics_type, frame_start, frame_end):
    """Bake simulation cache."""
    scene = bpy.context.scene

    if physics_type and physics_type.upper() == "RIGID_BODY":
        if not scene.rigidbody_world:
            return {"error": "No rigid body world to bake"}
        cache = scene.rigidbody_world.point_cache
        if frame_start is not None:
            cache.frame_start = frame_start
        if frame_end is not None:
            cache.frame_end = frame_end

        override = bpy.context.copy()
        override['point_cache'] = cache
        with bpy.context.temp_override(**override):
            bpy.ops.ptcache.bake(bake=True)

        return {
            "success": True,
            "message": f"Baked rigid body simulation (frames {cache.frame_start}-{cache.frame_end})",
        }

    # For cloth/soft body on specific object
    if not object_name:
        return {"error": "object_name is required for bake"}

    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    select_only(obj)

    for mod in obj.modifiers:
        if mod.type in ('CLOTH', 'SOFT_BODY'):
            cache = mod.point_cache
            if frame_start is not None:
                cache.frame_start = frame_start
            if frame_end is not None:
                cache.frame_end = frame_end

            override = bpy.context.copy()
            override['point_cache'] = cache
            with bpy.context.temp_override(**override):
                bpy.ops.ptcache.bake(bake=True)

            return {
                "success": True,
                "message": f"Baked {mod.type} simulation on '{object_name}' "
                           f"(frames {cache.frame_start}-{cache.frame_end})",
            }

    return {"error": f"No bakeable physics found on '{object_name}'"}


def _free_cache(object_name, physics_type):
    """Free simulation cache."""
    scene = bpy.context.scene

    if physics_type and physics_type.upper() == "RIGID_BODY":
        if not scene.rigidbody_world:
            return {"error": "No rigid body world"}
        cache = scene.rigidbody_world.point_cache
        override = bpy.context.copy()
        override['point_cache'] = cache
        with bpy.context.temp_override(**override):
            bpy.ops.ptcache.free_bake()
        return {"success": True, "message": "Freed rigid body cache"}

    if not object_name:
        return {"error": "object_name is required for free_cache"}

    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    select_only(obj)

    for mod in obj.modifiers:
        if mod.type in ('CLOTH', 'SOFT_BODY'):
            cache = mod.point_cache
            override = bpy.context.copy()
            override['point_cache'] = cache
            with bpy.context.temp_override(**override):
                bpy.ops.ptcache.free_bake()
            return {"success": True, "message": f"Freed {mod.type} cache on '{object_name}'"}

    return {"error": f"No physics cache found on '{object_name}'"}


def manage_constraints(object_name, action, constraint_type=None,
                       constraint_name=None, properties=None):
    """Manage object-level constraints.

    Args:
        action: Operation —
            "add" — add constraint to object
            "remove" — remove constraint by name
            "set" — set constraint properties
            "list" — list all constraints on object
        object_name: Name of the object
        constraint_type: Constraint type — TRACK_TO, LIMIT_LOCATION, COPY_ROTATION,
                        CHILD_OF, DAMPED_TRACK, FLOOR, CLAMP_TO, COPY_LOCATION,
                        COPY_SCALE, LIMIT_ROTATION, LIMIT_SCALE
        constraint_name: Name of constraint (for remove, set)
        properties: Dict of constraint properties (target, subtarget, influence, etc.)

    Returns:
        dict with operation result
    """
    try:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}

        if action == "add":
            if not constraint_type:
                return {"error": "constraint_type is required for add"}
            con = obj.constraints.new(constraint_type)
            if properties:
                for key, val in properties.items():
                    if key == "target":
                        con.target = bpy.data.objects.get(val)
                    elif key == "subtarget":
                        con.subtarget = val
                    elif hasattr(con, key):
                        setattr(con, key, val)
            return {
                "success": True,
                "message": f"Added {constraint_type} constraint to '{object_name}'",
                "constraint_name": con.name,
            }

        elif action == "remove":
            if not constraint_name:
                return {"error": "constraint_name is required for remove"}
            con = obj.constraints.get(constraint_name)
            if not con:
                return {"error": f"Constraint not found: {constraint_name}"}
            obj.constraints.remove(con)
            return {
                "success": True,
                "message": f"Removed constraint '{constraint_name}' from '{object_name}'",
            }

        elif action == "set":
            if not constraint_name or not properties:
                return {"error": "constraint_name and properties are required for set"}
            con = obj.constraints.get(constraint_name)
            if not con:
                return {"error": f"Constraint not found: {constraint_name}"}
            changed = []
            for key, val in properties.items():
                if key == "target":
                    con.target = bpy.data.objects.get(val)
                    changed.append(key)
                elif key == "subtarget":
                    con.subtarget = val
                    changed.append(key)
                elif hasattr(con, key):
                    setattr(con, key, val)
                    changed.append(key)
            return {
                "success": True,
                "message": f"Updated constraint '{constraint_name}': {', '.join(changed)}",
                "changed": changed,
            }

        elif action == "list":
            constraints = []
            for con in obj.constraints:
                con_info = {
                    "name": con.name,
                    "type": con.type,
                    "influence": con.influence,
                    "mute": con.mute,
                }
                if hasattr(con, 'target') and con.target:
                    con_info["target"] = con.target.name
                if hasattr(con, 'subtarget') and con.subtarget:
                    con_info["subtarget"] = con.subtarget
                constraints.append(con_info)
            return {
                "success": True,
                "object_name": obj.name,
                "constraints": constraints,
                "total": len(constraints),
            }

        else:
            return {"error": f"Unknown action: {action}. Use: add, remove, set, list"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Constraint operation failed: {str(e)}"}
