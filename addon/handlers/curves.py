"""Curve operations — create, edit, convert curves."""
import bpy
import traceback


def manage_curves(action, object_name=None, name=None, curve_type="BEZIER",
                  points=None, cyclic=False, point=None, index=-1,
                  spline_index=0, bevel_depth=None, bevel_resolution=None,
                  extrude=None, resolution_u=None, fill_mode=None):
    """Manage curve objects.

    Actions:
    - create: Create curve from points [[x,y,z], ...]
    - add_point: Insert control point at index
    - set_point: Move control point at index
    - set_properties: Set curve shape properties (bevel, extrude, etc.)
    - to_mesh: Convert curve to mesh
    - list_points: Get all control points from spline
    """
    try:
        if action == "create":
            return _create_curve(name or "Curve", curve_type, points or [], cyclic)
        elif action == "add_point":
            return _add_point(object_name, point, index, spline_index)
        elif action == "set_point":
            return _set_point(object_name, index, point, spline_index)
        elif action == "set_properties":
            return _set_properties(object_name, bevel_depth, bevel_resolution,
                                   extrude, resolution_u, fill_mode)
        elif action == "to_mesh":
            return _to_mesh(object_name)
        elif action == "list_points":
            return _list_points(object_name, spline_index)
        else:
            return {"error": f"Unknown action: {action}"}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def _create_curve(name, curve_type, points, cyclic):
    if len(points) < 2:
        return {"error": "At least 2 points required"}

    curve_data = bpy.data.curves.new(name, 'CURVE')
    curve_data.dimensions = '3D'

    spline = curve_data.splines.new(curve_type)

    if curve_type == 'BEZIER':
        spline.bezier_points.add(len(points) - 1)
        for i, pt in enumerate(points):
            bp = spline.bezier_points[i]
            bp.co = (pt[0], pt[1], pt[2])
            # Auto handles
            bp.handle_left_type = 'AUTO'
            bp.handle_right_type = 'AUTO'
    elif curve_type in ('POLY', 'NURBS'):
        spline.points.add(len(points) - 1)
        for i, pt in enumerate(points):
            # Spline points need 4 coords (x, y, z, w)
            spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

    spline.use_cyclic_u = cyclic

    obj = bpy.data.objects.new(name, curve_data)
    bpy.context.collection.objects.link(obj)

    return {
        "success": True,
        "message": f"Created {curve_type} curve '{name}' with {len(points)} points",
        "object_name": obj.name,
        "curve_type": curve_type,
        "point_count": len(points),
    }


def _add_point(object_name, point, index, spline_index):
    obj = bpy.data.objects.get(object_name)
    if not obj or obj.type != 'CURVE':
        return {"error": f"Curve object '{object_name}' not found"}
    if not point or len(point) < 3:
        return {"error": "point must be [x, y, z]"}

    curve = obj.data
    if spline_index >= len(curve.splines):
        return {"error": f"Spline index {spline_index} out of range"}

    spline = curve.splines[spline_index]

    if spline.type == 'BEZIER':
        spline.bezier_points.add(1)
        bp = spline.bezier_points[-1]
        bp.co = (point[0], point[1], point[2])
        bp.handle_left_type = 'AUTO'
        bp.handle_right_type = 'AUTO'
        count = len(spline.bezier_points)
    else:
        spline.points.add(1)
        spline.points[-1].co = (point[0], point[1], point[2], 1.0)
        count = len(spline.points)

    return {
        "success": True,
        "message": f"Added point to '{object_name}' spline {spline_index}",
        "point_count": count,
    }


def _set_point(object_name, index, point, spline_index):
    obj = bpy.data.objects.get(object_name)
    if not obj or obj.type != 'CURVE':
        return {"error": f"Curve object '{object_name}' not found"}
    if not point or len(point) < 3:
        return {"error": "point must be [x, y, z]"}

    curve = obj.data
    if spline_index >= len(curve.splines):
        return {"error": f"Spline index {spline_index} out of range"}

    spline = curve.splines[spline_index]

    if spline.type == 'BEZIER':
        if index < 0 or index >= len(spline.bezier_points):
            return {"error": f"Point index {index} out of range (0-{len(spline.bezier_points)-1})"}
        spline.bezier_points[index].co = (point[0], point[1], point[2])
    else:
        if index < 0 or index >= len(spline.points):
            return {"error": f"Point index {index} out of range (0-{len(spline.points)-1})"}
        spline.points[index].co = (point[0], point[1], point[2], 1.0)

    return {
        "success": True,
        "message": f"Set point {index} on '{object_name}' to [{point[0]}, {point[1]}, {point[2]}]",
    }


def _set_properties(object_name, bevel_depth, bevel_resolution, extrude,
                     resolution_u, fill_mode):
    obj = bpy.data.objects.get(object_name)
    if not obj or obj.type != 'CURVE':
        return {"error": f"Curve object '{object_name}' not found"}

    curve = obj.data
    changed = []

    if bevel_depth is not None:
        curve.bevel_depth = bevel_depth
        changed.append(f"bevel_depth={bevel_depth}")
    if bevel_resolution is not None:
        curve.bevel_resolution = bevel_resolution
        changed.append(f"bevel_resolution={bevel_resolution}")
    if extrude is not None:
        curve.extrude = extrude
        changed.append(f"extrude={extrude}")
    if resolution_u is not None:
        curve.resolution_u = resolution_u
        changed.append(f"resolution_u={resolution_u}")
    if fill_mode is not None:
        curve.fill_mode = fill_mode
        changed.append(f"fill_mode={fill_mode}")

    return {
        "success": True,
        "message": f"Set properties on '{object_name}': {', '.join(changed)}",
        "changed": changed,
    }


def _to_mesh(object_name):
    obj = bpy.data.objects.get(object_name)
    if not obj or obj.type != 'CURVE':
        return {"error": f"Curve object '{object_name}' not found"}

    # Select and set active
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.object.convert(target='MESH')

    return {
        "success": True,
        "message": f"Converted '{object_name}' to mesh",
        "object_name": obj.name,
        "type": obj.type,
    }


def _list_points(object_name, spline_index):
    obj = bpy.data.objects.get(object_name)
    if not obj or obj.type != 'CURVE':
        return {"error": f"Curve object '{object_name}' not found"}

    curve = obj.data
    if spline_index >= len(curve.splines):
        return {"error": f"Spline index {spline_index} out of range"}

    spline = curve.splines[spline_index]
    points_list = []

    if spline.type == 'BEZIER':
        for i, bp in enumerate(spline.bezier_points):
            points_list.append({
                "index": i,
                "co": [round(v, 4) for v in bp.co],
                "handle_left": [round(v, 4) for v in bp.handle_left],
                "handle_right": [round(v, 4) for v in bp.handle_right],
                "handle_left_type": bp.handle_left_type,
                "handle_right_type": bp.handle_right_type,
            })
    else:
        for i, pt in enumerate(spline.points):
            points_list.append({
                "index": i,
                "co": [round(v, 4) for v in pt.co[:3]],
                "weight": round(pt.co[3], 4),
            })

    return {
        "success": True,
        "object": object_name,
        "spline_index": spline_index,
        "spline_type": spline.type,
        "cyclic": spline.use_cyclic_u,
        "points": points_list,
        "count": len(points_list),
    }
