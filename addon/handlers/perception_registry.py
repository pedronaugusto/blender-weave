"""Perception subsystem registry — dynamic registration and ordered execution.

Subsystems register themselves with a name, function, phase, and dependencies.
The orchestrator (perception.py) calls run_all() to execute them in dependency order.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_subsystems = []


@dataclass
class PerceptionContext:
    """Shared context passed to all subsystems."""
    mesh_objects: list           # [(obj, obj_data)]
    visible_objects: list        # [obj_data dicts]
    spatial_grid: Any            # Octree or SpatialGrid
    scene: Any                   # bpy.types.Scene
    depsgraph: Any               # bpy.types.Depsgraph
    cam: Any                     # Camera object or None
    lights: list                 # [light_info dicts]
    semantic_groups: list        # [sgroup dicts]
    world_info: dict             # world/HDRI info
    result: dict                 # accumulated perception result
    emissive_count: int = 0
    light_analysis: Optional[list] = None
    containment: Optional[list] = None
    spatial_relationships: Optional[list] = None
    include_flags: dict = field(default_factory=dict)


def register(name: str, fn: Callable, phase: str = "post",
             depends_on: Optional[List[str]] = None,
             emits: Optional[List[str]] = None):
    """Register a perception subsystem.

    Args:
        name: Unique subsystem identifier
        fn: Callable(ctx: PerceptionContext) -> dict with results to merge
        phase: "post" (after Phase 3), "pre" (before Phase 2)
        depends_on: List of subsystem names that must run first
        emits: List of result keys this subsystem produces
    """
    _subsystems.append({
        "name": name,
        "fn": fn,
        "phase": phase,
        "depends_on": depends_on or [],
        "emits": emits or [],
    })


def run_all(ctx: PerceptionContext, phase: str = "post") -> dict:
    """Run all registered subsystems in dependency order for given phase.

    Returns merged results dict from all subsystems.
    """
    # Filter by phase
    phase_subs = [s for s in _subsystems if s["phase"] == phase]

    # Topological sort by dependencies
    ordered = _topo_sort(phase_subs)

    merged = {}
    for sub in ordered:
        try:
            result = sub["fn"](ctx)
            if isinstance(result, dict):
                merged.update(result)
                # Also update context.result so downstream subsystems can access
                ctx.result.update(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            merged.setdefault("_errors", []).append(f"{sub['name']}: {e}")

    return merged


def _topo_sort(subsystems):
    """Simple topological sort. Falls back to input order on cycles."""
    name_to_sub = {s["name"]: s for s in subsystems}
    visited = set()
    result = []

    def visit(sub):
        if sub["name"] in visited:
            return
        visited.add(sub["name"])
        for dep in sub["depends_on"]:
            if dep in name_to_sub:
                visit(name_to_sub[dep])
        result.append(sub)

    for sub in subsystems:
        visit(sub)

    return result


def get_registered() -> List[str]:
    """Return list of registered subsystem names."""
    return [s["name"] for s in _subsystems]
