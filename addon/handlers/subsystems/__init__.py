"""Perception subsystems package — auto-discovers and registers all modules.

Each module defines a `compute(ctx)` function and calls `register()` from
perception_registry at import time.
"""
import importlib
import pkgutil
import os

_discovered = False


def discover():
    """Import all sibling modules to trigger their register() calls."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    package_dir = os.path.dirname(__file__)
    for _, module_name, _ in pkgutil.iter_modules([package_dir]):
        if module_name.startswith("_"):
            continue
        try:
            importlib.import_module(f".{module_name}", package=__name__)
        except Exception:
            import traceback
            traceback.print_exc()
