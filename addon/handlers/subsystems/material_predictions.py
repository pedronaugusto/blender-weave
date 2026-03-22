"""Material-light readability predictions subsystem."""
import bpy

from ..perception_registry import register


def _compute_material_predictions(mesh_objects, world_info, lights,
                                  light_analysis=None, scene=None, cam=None,
                                  depsgraph=None):
    """Rule engine for visible Principled BSDF materials — factual appearance."""

    has_hdri = world_info.get("has_hdri", False)
    predictions = {}

    for obj, data in mesh_objects:
        mat_info = data.get("material")
        if not mat_info or mat_info.get("name") in predictions:
            continue

        name = mat_info["name"]
        pred = {"name": name, "appearance": "", "needs": [], "warnings": []}

        transmission = mat_info.get("transmission", 0)
        metallic = mat_info.get("metallic", 0)
        roughness = mat_info.get("roughness", 0.5)
        emission = mat_info.get("emission_strength", 0)
        subsurface = mat_info.get("subsurface_weight", 0)
        coat = mat_info.get("coat_weight", 0)
        has_textures = mat_info.get("has_textures", False)
        base_color = mat_info.get("base_color", [0.5, 0.5, 0.5])

        # Build appearance description
        parts = []
        if transmission > 0.5:
            parts.append("glass" if transmission > 0.8 else "translucent")
            pred["needs"].append("env reflections")
            pred["needs"].append("objects behind")
        elif metallic > 0.8:
            if roughness < 0.1:
                parts.append("mirror-like metal")
                if not has_hdri:
                    pred["needs"].append("HDRI for reflections")
            elif roughness < 0.3:
                parts.append("polished metal")
            else:
                parts.append("rough metal")
            if roughness < 0.05 and bpy.context.scene.render.engine == 'CYCLES':
                pred["warnings"].append("firefly risk — very low roughness")
        elif has_textures:
            parts.append("textured")
        else:
            # Matte/diffuse
            if isinstance(base_color, list):
                luminance = 0.2126 * base_color[0] + 0.7152 * base_color[1] + 0.0722 * base_color[2]
                if luminance < 0.05:
                    parts.append("very dark")
                elif luminance > 0.9:
                    parts.append("very bright")
                else:
                    parts.append("matte diffuse")
            else:
                parts.append("matte diffuse")

        if subsurface > 0.3:
            parts.append("SSS")
            pred["needs"].append("backlight for SSS")

        if emission > 0:
            parts.append("emissive")

        if coat > 0:
            parts.append("clearcoat")

        pred["appearance"] = " ".join(parts) if parts else "standard"

        # Suppress needs if already met
        if has_hdri and "HDRI for reflections" in pred["needs"]:
            pred["needs"].remove("HDRI for reflections")

        predictions[name] = pred

    return list(predictions.values())


def compute(ctx):
    if not ctx.include_flags.get("materials"):
        return {}
    if not ctx.mesh_objects:
        return {}
    preds = _compute_material_predictions(ctx.mesh_objects, ctx.world_info, ctx.lights,
                                           ctx.light_analysis, ctx.scene, ctx.cam, ctx.depsgraph)
    return {"material_predictions": preds}


register("material_predictions", compute, depends_on=["lighting"], emits=["material_predictions"])
