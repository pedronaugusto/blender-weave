"""BlenderWeave's built-in documentation, for the Blender that is connected.

Two sources, both made or fetched on the user's machine, so nothing of Blender's is shipped with BlenderWeave:
- the Python API, read from the running Blender itself by the add-on (addon/handlers/docs.py): every type with its
  own properties, enum items, defaults and functions, every operator, the Python modules, and every shader, geometry
  and compositor node's sockets;
- the Blender manual's source for the same version (projects.blender.org/blender/blender-manual, CC BY-SA 4.0),
  fetched once as text only (a sparse clone of its .rst files).
Each is split into entries and searched with BM25, names weighing more than prose. Cached in
~/.blenderweave/docs/<version>/.
"""
import json
import math
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

DOCS_DIR = Path.home() / ".blenderweave" / "docs"
MANUAL_GIT = "https://projects.blender.org/blender/blender-manual.git"
WORD = re.compile(r"[a-z0-9]+")


def _words(text):
    # words, with identifiers split too: "ShaderNodeBsdfPrincipled" -> shader node bsdf principled, "use_smooth" -> use smooth
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    return WORD.findall(text.lower())


class Index:
    """BM25 over entries' name and body; names count three times."""

    def __init__(self, entries, name, body):
        self.entries = entries
        self.docs = []
        df = Counter()
        for e in entries:
            terms = Counter(_words(body(e)))
            for t in _words(name(e)): terms[t] += 3
            self.docs.append(terms)
            df.update(terms.keys())
        n = max(1, len(entries))
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.avg = sum(sum(d.values()) for d in self.docs) / n
        self.postings = defaultdict(list)
        for i, d in enumerate(self.docs):
            for t in d:
                self.postings[t].append(i)

    def search(self, query, limit=8, k1=1.2, b=0.75):
        terms = _words(query)
        scores = defaultdict(float)
        for t in terms:
            for i in self.postings.get(t, ()):
                d = self.docs[i]; f = d[t]; L = sum(d.values())
                scores[i] += self.idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * L / self.avg))
        best = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
        return [(self.entries[i], s) for i, s in best]


# ---- the API --------------------------------------------------------------------------------------------------------

_api = {}


def api_path(version):
    return DOCS_DIR / version / "api.json"


def api(version, build):
    """The API index for this Blender version, built through the add-on the first time (build(filepath) -> result)."""
    if version in _api:
        return _api[version]
    path = api_path(version)
    if not path.exists():
        build(str(path))
    data = json.loads(path.read_text())
    body = lambda e: " ".join([e.get("description", ""), e.get("signature", "")]
                              + [p["name"] + " " + p.get("description", "") for p in e.get("properties", [])]
                              + [f["name"] + " " + f.get("description", "") for f in e.get("functions", [])]
                              + [s["name"] for s in e.get("sockets", {}).get("inputs", [])])
    _api[version] = (Index(data["entries"], lambda e: e["path"], body), {e["path"]: e for e in data["entries"]}, data["meta"])
    return _api[version]


def _prop_line(p):
    bits = [p["name"], f"({p['type']})"]
    if p.get("readonly"): bits.append("readonly")
    for k in ("default", "hard_min", "hard_max", "unit"):
        if k in p: bits.append(f"{k}={p[k]}")
    line = "  " + " ".join(str(b) for b in bits)
    if p.get("description"): line += f" — {p['description']}"
    if p.get("items"):
        line += "\n    items: " + ", ".join(i["id"] for i in p["items"][:60]) + (" …" if len(p["items"]) > 60 else "")
    return line


def format_api(e):
    out = [f"{e['path']}  [{e['kind']}]"]
    if e.get("base"): out.append(f"base: bpy.types.{e['base']} (inherited members are listed there)")
    if e.get("signature"): out.append(e["signature"])
    if e.get("description"): out.append(e["description"])
    if e.get("sockets"):
        s = e["sockets"]
        out.append("inputs:  " + ", ".join(f"{x['name']} ({x['type'].replace('NodeSocket', '')}{', ' + str(x['default']) if 'default' in x else ''})" for x in s["inputs"]))
        out.append("outputs: " + ", ".join(f"{x['name']} ({x['type'].replace('NodeSocket', '')})" for x in s["outputs"]))
    if e.get("properties"):
        out.append("properties:"); out += [_prop_line(p) for p in e["properties"]]
    for f in e.get("functions", []):
        out.append(f"function {f['signature']}" + (f" — {f['description']}" if f.get("description") else ""))
        out += ["  " + _prop_line(p) for p in f.get("parameters", [])]
        if f.get("returns"): out.append("  returns: " + ", ".join(p["name"] + f" ({p['type']})" for p in f["returns"]))
    for m in e.get("members", []):
        out.append(f"  .{m['name']} — {m['description'].splitlines()[0] if m['description'] else ''}")
    return "\n".join(out)


# ---- the manual -----------------------------------------------------------------------------------------------------

_manual = {}
HEADING = re.compile(r"^(=+|-+|~+|\^+|\*+|#+)\s*$")


def manual_dir(version):
    return DOCS_DIR / version / "manual"


def fetch_manual(version):
    """The manual's .rst files for this version (blender-vX.Y-release, else main), cloned sparse, text only."""
    target = manual_dir(version)
    if (target / "manual").exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    major_minor = ".".join(version.split(".")[:2])
    for branch in (f"blender-v{major_minor}-release", "main"):
        subprocess.run(["rm", "-rf", str(target)])
        r = subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--sparse", "--branch", branch, MANUAL_GIT, str(target)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            subprocess.run(["git", "-C", str(target), "sparse-checkout", "set", "--no-cone", "/manual/**/*.rst"], capture_output=True, text=True, timeout=1200)
            (target / ".branch").write_text(branch)
            return target
    raise RuntimeError(f"could not fetch the Blender manual: {r.stderr.strip()[:300]}")


def _clean(text):
    text = re.sub(r"^\.\. _[^:]+:\s*$", "", text, flags=re.M)               # .. _label:
    text = re.sub(r"^\s*[=*#~^-]{3,}\s*$", "", text, flags=re.M)            # heading over- and underlines
    text = re.sub(r"^\s*:[a-z-]+:.*$", "", text, flags=re.M)                 # :align: center, :width: 50%
    text = re.sub(r":[a-z]+:`([^`<]*?)(?:\s*<[^>]*>)?`", r"\1", text)      # :ref:`Title <target>` -> Title
    text = re.sub(r"\.\. (figure|image|youtube|peertube)::.*", "", text)
    text = re.sub(r"\.\. [a-z-]+::", "", text)
    text = re.sub(r"\|[a-z0-9_-]+\|", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _sections(path, root):
    lines = path.read_text(errors="ignore").splitlines()
    rel = str(path.relative_to(root / "manual"))[:-4]
    out, title, buf = [], None, []
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and HEADING.match(lines[i + 1]) and line.strip() and len(lines[i + 1].strip()) >= len(line.strip()) * 0.6:
            if title is not None or buf:
                out.append((title or rel, buf))
            title, buf = line.strip(), []
            continue
        if HEADING.match(line) and buf == [] and title:
            continue
        buf.append(line)
    out.append((title or rel, buf))
    return [{"path": f"{rel}#{t}", "page": rel, "title": t, "text": _clean("\n".join(b))} for t, b in out if "".join(b).strip()]


def manual(version):
    if version in _manual:
        return _manual[version]
    root = fetch_manual(version)
    entries = []
    for p in sorted((root / "manual").rglob("*.rst")):
        entries += _sections(p, root)
    _manual[version] = (Index(entries, lambda e: e["page"] + " " + e["title"], lambda e: e["text"]), {e["path"]: e for e in entries}, entries)
    return _manual[version]


def page(text, offset=0, size=6000):
    """A long text in pieces: this piece, and where the next starts (or None)."""
    piece = text[offset:offset + size]
    nxt = offset + size if offset + size < len(text) else None
    return piece + (f"\n\n[more: offset={nxt}]" if nxt else "")
