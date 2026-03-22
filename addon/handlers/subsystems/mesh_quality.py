"""Mesh quality subsystem — flipped normals and non-manifold edge detection."""
import random
from ..perception_registry import register


def compute(ctx):
    if not ctx.include_flags.get("constraints"):
        return {}
    for obj, data in ctx.mesh_objects:
        if data.get("screen_coverage_pct", 0) < 2:
            continue
        try:
            mesh = obj.data
            if not mesh:
                continue
            if hasattr(mesh, 'polygons') and len(mesh.polygons) > 0:
                polys = mesh.polygons
                sample_size = min(100, len(polys))
                sample_indices = random.sample(range(len(polys)), sample_size) if len(polys) > 100 else range(len(polys))
                flipped = 0
                for idx in sample_indices:
                    poly = polys[idx]
                    face_center = obj.matrix_world @ poly.center
                    obj_center = obj.matrix_world.translation
                    outward = (face_center - obj_center).normalized()
                    world_normal = (obj.matrix_world.to_3x3() @ poly.normal).normalized()
                    if outward.dot(world_normal) < 0:
                        flipped += 1
                if sample_size > 0:
                    flipped_pct = round(flipped / sample_size * 100)
                    if flipped_pct > 20:
                        data["flipped_normals_pct"] = flipped_pct
            try:
                import bmesh
                bm = bmesh.new()
                bm.from_mesh(mesh)
                bm.edges.ensure_lookup_table()
                non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
                if non_manifold > 0:
                    data["non_manifold_edges"] = non_manifold
                bm.free()
            except Exception:
                pass
        except Exception:
            pass
    return {}


register("mesh_quality", compute, phase="post")
