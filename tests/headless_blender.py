"""Blender in the background with the BlenderWeave add-on connected, for end-to-end tests.
    blender -b --factory-startup --python tests/headless_blender.py -- <seconds>
Background Blender runs no event loop, so bpy.app.timers never fire: this replaces timer registration with a queue
and runs it here, as Blender's main thread would."""
import sys, time, importlib.util, os
import bpy
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("blender_weave_addon", os.path.join(root, "addon", "__init__.py"),
                                              submodule_search_locations=[os.path.join(root, "addon")])
addon = importlib.util.module_from_spec(spec); sys.modules["blender_weave_addon"] = addon; spec.loader.exec_module(addon)
from blender_weave_addon import server_bridge
queue = []
bpy.app.timers.register = lambda fn, first_interval=0.0, **kw: queue.append(fn)
seconds = float(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else 120
addon.register()   # as enabling it does: its properties, panels, and (through the timer queue) its connection
end = time.time() + seconds
while time.time() < end:
    while queue:
        fn = queue.pop(0); again = fn()
        if isinstance(again, (int, float)): queue.append(fn)
    time.sleep(0.02)
    if os.path.exists("/tmp/blenderweave_headless_stop"): break
addon.unregister()
