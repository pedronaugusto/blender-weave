import bpy
import traceback

from ._compat import normalize_engine, is_eevee, has_eevee_attr


def set_viewport_shading(mode, options=None):
    """Set the viewport shading mode.

    Args:
        mode: Shading mode — WIREFRAME, SOLID, MATERIAL, RENDERED
        options: Optional dict of shading settings:
            For SOLID: cavity, xray, studio_light, color_type, single_color
            For RENDERED: use_scene_world, use_scene_lights

    Returns:
        dict with success status
    """
    try:
        area = None
        for a in bpy.context.screen.areas:
            if a.type == 'VIEW_3D':
                area = a
                break
        if not area:
            return {"error": "No 3D viewport found"}

        space = area.spaces[0]
        mode = mode.upper()

        if mode not in ("WIREFRAME", "SOLID", "MATERIAL", "RENDERED"):
            return {"error": f"Unknown mode: {mode}. Use WIREFRAME, SOLID, MATERIAL, or RENDERED"}

        space.shading.type = mode

        if options:
            shading = space.shading
            for key, val in options.items():
                if hasattr(shading, key):
                    setattr(shading, key, val)

        return {
            "success": True,
            "message": f"Viewport shading set to {mode}",
            "mode": mode,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to set viewport shading: {str(e)}"}


def configure_render_settings(settings):
    """Configure render and world settings.

    Args:
        settings: Dict of settings to configure. Whitelisted keys:
            Render:
              - engine: "CYCLES", "BLENDER_EEVEE", "BLENDER_WORKBENCH"
                        (BLENDER_EEVEE_NEXT also accepted for backwards compatibility)
              - samples: render sample count
              - resolution_x, resolution_y: render resolution
              - film_transparent: transparent background (bool)
              - use_motion_blur: motion blur (bool)
            EEVEE:
              - use_bloom: bloom effect (bool)
              - use_ssr: screen space reflections (bool)
              - use_gtao: ambient occlusion (bool)
            Color Management:
              - view_transform: "Standard", "Filmic", "AgX", etc.
              - look: color look preset
              - exposure: exposure value
              - gamma: gamma value
            World:
              - world_color: [r, g, b] world background color

    Returns:
        dict with changed settings
    """
    try:
        if not settings:
            return {"error": "settings dict is required"}

        scene = bpy.context.scene
        changed = []

        # Render engine
        if "engine" in settings:
            scene.render.engine = normalize_engine(settings["engine"])
            changed.append("engine")

        # Render settings
        render_keys = ["samples", "film_transparent", "use_motion_blur"]
        for key in render_keys:
            if key in settings:
                if key == "samples":
                    if scene.render.engine == 'CYCLES':
                        scene.cycles.samples = settings[key]
                    elif is_eevee(scene.render.engine):
                        if hasattr(scene.eevee, 'taa_render_samples'):
                            scene.eevee.taa_render_samples = settings[key]
                elif key == "film_transparent":
                    scene.render.film_transparent = settings[key]
                elif key == "use_motion_blur":
                    scene.render.use_motion_blur = settings[key]
                changed.append(key)

        # Resolution
        if "resolution_x" in settings:
            scene.render.resolution_x = settings["resolution_x"]
            changed.append("resolution_x")
        if "resolution_y" in settings:
            scene.render.resolution_y = settings["resolution_y"]
            changed.append("resolution_y")

        # EEVEE features
        eevee_keys = {"use_bloom": "use_bloom", "use_ssr": "use_ssr", "use_gtao": "use_gtao"}
        for key, attr in eevee_keys.items():
            if key in settings and hasattr(scene.eevee, attr):
                setattr(scene.eevee, attr, settings[key])
                changed.append(key)

        # EEVEE ray tracing (Blender 5+)
        if "use_ray_tracing" in settings and has_eevee_attr("use_raytracing"):
            scene.eevee.use_raytracing = settings["use_ray_tracing"]
            changed.append("use_ray_tracing")

        # Color management preset
        if "color_management_preset" in settings:
            preset = settings["color_management_preset"]
            if preset == "ACES" and hasattr(scene.display_settings, 'display_device'):
                scene.display_settings.display_device = 'ACES'
                changed.append("color_management_preset")
            elif preset == "sRGB":
                scene.display_settings.display_device = 'sRGB'
                changed.append("color_management_preset")

        # Color management
        cm_keys = ["view_transform", "look", "exposure", "gamma"]
        for key in cm_keys:
            if key in settings:
                if hasattr(scene.view_settings, key):
                    setattr(scene.view_settings, key, settings[key])
                    changed.append(key)

        # World color
        if "world_color" in settings:
            world = scene.world
            if not world:
                world = bpy.data.worlds.new("World")
                scene.world = world
            if not world.use_nodes:
                world.use_nodes = True
            bg = None
            for node in world.node_tree.nodes:
                if node.type == 'BACKGROUND':
                    bg = node
                    break
            if bg:
                c = settings["world_color"]
                bg.inputs["Color"].default_value = (c[0], c[1], c[2], 1.0)
                changed.append("world_color")

        return {
            "success": True,
            "message": f"Updated {len(changed)} render settings",
            "changed": changed,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Failed to configure render settings: {str(e)}"}
