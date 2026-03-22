import bpy
import math
import traceback


def create_assembly(type, name=None, location=None, facing_direction=None,
                    dimensions=None, **_kw):
    """Create a multi-part furniture assembly with proper hierarchy.

    Args:
        type: "dining_chair", "table", "sofa", "floor_lamp", "bookshelf"
        name: Optional parent name
        location: [x, y, z] position
        facing_direction: [x, y] direction the front faces (default [0, -1])
        dimensions: Dict of type-specific dimension overrides

    Returns:
        dict with name, parts list, type
    """
    dispatch = {
        "dining_chair": _dining_chair,
        "table": _table,
        "sofa": _sofa,
        "floor_lamp": _floor_lamp,
        "bookshelf": _bookshelf,
    }

    handler = dispatch.get(type)
    if not handler:
        return {"error": f"Unknown assembly type: {type}. Use: {list(dispatch.keys())}"}

    try:
        loc = tuple(location) if location else (0, 0, 0)
        dims = dimensions or {}
        facing = facing_direction or [0, -1]

        # Compute rotation from facing direction
        angle = math.atan2(facing[0], -facing[1]) if len(facing) >= 2 else 0

        # Create parent empty
        parent_name = name or type.replace("_", " ").title()
        parent = bpy.data.objects.new(parent_name, None)
        parent.empty_display_type = 'PLAIN_AXES'
        parent.empty_display_size = 0.2
        parent.location = loc
        parent.rotation_euler = (0, 0, angle)
        bpy.context.scene.collection.objects.link(parent)

        # Build parts
        parts = handler(parent, dims)

        return {
            "success": True,
            "name": parent.name,
            "type": type,
            "parts": [p.name for p in parts],
            "location": list(parent.location),
            "rotation": [math.degrees(r) for r in parent.rotation_euler],
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to create assembly: {str(e)}"}


def _make_box(name, parent, dims, local_pos, material_color=None):
    """Create a box mesh, parent it, return the object."""
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = dims
    obj.location = local_pos
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.parent = parent
    if material_color:
        mat = bpy.data.materials.new(name=f"{name}_Mat")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = material_color
        obj.data.materials.append(mat)
    return obj


def _make_cylinder(name, parent, radius, depth, local_pos, material_color=None):
    """Create a cylinder mesh, parent it, return the object."""
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=12)
    obj = bpy.context.active_object
    obj.name = name
    obj.location = local_pos
    obj.parent = parent
    if material_color:
        mat = bpy.data.materials.new(name=f"{name}_Mat")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = material_color
        obj.data.materials.append(mat)
    return obj


# ---------------------------------------------------------------------------
# Dining Chair
# ---------------------------------------------------------------------------

def _dining_chair(parent, dims):
    sw = dims.get("seat_width", 0.42)
    sd = dims.get("seat_depth", 0.40)
    sh = dims.get("seat_height", 0.45)
    st = dims.get("seat_thickness", 0.03)
    bh = dims.get("back_height", 0.40)
    bt = dims.get("back_thickness", 0.025)
    lr = dims.get("leg_radius", 0.02)
    wood = (0.35, 0.2, 0.1, 1.0)

    parts = []
    # Seat
    parts.append(_make_box(f"{parent.name}_Seat", parent,
                           (sw, sd, st), (0, 0, sh), wood))
    # Back
    parts.append(_make_box(f"{parent.name}_Back", parent,
                           (sw, bt, bh), (0, -sd / 2 + bt / 2, sh + bh / 2), wood))
    # 4 legs
    leg_positions = [
        (sw / 2 - lr * 2, sd / 2 - lr * 2),
        (-sw / 2 + lr * 2, sd / 2 - lr * 2),
        (sw / 2 - lr * 2, -sd / 2 + lr * 2),
        (-sw / 2 + lr * 2, -sd / 2 + lr * 2),
    ]
    for i, (lx, ly) in enumerate(leg_positions):
        parts.append(_make_cylinder(f"{parent.name}_Leg{i}", parent,
                                    lr, sh - st / 2, (lx, ly, (sh - st / 2) / 2), wood))
    return parts


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

def _table(parent, dims):
    tw = dims.get("width", 1.4)
    td = dims.get("depth", 0.8)
    th = dims.get("height", 0.75)
    tt = dims.get("top_thickness", 0.04)
    lr = dims.get("leg_radius", 0.03)
    wood = (0.4, 0.25, 0.12, 1.0)

    parts = []
    # Tabletop
    parts.append(_make_box(f"{parent.name}_Top", parent,
                           (tw, td, tt), (0, 0, th), wood))
    # 4 legs
    inset = 0.05
    leg_positions = [
        (tw / 2 - inset, td / 2 - inset),
        (-tw / 2 + inset, td / 2 - inset),
        (tw / 2 - inset, -td / 2 + inset),
        (-tw / 2 + inset, -td / 2 + inset),
    ]
    leg_h = th - tt / 2
    for i, (lx, ly) in enumerate(leg_positions):
        parts.append(_make_cylinder(f"{parent.name}_Leg{i}", parent,
                                    lr, leg_h, (lx, ly, leg_h / 2), wood))
    return parts


# ---------------------------------------------------------------------------
# Sofa
# ---------------------------------------------------------------------------

def _sofa(parent, dims):
    sw = dims.get("width", 2.0)
    sd = dims.get("depth", 0.85)
    sh = dims.get("seat_height", 0.42)
    bh = dims.get("back_height", 0.35)
    ah = dims.get("arm_height", 0.25)
    aw = dims.get("arm_width", 0.15)
    cushion_t = dims.get("cushion_thickness", 0.15)
    fabric = (0.3, 0.3, 0.35, 1.0)

    parts = []
    # Base
    base_h = sh - cushion_t
    parts.append(_make_box(f"{parent.name}_Base", parent,
                           (sw, sd, base_h), (0, 0, base_h / 2), fabric))
    # Seat cushion
    parts.append(_make_box(f"{parent.name}_Cushion", parent,
                           (sw - aw * 2, sd - 0.1, cushion_t),
                           (0, 0.05, sh - cushion_t / 2), fabric))
    # Back
    parts.append(_make_box(f"{parent.name}_Back", parent,
                           (sw, 0.12, bh),
                           (0, -sd / 2 + 0.06, sh + bh / 2), fabric))
    # Left arm
    parts.append(_make_box(f"{parent.name}_ArmL", parent,
                           (aw, sd, ah),
                           (-sw / 2 + aw / 2, 0, sh + ah / 2), fabric))
    # Right arm
    parts.append(_make_box(f"{parent.name}_ArmR", parent,
                           (aw, sd, ah),
                           (sw / 2 - aw / 2, 0, sh + ah / 2), fabric))
    return parts


# ---------------------------------------------------------------------------
# Floor Lamp
# ---------------------------------------------------------------------------

def _floor_lamp(parent, dims):
    baser = dims.get("base_radius", 0.15)
    poleh = dims.get("pole_height", 1.5)
    shader = dims.get("shade_radius", 0.2)
    shadeh = dims.get("shade_height", 0.25)
    metal = (0.15, 0.15, 0.15, 1.0)
    shade_col = (0.9, 0.85, 0.75, 1.0)

    parts = []
    # Base disc
    parts.append(_make_cylinder(f"{parent.name}_Base", parent,
                                baser, 0.02, (0, 0, 0.01), metal))
    # Pole
    parts.append(_make_cylinder(f"{parent.name}_Pole", parent,
                                0.015, poleh, (0, 0, poleh / 2 + 0.02), metal))
    # Shade (cone-like cylinder)
    shade_z = poleh + 0.02
    parts.append(_make_cylinder(f"{parent.name}_Shade", parent,
                                shader, shadeh, (0, 0, shade_z + shadeh / 2),
                                shade_col))
    # Point light inside shade
    light_data = bpy.data.lights.new(name=f"{parent.name}_Bulb", type='POINT')
    light_data.energy = 100
    light_data.color = (1.0, 0.92, 0.8)
    light_obj = bpy.data.objects.new(f"{parent.name}_Bulb", light_data)
    light_obj.location = (0, 0, shade_z + shadeh * 0.3)
    light_obj.parent = parent
    bpy.context.scene.collection.objects.link(light_obj)
    parts.append(light_obj)

    return parts


# ---------------------------------------------------------------------------
# Bookshelf
# ---------------------------------------------------------------------------

def _bookshelf(parent, dims):
    bw = dims.get("width", 0.8)
    bd = dims.get("depth", 0.3)
    bh = dims.get("height", 1.8)
    shelves = dims.get("shelf_count", 4)
    st = dims.get("shelf_thickness", 0.02)
    side_t = dims.get("side_thickness", 0.02)
    wood = (0.45, 0.3, 0.15, 1.0)

    parts = []
    # Left side
    parts.append(_make_box(f"{parent.name}_SideL", parent,
                           (side_t, bd, bh),
                           (-bw / 2 + side_t / 2, 0, bh / 2), wood))
    # Right side
    parts.append(_make_box(f"{parent.name}_SideR", parent,
                           (side_t, bd, bh),
                           (bw / 2 - side_t / 2, 0, bh / 2), wood))
    # Back panel
    parts.append(_make_box(f"{parent.name}_BackPanel", parent,
                           (bw, 0.01, bh),
                           (0, -bd / 2 + 0.005, bh / 2), wood))
    # Shelves (including bottom and top)
    inner_w = bw - 2 * side_t
    for i in range(shelves + 1):
        z = (bh / shelves) * i
        parts.append(_make_box(f"{parent.name}_Shelf{i}", parent,
                               (inner_w, bd, st),
                               (0, 0, z + st / 2), wood))
    return parts
