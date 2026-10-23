"""What a .blend holds: its datablocks by kind, its files' paths, what is missing, what is linked from libraries."""
import bpy
import os

KINDS = ("objects", "meshes", "materials", "node_groups", "images", "textures", "lights", "cameras", "worlds",
         "collections", "scenes", "actions", "armatures", "curves", "hair_curves", "grease_pencils", "fonts",
         "sounds", "movieclips", "libraries", "volumes", "pointclouds", "texts", "brushes", "palettes", "workspaces")


def summary(names=8):
    """Every kind of datablock with its count, how many are linked, unused (no users) or fake-user kept, and the
    first names."""
    out = {}
    for k in KINDS:
        coll = getattr(bpy.data, k, None)
        if coll is None or not len(coll):
            continue
        items = list(coll)
        out[k] = {"count": len(items), "linked": sum(1 for i in items if getattr(i, "library", None)),
                  "unused": sum(1 for i in items if i.users == 0), "fake_user": sum(1 for i in items if getattr(i, "use_fake_user", False)),
                  "names": [i.name for i in items[:names]]}
    return {"file": bpy.data.filepath or None, "saved": bool(bpy.data.filepath), "dirty": bpy.data.is_dirty, "datablocks": out}


def _abs(path, lib=None):
    return os.path.normpath(bpy.path.abspath(path, library=lib)) if path else ""


def paths():
    """Every external file the scene uses (images, libraries, sounds, fonts, caches) with its path as written,
    absolute, and whether it exists."""
    out = []
    for kind in ("images", "libraries", "sounds", "fonts", "movieclips", "volumes", "cache_files"):
        for d in getattr(bpy.data, kind, []):
            fp = getattr(d, "filepath", "")
            if not fp or (kind == "images" and d.packed_file) or (kind == "fonts" and fp == "<builtin>"):
                continue
            a = _abs(fp, getattr(d, "library", None))
            out.append({"kind": kind, "name": d.name, "path": fp, "absolute": a, "relative": fp.startswith("//"), "exists": os.path.exists(a)})
    return {"file": bpy.data.filepath or None, "paths": out}


def missing():
    """External files that are not where the scene expects them."""
    p = paths()
    return {"file": p["file"], "missing": [e for e in p["paths"] if not e["exists"]]}


def libraries():
    """Linked libraries and what each provides."""
    out = []
    for lib in bpy.data.libraries:
        provided = {}
        for k in KINDS:
            coll = getattr(bpy.data, k, None)
            if coll is None:
                continue
            n = [i.name for i in coll if getattr(i, "library", None) == lib]
            if n:
                provided[k] = n[:20]
        out.append({"name": lib.name, "path": lib.filepath, "absolute": _abs(lib.filepath), "exists": os.path.exists(_abs(lib.filepath)), "provides": provided})
    return {"libraries": out}
