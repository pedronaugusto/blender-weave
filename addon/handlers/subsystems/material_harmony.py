import math
from ..perception_registry import register

def compute(ctx):
    """Analyze material harmony across visible objects."""
    if not ctx.include_flags.get("materials"):
        return {}
    type_counts = {"wood": 0, "metal": 0, "glass": 0, "fabric": 0,
                   "stone": 0, "plastic": 0, "other": 0}
    warm_count = 0
    cool_count = 0
    neutral_count = 0
    total_materials = 0

    # Track materials per semantic group for consistency check
    group_materials = {}

    for obj_data in ctx.visible_objects:
        mat = obj_data.get("material")
        if not mat:
            continue

        total_materials += 1
        name_lower = mat.get("name", "").lower()

        # Classify material type from name
        if any(w in name_lower for w in ("wood", "oak", "pine", "walnut", "birch")):
            type_counts["wood"] += 1
        elif any(w in name_lower for w in ("metal", "steel", "iron", "chrome", "brass", "copper")):
            type_counts["metal"] += 1
        elif any(w in name_lower for w in ("glass", "window", "transparent")):
            type_counts["glass"] += 1
        elif any(w in name_lower for w in ("fabric", "cloth", "cotton", "linen", "velvet")):
            type_counts["fabric"] += 1
        elif any(w in name_lower for w in ("stone", "concrete", "marble", "granite", "brick")):
            type_counts["stone"] += 1
        elif any(w in name_lower for w in ("plastic", "rubber", "vinyl")):
            type_counts["plastic"] += 1
        elif mat.get("metallic", 0) > 0.7:
            type_counts["metal"] += 1
        elif mat.get("transmission", 0) > 0.5:
            type_counts["glass"] += 1
        elif mat.get("roughness", 0.5) > 0.8:
            type_counts["stone"] += 1
        else:
            type_counts["other"] += 1

        # Color temperature from base_color
        bc = mat.get("base_color")
        if isinstance(bc, list) and len(bc) >= 3:
            r, g, b = bc[0], bc[1], bc[2]
            # Warm = more red, Cool = more blue
            warmth = r - b
            if warmth > 0.1:
                warm_count += 1
            elif warmth < -0.1:
                cool_count += 1
            else:
                neutral_count += 1

    if total_materials < 2:
        return {}

    # Build type string (only types with >0 count, sorted by count)
    type_parts = sorted(
        [(k, v) for k, v in type_counts.items() if v > 0],
        key=lambda x: x[1], reverse=True
    )
    type_str = "+".join(f"{k}({round(v/total_materials*100)}%)" for k, v in type_parts)

    # Temperature
    temps = []
    if warm_count > 0:
        temps.append("warm")
    if cool_count > 0:
        temps.append("cool")
    if neutral_count > 0:
        temps.append("neutral")
    temp_str = "/".join(temps) if temps else "unknown"

    harmony = {
        "types": type_str,
        "temperature": temp_str,
        "total_materials": total_materials,
    }

    return {"material_harmony": harmony}

register("material_harmony", compute, phase="post", emits=["material_harmony"])
