"""Semantic grouping subsystem — collapse multi-mesh imports into composites."""

import re

from ..perception_registry import register


def _src_base_name(src):
    """Extract base name from a source identity, stripping instance suffixes.

    'Cassidy Dinning Chair_jok_0.002' -> 'Cassidy Dinning Chair'
    'Cassidy Dinning Chair_1.003'     -> 'Cassidy Dinning Chair'
    'Mesh1.0_0'                       -> 'Mesh1.0'
    """
    import re
    # Strip trailing .NNN
    name = re.sub(r'\.\d{3}$', '', src)
    # Strip trailing _N or _word_N patterns (instance suffixes)
    name = re.sub(r'[_ ](jok_)?\d+$', '', name)
    # Strip trailing _N again for nested suffixes
    name = re.sub(r'[_ ]\d+$', '', name)
    return name.strip()


def _aggregate_group(members):
    """Compute aggregate AABB, dominant material, and facing for a group."""
    all_mins = []
    all_maxs = []
    for m in members:
        wc = m.get("world_center", [0, 0, 0])
        dims = m.get("dimensions", [0.1, 0.1, 0.1])
        half = [d / 2 for d in dims]
        all_mins.append([wc[i] - half[i] for i in range(3)])
        all_maxs.append([wc[i] + half[i] for i in range(3)])

    if not all_mins:
        return None

    agg_min = [min(m[i] for m in all_mins) for i in range(3)]
    agg_max = [max(m[i] for m in all_maxs) for i in range(3)]
    center = [round((agg_min[i] + agg_max[i]) / 2, 3) for i in range(3)]
    dimensions = [round(agg_max[i] - agg_min[i], 3) for i in range(3)]
    top_z = round(agg_max[2], 3)

    # Dominant material: pick from largest member (by coverage or dimensions volume)
    dominant_mat = None
    best_vol = 0
    for m in members:
        mat = m.get("material")
        if mat:
            dims = m.get("dimensions", [0, 0, 0])
            vol = dims[0] * dims[1] * dims[2]
            if vol > best_vol:
                best_vol = vol
                dominant_mat = mat

    # Facing: use first member that has one
    facing = None
    for m in members:
        if m.get("facing"):
            facing = m["facing"]
            break

    return {
        "center": center,
        "dimensions": dimensions,
        "top_z": top_z,
        "material": dominant_mat,
        "facing": facing,
    }


def _compute_semantic_groups(visible_objects, scene):
    """Collapse multi-mesh imports into single composite entries.

    Two grouping strategies:
    1. Sketchfab root: objects sharing a Sketchfab_model* parent
    2. Source base name: objects sharing the same src= base (catches duplicated imports)

    Returns list of {root, display_name, center, dimensions, top_z, member_count, members, material, facing}.
    """
    import re

    groups = []
    already_grouped = set()  # Track which objects are already in a group

    # -- Strategy 1: Sketchfab root grouping --
    sketchfab_roots = {}
    for obj in scene.objects:
        if obj.name.startswith("Sketchfab_model") and obj.type == 'EMPTY':
            sketchfab_roots[obj.name] = obj

    obj_lookup = {od["name"]: od for od in visible_objects}

    if sketchfab_roots:
        root_members = {}
        for obj in scene.objects:
            if obj.name not in obj_lookup:
                continue
            current = obj.parent
            while current:
                if current.name in sketchfab_roots:
                    root_members.setdefault(current.name, []).append(obj_lookup[obj.name])
                    break
                current = current.parent

        for root_name, members in root_members.items():
            if len(members) < 2:
                continue

            root_obj = sketchfab_roots[root_name]

            # Extract display name
            display_name = None

            # Check user-assigned parent
            if root_obj.parent and not root_obj.parent.name.startswith("Sketchfab_"):
                display_name = root_obj.parent.name

            # Walk hierarchy for semantic name
            if not display_name:
                _generic = ("root.", "GLTF_", "Object_", "RootNode", "Sketchfab_")
                def _find_semantic(obj, depth=0):
                    if depth > 5:
                        return None
                    for child in obj.children:
                        name = child.name
                        if not any(name.startswith(p) for p in _generic):
                            if not re.search(r'\.(obj|fbx|gles|glb|gltf)\b', name, re.I):
                                return name
                        result = _find_semantic(child, depth + 1)
                        if result:
                            return result
                    return None
                display_name = _find_semantic(root_obj)

            # Fallback: src= from member
            if not display_name:
                for m in members:
                    src = m.get("source")
                    if src:
                        display_name = _src_base_name(src)
                        break

            if not display_name:
                for child in root_obj.children:
                    if not child.name.startswith("Sketchfab_"):
                        display_name = child.name
                        break

            if not display_name:
                display_name = root_name

            # Clean up
            display_name = re.sub(r'\.\d{3}$', '', display_name)
            display_name = re.sub(r'\.(obj|fbx|gles|glb|gltf).*$', '', display_name, flags=re.I)
            display_name = display_name.replace("_", " ").strip()

            agg = _aggregate_group(members)
            if not agg:
                continue

            member_names = [m["name"] for m in members]
            already_grouped.update(member_names)

            groups.append({
                "root": root_name,
                "display_name": display_name,
                "center": agg["center"],
                "dimensions": agg["dimensions"],
                "top_z": agg["top_z"],
                "material": agg["material"],
                "facing": agg["facing"],
                "member_count": len(members),
                "members": member_names,
            })

    # -- Strategy 2: Source base-name grouping --
    # Group objects with matching src= base that aren't already in a Sketchfab group
    src_groups = {}  # base_name -> [obj_data]
    for od in visible_objects:
        if od["name"] in already_grouped:
            continue
        src = od.get("source")
        if not src:
            continue
        base = _src_base_name(src)
        if base:
            src_groups.setdefault(base, []).append(od)

    for base_name, members in src_groups.items():
        if len(members) < 2:
            continue

        # Check if all members are at the same position (same import)
        # vs spread around (duplicated furniture) — group either way
        display_name = base_name
        display_name = re.sub(r'\.(obj|fbx|gles|glb|gltf).*$', '', display_name, flags=re.I)
        display_name = display_name.replace("_", " ").strip()

        agg = _aggregate_group(members)
        if not agg:
            continue

        member_names = [m["name"] for m in members]
        already_grouped.update(member_names)

        groups.append({
            "root": f"src:{base_name}",
            "display_name": display_name,
            "center": agg["center"],
            "dimensions": agg["dimensions"],
            "top_z": agg["top_z"],
            "material": agg["material"],
            "facing": agg["facing"],
            "member_count": len(members),
            "members": member_names,
        })

    return groups


def compute(ctx):
    # Skip if already computed inline by perception.py orchestrator
    if ctx.result.get("semantic_groups"):
        return {}
    groups = _compute_semantic_groups(ctx.visible_objects, ctx.scene)
    return {"semantic_groups": groups} if groups else {}


register("semantic_groups", compute, emits=["semantic_groups"])
