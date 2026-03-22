"""Blender version detection helpers for cross-version compatibility."""
import bpy


def blender_version():
    """Return Blender version as tuple, e.g. (5, 0, 0)."""
    return bpy.app.version


def is_blender5():
    """True if running Blender 5.0+."""
    return bpy.app.version >= (5, 0, 0)


def eevee_engine_id():
    """Return the correct EEVEE engine identifier for the current Blender version.

    Blender 5.0+ renamed BLENDER_EEVEE_NEXT → BLENDER_EEVEE.
    """
    if is_blender5():
        return 'BLENDER_EEVEE'
    return 'BLENDER_EEVEE_NEXT'


def is_eevee(engine_str):
    """Check if engine_str refers to EEVEE (either naming)."""
    return engine_str in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT')


def normalize_engine(engine_str):
    """Convert any EEVEE name to the correct one for current Blender version."""
    if is_eevee(engine_str):
        return eevee_engine_id()
    return engine_str


def get_eevee_settings(scene):
    """Return the EEVEE settings object (scene.eevee)."""
    return scene.eevee


def has_eevee_attr(name):
    """Check if the current EEVEE version has a specific attribute.

    Blender 5.0 removed some EEVEE attributes (use_bloom, use_ssr, use_gtao)
    and replaced them with new ones.
    """
    try:
        settings = bpy.context.scene.eevee
        return hasattr(settings, name)
    except Exception:
        return False
