"""Particle system management."""
import bpy
import traceback


def manage_particles(action, object_name=None, name=None, particle_type="EMITTER",
                     count=1000, properties=None, collection_name=None):
    """Manage particle systems on objects.

    Actions:
    - add: Add a particle system
    - set_properties: Set emission/physics/render properties
    - set_instance: Set instance collection for particles
    - remove: Remove a particle system
    - list: List all particle systems on object
    """
    try:
        if action == "add":
            return _add_particles(object_name, name or "ParticleSystem", particle_type, count)
        elif action == "set_properties":
            return _set_properties(object_name, name, properties or {})
        elif action == "set_instance":
            return _set_instance(object_name, name, collection_name)
        elif action == "remove":
            return _remove_particles(object_name, name)
        elif action == "list":
            return _list_particles(object_name)
        else:
            return {"error": f"Unknown action: {action}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def _add_particles(object_name, name, particle_type, count):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}
    if obj.type != 'MESH':
        return {"error": f"Object '{object_name}' is not a mesh"}

    # Add particle system modifier
    mod = obj.modifiers.new(name=name, type='PARTICLE_SYSTEM')
    ps = mod.particle_system
    settings = ps.settings

    settings.type = particle_type
    settings.count = count

    return {
        "success": True,
        "message": f"Added {particle_type} particle system '{ps.name}' with {count} particles on '{object_name}'",
        "object": object_name,
        "system_name": ps.name,
        "particle_type": particle_type,
        "count": count,
    }


def _set_properties(object_name, name, properties):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    ps = _find_particle_system(obj, name)
    if not ps:
        return {"error": f"Particle system '{name}' not found on '{object_name}'"}

    settings = ps.settings
    changed = []

    # Emission properties
    emission_props = ['count', 'frame_start', 'frame_end', 'lifetime', 'emit_from']
    for prop in emission_props:
        if prop in properties:
            setattr(settings, prop, properties[prop])
            changed.append(f"{prop}={properties[prop]}")

    # Velocity
    if 'normal' in properties:
        settings.normal_factor = properties['normal']
        changed.append(f"normal_factor={properties['normal']}")
    if 'object_align_factor' in properties:
        settings.object_align_factor = properties['object_align_factor']
        changed.append("object_align_factor set")

    # Physics
    physics_props = ['mass', 'drag', 'brownian', 'damping']
    for prop in physics_props:
        if prop in properties:
            setattr(settings, prop, properties[prop])
            changed.append(f"{prop}={properties[prop]}")

    # Render type
    if 'render_type' in properties:
        settings.render_type = properties['render_type']
        changed.append(f"render_type={properties['render_type']}")

    if 'particle_size' in properties:
        settings.particle_size = properties['particle_size']
        changed.append(f"particle_size={properties['particle_size']}")

    # Instance object
    if 'instance_object' in properties:
        inst_obj = bpy.data.objects.get(properties['instance_object'])
        if inst_obj:
            settings.instance_object = inst_obj
            changed.append(f"instance_object={properties['instance_object']}")

    # Hair-specific
    if 'hair_length' in properties:
        settings.hair_length = properties['hair_length']
        changed.append(f"hair_length={properties['hair_length']}")

    return {
        "success": True,
        "message": f"Updated particle system '{name}' on '{object_name}': {', '.join(changed)}",
        "changed": changed,
    }


def _set_instance(object_name, name, collection_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    ps = _find_particle_system(obj, name)
    if not ps:
        return {"error": f"Particle system '{name}' not found on '{object_name}'"}

    coll = bpy.data.collections.get(collection_name)
    if not coll:
        return {"error": f"Collection '{collection_name}' not found"}

    settings = ps.settings
    settings.render_type = 'COLLECTION'
    settings.instance_collection = coll

    return {
        "success": True,
        "message": f"Set instance collection '{collection_name}' on particle system '{name}'",
        "object": object_name,
        "system_name": name,
        "collection": collection_name,
    }


def _remove_particles(object_name, name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    # Find the modifier that hosts this particle system
    for i, mod in enumerate(obj.modifiers):
        if mod.type == 'PARTICLE_SYSTEM' and mod.particle_system.name == name:
            obj.modifiers.remove(mod)
            return {
                "success": True,
                "message": f"Removed particle system '{name}' from '{object_name}'",
            }

    return {"error": f"Particle system '{name}' not found on '{object_name}'"}


def _list_particles(object_name):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object '{object_name}' not found"}

    systems = []
    for mod in obj.modifiers:
        if mod.type == 'PARTICLE_SYSTEM':
            ps = mod.particle_system
            settings = ps.settings
            info = {
                "name": ps.name,
                "type": settings.type,
                "count": settings.count,
                "render_type": settings.render_type,
                "frame_start": settings.frame_start,
                "frame_end": settings.frame_end,
                "lifetime": settings.lifetime,
            }
            if settings.render_type == 'COLLECTION' and settings.instance_collection:
                info["instance_collection"] = settings.instance_collection.name
            if settings.render_type == 'OBJECT' and settings.instance_object:
                info["instance_object"] = settings.instance_object.name
            systems.append(info)

    return {
        "success": True,
        "object": object_name,
        "particle_systems": systems,
        "count": len(systems),
    }


def _find_particle_system(obj, name):
    """Find a particle system by name on an object."""
    for mod in obj.modifiers:
        if mod.type == 'PARTICLE_SYSTEM' and mod.particle_system.name == name:
            return mod.particle_system
    return None
