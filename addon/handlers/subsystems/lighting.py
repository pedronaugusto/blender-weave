"""Light-surface illumination analysis subsystem."""
import bpy
import math

from ..perception_registry import register


def _compute_light_analysis(lights, mesh_objects, scene, depsgraph):
    """Compute light-surface structural analysis.

    Returns angle, relative intensity, and shadow casters for each
    (light, surface) pair. Does NOT estimate brightness — that's the
    micro-render's job (EEVEE handles light transport correctly).
    """
    import mathutils

    significant = [(obj, data) for obj, data in mesh_objects
                    if data.get("screen_coverage_pct", 0) > 0.5 or data.get("dimensions")]
    if not significant:
        return []

    analysis = []
    max_intensity = 0.001

    raw_results = []
    for light_info in lights:
        light_pos = mathutils.Vector(light_info["location"])
        light_energy = light_info["energy"]
        light_type = light_info["type"]

        light_obj = bpy.data.objects.get(light_info["name"])
        if not light_obj:
            continue

        for obj, data in significant:
            mesh_center = obj.matrix_world.translation

            if light_type == 'SUN':
                light_dir = -(light_obj.matrix_world.col[2].to_3d().normalized())
                distance = 1.0
            else:
                light_dir = (mesh_center - light_pos).normalized()
                distance = (mesh_center - light_pos).length
                if distance < 0.001:
                    distance = 0.001

            obj_up = (obj.matrix_world.to_3x3() @ mathutils.Vector((0, 0, 1))).normalized()
            cos_angle = max(0, -light_dir.dot(obj_up))
            incidence_angle = math.degrees(math.acos(min(1.0, cos_angle)))

            if light_type == 'SUN':
                raw_intensity = light_energy * cos_angle
            else:
                raw_intensity = light_energy * cos_angle / (distance * distance)

            # Simple shadow check (single raycast, no transmission hacks)
            shadowed_by = []
            try:
                if light_type == 'SUN':
                    ray_d = -light_dir
                    ray_origin = mesh_center + ray_d * 0.01
                    ray_dist = 100.0
                else:
                    ray_d = (light_pos - mesh_center).normalized()
                    ray_origin = mesh_center + ray_d * 0.01
                    ray_dist = distance - 0.02

                hit, loc, normal, idx, hit_obj, matrix = scene.ray_cast(
                    depsgraph, ray_origin, ray_d, distance=ray_dist
                )
                if hit and hit_obj and hit_obj.name != obj.name:
                    shadowed_by.append(hit_obj.name)
            except Exception:
                pass

            max_intensity = max(max_intensity, raw_intensity)
            raw_results.append({
                "light": light_info["name"],
                "surface": data["name"],
                "distance": round(distance, 2),
                "incidence_angle": round(incidence_angle, 1),
                "raw_intensity": raw_intensity,
                "shadowed_by": shadowed_by,
            })

    # ── Emissive objects as light sources (any type: MESH, CURVE, etc.) ──
    emissive_objects = []
    for emit_obj in scene.objects:
        if not emit_obj.visible_get() or not emit_obj.material_slots:
            continue
        for slot in emit_obj.material_slots:
            mat = slot.material
            if not mat or not mat.use_nodes or not mat.node_tree:
                continue
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    es = node.inputs.get('Emission Strength')
                    ec = node.inputs.get('Emission Color')
                    if es and es.default_value > 0:
                        emissive_objects.append((
                            emit_obj,
                            es.default_value,
                            [ec.default_value[i] for i in range(3)] if ec else [1, 1, 1],
                        ))
                        break
            if emissive_objects and emissive_objects[-1][0] == emit_obj:
                break

    for emit_obj, emission_strength, emission_color in emissive_objects:
        emit_luminance = 0.2126 * emission_color[0] + 0.7152 * emission_color[1] + 0.0722 * emission_color[2]
        try:
            bbox_corners = [emit_obj.matrix_world @ mathutils.Vector(c) for c in emit_obj.bound_box]
            dims = [max(c[i] for c in bbox_corners) - min(c[i] for c in bbox_corners) for i in range(3)]
            bbox_area = max(2 * (dims[0]*dims[1] + dims[1]*dims[2] + dims[0]*dims[2]), 0.01)
        except Exception:
            bbox_area = 0.1

        emit_energy = emission_strength * emit_luminance * bbox_area
        emit_center = emit_obj.matrix_world.translation

        for obj, data in significant:
            if obj.name == emit_obj.name:
                continue
            mesh_center = obj.matrix_world.translation
            distance = (mesh_center - emit_center).length
            if distance < 0.001:
                distance = 0.001

            light_dir = (mesh_center - emit_center).normalized()
            obj_up = (obj.matrix_world.to_3x3() @ mathutils.Vector((0, 0, 1))).normalized()
            cos_angle = max(0, -light_dir.dot(obj_up))
            incidence_angle = math.degrees(math.acos(min(1.0, cos_angle)))
            raw_intensity = emit_energy * cos_angle / (distance * distance)

            max_intensity = max(max_intensity, raw_intensity)
            raw_results.append({
                "light": f"EMIT:{emit_obj.name}",
                "surface": data["name"],
                "distance": round(distance, 2),
                "incidence_angle": round(incidence_angle, 1),
                "raw_intensity": raw_intensity,
                "shadowed_by": [],
            })

    # Normalize intensities
    for r in raw_results:
        raw = r.pop("raw_intensity")
        r["intensity"] = round(raw / max_intensity, 2) if max_intensity > 0 else 0
        r["raw_intensity"] = round(raw, 2)
        analysis.append(r)

    return analysis


def compute(ctx):
    if not (ctx.include_flags.get("lighting") or ctx.include_flags.get("materials") or ctx.include_flags.get("shadows")):
        return {}
    if not ctx.lights or not ctx.mesh_objects:
        return {}
    analysis = _compute_light_analysis(ctx.lights, ctx.mesh_objects, ctx.scene, ctx.depsgraph)
    ctx.light_analysis = analysis
    return {"light_analysis": analysis}


register("lighting", compute, emits=["light_analysis"])
