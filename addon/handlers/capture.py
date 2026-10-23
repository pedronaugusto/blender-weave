"""Seeing Blender's window and moving about it: screenshots of the window or one area, the window's layout as data,
and jumping to an editor or to an object."""
import bpy


def _window():
    wm = bpy.context.window_manager
    return bpy.context.window or (wm.windows[0] if wm.windows else None)


def _areas(window):
    return list(window.screen.areas) if window and window.screen else []


def _fit(filepath, max_size):
    # shrink an image file in place so its longer side is at most max_size; returns its size
    img = bpy.data.images.load(filepath, check_existing=False)
    w, h = img.size
    if max(w, h) > max_size:
        s = max_size / max(w, h); w, h = max(1, int(w * s)), max(1, int(h * s))
        img.scale(w, h); img.filepath_raw = filepath; img.file_format = "PNG"; img.save()
    bpy.data.images.remove(img)
    return w, h


def screenshot_window(filepath, max_size=1600):
    """The whole Blender window as a PNG at filepath."""
    win = _window()
    if win is None:
        return {"error": "No Blender window (is Blender running in the background?)"}
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.screenshot(filepath=filepath, check_existing=False)
    w, h = _fit(filepath, max_size)
    return {"success": True, "filepath": filepath, "width": w, "height": h}


def screenshot_area(filepath, area_type="VIEW_3D", index=0, max_size=1600):
    """One area of the window (by its type: VIEW_3D, NODE_EDITOR, IMAGE_EDITOR, PROPERTIES, OUTLINER...) as a PNG."""
    win = _window()
    areas = [a for a in _areas(win) if a.type == area_type]
    if not areas:
        return {"error": f"No {area_type} area in the window; there are: {sorted({a.type for a in _areas(win)})}"}
    area = areas[min(index, len(areas) - 1)]
    region = next((r for r in area.regions if r.type == "WINDOW"), area.regions[0])
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=filepath, check_existing=False)
    w, h = _fit(filepath, max_size)
    return {"success": True, "filepath": filepath, "width": w, "height": h, "area": area_type}


def window_layout():
    """The window as data: its workspace, every area (type, position, size, what it shows), the active object and
    the selection."""
    win = _window()
    if win is None:
        return {"error": "No Blender window"}
    areas = []
    for i, a in enumerate(_areas(win)):
        e = {"index": i, "type": a.type, "ui_type": getattr(a, "ui_type", a.type), "x": a.x, "y": a.y, "width": a.width, "height": a.height}
        sp = a.spaces.active
        if a.type == "VIEW_3D":
            e["shading"] = sp.shading.type; e["camera_view"] = sp.region_3d.view_perspective
        elif a.type == "NODE_EDITOR":
            e["tree_type"] = sp.tree_type; e["tree"] = sp.node_tree.name if sp.node_tree else None
        elif a.type == "IMAGE_EDITOR":
            e["image"] = sp.image.name if sp.image else None
        elif a.type == "PROPERTIES":
            e["context"] = sp.context
        areas.append(e)
    ctx = bpy.context
    return {"workspace": win.workspace.name, "workspaces": [w.name for w in bpy.data.workspaces],
            "window": {"width": win.width, "height": win.height}, "areas": areas, "mode": ctx.mode,
            "active_object": ctx.view_layer.objects.active.name if ctx.view_layer.objects.active else None,
            "selected": [o.name for o in ctx.view_layer.objects if o.select_get()][:50]}


def jump_to_workspace(name):
    """Make a workspace (a tab: Layout, Shading, Sculpting...) the window's."""
    win = _window(); ws = bpy.data.workspaces.get(name)
    if ws is None:
        return {"error": f"No workspace {name!r}; there are: {[w.name for w in bpy.data.workspaces]}"}
    win.workspace = ws
    return {"success": True, "workspace": name}


def jump_to_object(name, frame=True):
    """Select an object, make it active, and frame it in every 3D view."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return {"error": f"No object {name!r}"}
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True); bpy.context.view_layer.objects.active = obj
    framed = 0
    if frame:
        win = _window()
        for a in _areas(win):
            if a.type == "VIEW_3D":
                region = next(r for r in a.regions if r.type == "WINDOW")
                with bpy.context.temp_override(window=win, screen=win.screen, area=a, region=region):
                    bpy.ops.view3d.view_selected()
                framed += 1
    return {"success": True, "object": name, "framed_views": framed}
