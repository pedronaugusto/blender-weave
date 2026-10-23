"""Blender's Python API, read from the running Blender itself.

Builds a reference of every RNA type (its properties with their types, enum items, defaults and descriptions, and
its functions with parameters and returns), every operator (its properties), and the Python modules (mathutils,
bmesh, gpu, bpy.utils, bpy.props, bpy.app...) from their docstrings. Written as JSON to a path the MCP server gives,
per Blender version, so the server can search it without Blender's documentation being shipped with BlenderWeave.
"""
import bpy
import inspect
import json
import os


def _rna_type(p):
    t = p.type
    if t == 'POINTER':
        return f"pointer to {p.fixed_type.identifier}" if getattr(p, "fixed_type", None) else "pointer"
    if t == 'COLLECTION':
        return f"collection of {p.fixed_type.identifier}" if getattr(p, "fixed_type", None) else "collection"
    if t == 'ENUM':
        return "enum set" if p.is_enum_flag else "enum"
    if getattr(p, "array_length", 0):
        return f"{t.lower()} array[{p.array_length}]"
    return t.lower()


def _rna_property(p):
    entry = {"name": p.identifier, "type": _rna_type(p), "description": p.description or ""}
    if p.is_readonly:
        entry["readonly"] = True
    if p.type == 'ENUM':
        entry["items"] = [{"id": i.identifier, "name": i.name, "description": i.description} for i in p.enum_items]
    elif p.type in ('INT', 'FLOAT') and not getattr(p, "array_length", 0):
        for k in ("default", "hard_min", "hard_max"):
            v = getattr(p, k, None)
            if v is not None:
                entry[k] = v
        if p.type == 'FLOAT' and getattr(p, "unit", 'NONE') != 'NONE':
            entry["unit"] = p.unit
    elif p.type in ('BOOLEAN', 'STRING') and not getattr(p, "array_length", 0):
        entry["default"] = p.default
    return entry


def _rna_function(f):
    params = [p for p in f.parameters if not p.is_output]
    outs = [p for p in f.parameters if p.is_output]
    sig = f"{f.identifier}(" + ", ".join(p.identifier for p in params) + ")"
    return {"name": f.identifier, "signature": sig, "description": f.description or "",
            "parameters": [_rna_property(p) for p in params], "returns": [_rna_property(p) for p in outs]}


def _types():
    out = []
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        rna = getattr(cls, "bl_rna", None)
        if rna is None or rna.identifier != name:
            continue
        base = rna.base.identifier if rna.base else None
        inherited_p = {p.identifier for p in rna.base.properties} if rna.base else set()
        inherited_f = {f.identifier for f in rna.base.functions} if rna.base else set()
        out.append({
            "path": f"bpy.types.{name}", "kind": "type", "name": name, "base": base,
            "description": rna.description or "",
            "properties": [_rna_property(p) for p in rna.properties if p.identifier != "rna_type" and p.identifier not in inherited_p],
            "functions": [_rna_function(f) for f in rna.functions if f.identifier not in inherited_f],
        })
    return out


def _sockets(node):
    def one(s):
        e = {"name": s.name, "identifier": s.identifier, "type": s.bl_idname}
        if hasattr(s, "default_value"):
            try:
                v = s.default_value
                v = list(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
                if isinstance(v, (bool, int, float, str)) or (isinstance(v, list) and all(isinstance(x, (int, float)) for x in v)):
                    e["default"] = v
            except Exception:
                pass
        return e
    return [one(s) for s in node.inputs], [one(s) for s in node.outputs]


def _node_sockets():
    # every shader, geometry and compositor node's sockets, read off a node made in a throwaway tree: what the RNA
    # does not list (a node's inputs are made when it is)
    out = {}
    trees = []
    try:
        trees.append(("ShaderNode", bpy.data.node_groups.new("_bw_docs_shader", "ShaderNodeTree")))
        trees.append(("GeometryNode", bpy.data.node_groups.new("_bw_docs_geometry", "GeometryNodeTree")))
        trees.append(("FunctionNode", trees[-1][1]))
        trees.append(("CompositorNode", bpy.data.node_groups.new("_bw_docs_compositor", "CompositorNodeTree")))
    except Exception:
        pass
    for prefix, tree in trees:
        for name in dir(bpy.types):
            if not name.startswith(prefix) or name in out:
                continue
            try:
                n = tree.nodes.new(name)
            except Exception:
                continue
            ins, outs = _sockets(n)
            out[name] = {"inputs": ins, "outputs": outs}
            tree.nodes.remove(n)
    for _, tree in trees:
        try:
            bpy.data.node_groups.remove(tree)
        except Exception:
            pass
    return out


def _operators():
    out = []
    for module in dir(bpy.ops):
        if module.startswith("_"):
            continue
        sub = getattr(bpy.ops, module)
        for name in dir(sub):
            if name.startswith("_"):
                continue
            try:
                rna = getattr(sub, name).get_rna_type()
            except Exception:
                continue
            props = [_rna_property(p) for p in rna.properties if p.identifier != "rna_type"]
            out.append({"path": f"bpy.ops.{module}.{name}", "kind": "operator", "name": f"{module}.{name}",
                        "description": rna.description or "",
                        "signature": f"bpy.ops.{module}.{name}(" + ", ".join(p["name"] for p in props) + ")",
                        "properties": props})
    return out


def _module(mod, path, depth=0, seen=None):
    seen = seen if seen is not None else set()
    if id(mod) in seen or depth > 2:
        return []
    seen.add(id(mod))
    out = [{"path": path, "kind": "module", "name": path, "description": inspect.getdoc(mod) or ""}]
    for name in dir(mod):
        if name.startswith("_"):
            continue
        try:
            obj = getattr(mod, name)
        except Exception:
            continue
        p = f"{path}.{name}"
        if inspect.ismodule(obj):
            if getattr(obj, "__name__", "").startswith(path.split(".")[0]):
                out += _module(obj, p, depth + 1, seen)
        elif inspect.isclass(obj):
            members = []
            for m in dir(obj):
                if m.startswith("_"):
                    continue
                try:
                    a = getattr(obj, m)
                except Exception:
                    continue
                doc = inspect.getdoc(a) or ""
                if doc:
                    members.append({"name": m, "description": doc})
            out.append({"path": p, "kind": "class", "name": name, "description": inspect.getdoc(obj) or "", "members": members})
        elif callable(obj):
            out.append({"path": p, "kind": "function", "name": name, "description": inspect.getdoc(obj) or ""})
        else:
            doc = inspect.getdoc(obj)
            if isinstance(obj, (int, float, str, tuple)) and len(repr(obj)) < 200:
                out.append({"path": p, "kind": "value", "name": name, "description": repr(obj)})
    return out


MODULES = ("mathutils", "bmesh", "gpu", "gpu_extras", "bpy_extras", "aud", "blf", "idprop", "imbuf", "freestyle")


def build_api_docs(filepath):
    """Write the API reference of this Blender to filepath (JSON). Returns how many entries."""
    import importlib
    entries = _types() + _operators()
    sockets = _node_sockets()
    for e in entries:
        if e["kind"] == "type" and e["name"] in sockets:
            e["sockets"] = sockets[e["name"]]
    for name in ("bpy.utils", "bpy.props", "bpy.app", "bpy.path", "bpy.msgbus"):
        mod = getattr(bpy, name.split(".")[1], None)   # some are attributes of bpy, not importable modules
        if mod is None:
            try:
                mod = importlib.import_module(name)
            except Exception:
                continue
        entries += _module(mod, name)
    for name in MODULES:
        try:
            entries += _module(importlib.import_module(name), name)
        except Exception:
            pass
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    meta = {"blender_version": ".".join(str(v) for v in bpy.app.version), "build": bpy.app.build_hash.decode()
            if isinstance(bpy.app.build_hash, bytes) else str(bpy.app.build_hash), "count": len(entries)}
    with open(filepath, "w") as f:
        json.dump({"meta": meta, "entries": entries}, f)
    return {"success": True, "filepath": filepath, **meta}
