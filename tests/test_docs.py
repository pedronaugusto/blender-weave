"""The docs index without Blender: identifiers split into words, names outweigh prose, the manual's .rst parsed into
sections and cleaned, long text paged. Run: uv run python tests/test_docs.py"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from blender_weave import docs


def test_words():
    assert docs._words("ShaderNodeBsdfPrincipled") == ["shader", "node", "bsdf", "principled"]
    assert docs._words("use_smooth") == ["use", "smooth"]


def test_names_outweigh_prose():
    entries = [{"path": "bpy.types.SubsurfModifier", "description": "Subdivision surface modifier"},
               {"path": "bpy.types.Mesh", "description": "a mesh, which a subsurf modifier may subdivide"}]
    idx = docs.Index(entries, lambda e: e["path"], lambda e: e["description"])
    assert idx.search("subsurf modifier")[0][0]["path"] == "bpy.types.SubsurfModifier"


def test_manual_sections():
    root = Path(tempfile.mkdtemp()); (root / "manual" / "render").mkdir(parents=True)
    (root / "manual" / "render" / "sss.rst").write_text(""".. _bpy.types.ShaderNodeSubsurfaceScattering:

********************
Subsurface Scattering
********************

The node adds :term:`subsurface` scattering.

.. figure:: /images/sss.png
   :align: center

Properties
==========

Method
   Random Walk (Skin), see :ref:`Principled <principled>`.
""")
    secs = docs._sections(root / "manual" / "render" / "sss.rst", root)
    titles = [s["title"] for s in secs]
    assert "Subsurface Scattering" in titles and "Properties" in titles, titles
    text = "\n".join(s["text"] for s in secs)
    assert ":align:" not in text and ".. _bpy" not in text and "****" not in text and "Principled" in text and "<principled>" not in text


def test_paging():
    t = "x" * 13000
    first = docs.page(t, 0, 6000)
    assert first.endswith("[more: offset=6000]") and docs.page(t, 12000, 6000) == "x" * 1000


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
