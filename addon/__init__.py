from .properties import register_properties, unregister_properties
from .ui_panel import UI_CLASSES
import bpy


def _auto_connect():
    """Auto-connect to MCP server on addon load."""
    from .server_bridge import BlenderWeaveClient
    if not hasattr(bpy.types, "blenderweave_server") or not bpy.types.blenderweave_server:
        bpy.types.blenderweave_server = BlenderWeaveClient()
    bpy.types.blenderweave_server.start()
    bpy.context.scene.blenderweave_server_running = True
    return None  # Don't repeat


def register():
    register_properties()
    for cls in UI_CLASSES:
        bpy.utils.register_class(cls)
    # Auto-connect after a short delay (scene properties need to be ready)
    bpy.app.timers.register(_auto_connect, first_interval=1.0)
    print("BlenderWeave addon registered")


def unregister():
    # Stop the client if it's running
    if hasattr(bpy.types, "blenderweave_server") and bpy.types.blenderweave_server:
        bpy.types.blenderweave_server.stop()
        bpy.types.blenderweave_server = None

    for cls in reversed(UI_CLASSES):
        bpy.utils.unregister_class(cls)
    unregister_properties()
    print("BlenderWeave addon unregistered")


if __name__ == "__main__":
    register()
