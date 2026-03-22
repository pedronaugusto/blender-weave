import bpy
from bpy.props import IntProperty, BoolProperty, FloatProperty, StringProperty, EnumProperty


# Cache for dynamic enum to prevent garbage collection issues
_server_enum_cache = [("NONE", "No servers", "No MCP servers found")]


def _get_server_items(self, context):
    """Dynamic enum callback — discovers available MCP servers."""
    global _server_enum_cache
    try:
        from .server_bridge import discover_servers, _server_label
        servers = discover_servers()
        if not servers:
            _server_enum_cache = [("NONE", "No servers found", "Start an AI client with BlenderWeave")]
        else:
            _server_enum_cache = [
                (sid, _server_label(meta), f"PID {meta.get('pid', '?')} — {meta.get('cwd', '')}")
                for sid, meta in servers
            ]
    except Exception:
        _server_enum_cache = [("NONE", "Discovery error", "Could not scan for servers")]
    return _server_enum_cache


def register_properties():
    bpy.types.Scene.blenderweave_panel_tab = EnumProperty(
        name="Panel Tab",
        items=[
            ("CORE", "Core", "Server, perception, and scene intelligence"),
            ("EXTERNAL", "External", "Asset libraries and AI generation services"),
        ],
        default="CORE",
    )

    bpy.types.Scene.blenderweave_server_choice = EnumProperty(
        name="Server",
        description="Available MCP servers",
        items=_get_server_items,
    )

    bpy.types.Scene.blenderweave_server_running = BoolProperty(
        name="Server Running",
        default=False
    )

    bpy.types.Scene.blenderweave_use_polyhaven = BoolProperty(
        name="Use Poly Haven",
        description="Enable Poly Haven asset integration",
        default=True
    )

    bpy.types.Scene.blenderweave_use_hyper3d = BoolProperty(
        name="Use Hyper3D Rodin",
        description="Enable Hyper3D Rodin generation integration",
        default=False
    )

    bpy.types.Scene.blenderweave_hyper3d_mode = EnumProperty(
        name="Rodin Mode",
        description="Choose the platform used to call Rodin APIs",
        items=[
            ("MAIN_SITE", "hyper3d.ai", "hyper3d.ai"),
            ("FAL_AI", "fal.ai", "fal.ai"),
        ],
        default="MAIN_SITE"
    )

    bpy.types.Scene.blenderweave_hyper3d_api_key = StringProperty(
        name="Hyper3D API Key",
        subtype="PASSWORD",
        description="API Key provided by Hyper3D",
        default=""
    )

    bpy.types.Scene.blenderweave_use_hunyuan3d = BoolProperty(
        name="Use Hunyuan 3D",
        description="Enable Hunyuan asset integration",
        default=False
    )

    bpy.types.Scene.blenderweave_hunyuan3d_mode = EnumProperty(
        name="Hunyuan3D Mode",
        description="Choose a local or official APIs",
        items=[
            ("LOCAL_API", "local api", "local api"),
            ("OFFICIAL_API", "official api", "official api"),
        ],
        default="LOCAL_API"
    )

    bpy.types.Scene.blenderweave_hunyuan3d_secret_id = StringProperty(
        name="Hunyuan 3D SecretId",
        description="SecretId provided by Hunyuan 3D",
        default=""
    )

    bpy.types.Scene.blenderweave_hunyuan3d_secret_key = StringProperty(
        name="Hunyuan 3D SecretKey",
        subtype="PASSWORD",
        description="SecretKey provided by Hunyuan 3D",
        default=""
    )

    bpy.types.Scene.blenderweave_hunyuan3d_api_url = StringProperty(
        name="API URL",
        description="URL of the Hunyuan 3D API service",
        default="http://localhost:8081"
    )

    bpy.types.Scene.blenderweave_hunyuan3d_octree_resolution = IntProperty(
        name="Octree Resolution",
        description="Octree resolution for the 3D generation",
        default=256,
        min=128,
        max=512,
    )

    bpy.types.Scene.blenderweave_hunyuan3d_num_inference_steps = IntProperty(
        name="Number of Inference Steps",
        description="Number of inference steps for the 3D generation",
        default=20,
        min=20,
        max=50,
    )

    bpy.types.Scene.blenderweave_hunyuan3d_guidance_scale = FloatProperty(
        name="Guidance Scale",
        description="Guidance scale for the 3D generation",
        default=5.5,
        min=1.0,
        max=10.0,
    )

    bpy.types.Scene.blenderweave_hunyuan3d_texture = BoolProperty(
        name="Generate Texture",
        description="Whether to generate texture for the 3D model",
        default=False,
    )

    bpy.types.Scene.blenderweave_hunyuan3d_seed = IntProperty(
        name="Seed",
        description="Random seed for reproducible generation",
        default=42,
        min=0,
        max=2**31-1,
    )

    bpy.types.Scene.blenderweave_hunyuan3d_texture_steps = IntProperty(
        name="Texture Steps",
        description="Number of texture generation steps",
        default=15,
        min=1,
        max=50,
    )

    bpy.types.Scene.blenderweave_hunyuan3d_texture_guidance = FloatProperty(
        name="Texture Guidance",
        description="Guidance scale for texture generation",
        default=3.0,
        min=0.1,
        max=20.0,
    )

    bpy.types.Scene.blenderweave_use_trellis2 = BoolProperty(
        name="Use Trellis2",
        description="Enable Trellis2 3D model generation",
        default=False,
    )

    bpy.types.Scene.blenderweave_trellis2_api_url = StringProperty(
        name="Trellis2 API URL",
        description="URL of the Trellis2 API service",
        default="http://localhost:8082",
    )

    bpy.types.Scene.blenderweave_trellis2_pipeline_type = EnumProperty(
        name="Trellis2 Pipeline Type",
        description="Pipeline type (upstream default: 1024 Cascade)",
        items=[
            ("512", "512", "Single-stage 512 pipeline"),
            ("1024_cascade", "1024 Cascade", "Cascaded 1024 pipeline (upstream default)"),
        ],
        default="1024_cascade",
    )

    bpy.types.Scene.blenderweave_trellis2_seed = IntProperty(
        name="Trellis2 Seed",
        description="Random seed for reproducible generation",
        default=42,
        min=0,
        max=2**31-1,
    )

    bpy.types.Scene.blenderweave_trellis2_steps = IntProperty(
        name="Trellis2 Steps",
        description="Number of generation steps",
        default=12,
        min=1,
        max=50,
    )

    bpy.types.Scene.blenderweave_trellis2_guidance_strength = FloatProperty(
        name="Trellis2 Guidance Strength",
        description="Guidance for structure/shape samplers (upstream default: 7.5)",
        default=7.5,
        min=0.1,
        max=20.0,
    )

    bpy.types.Scene.blenderweave_trellis2_texture_guidance = FloatProperty(
        name="Trellis2 Texture Guidance",
        description="Guidance for texture sampler (upstream default: 1.0 = OFF)",
        default=1.0,
        min=0.1,
        max=20.0,
    )

    bpy.types.Scene.blenderweave_trellis2_texture_size = IntProperty(
        name="Trellis2 Texture Size",
        description="Texture resolution in pixels",
        default=2048,
        min=512,
        max=4096,
    )

    # Perception mode
    bpy.types.Scene.blenderweave_perception_mode = EnumProperty(
        name="Perception Mode",
        description="Controls how much perception data is returned after each command",
        items=[
            ("SMART", "Smart", "Full perception minus physics/animation, radius-filtered. Includes OBJ, DELTA, VERIFY, SPATIAL, REL, LIT, SHAD, MAT, PALETTE, MVIEW"),
            ("FULL", "Full", "Everything: all tiers, all objects, all pairs. For deep scene audits and debugging"),
            ("COMPACT", "Compact", "Minimal: OBJ lines only (top 15), DELTA, VERIFY. Fastest response"),
        ],
        default="SMART",
    )

    # Perception feature toggles (used in Full mode)
    bpy.types.Scene.blenderweave_fb_thumbnail = BoolProperty(
        name="Thumbnail",
        description="96px JPEG viewport capture",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_spatial = BoolProperty(
        name="Spatial Relationships",
        description="Object distances, directions, occlusion",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_lighting = BoolProperty(
        name="Light Analysis",
        description="Illumination angles, intensity, shadows",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_materials = BoolProperty(
        name="Material Predictions",
        description="Appearance predictions and warnings",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_constraints = BoolProperty(
        name="Spatial Facts",
        description="Objective spatial facts: penetration, floating, scale, materials, VERIFY",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_shadows = BoolProperty(
        name="Shadow Analysis",
        description="Per-light shadow footprint, coverage, casters, contact",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_ray_grid = BoolProperty(
        name="Ray Grid",
        description="12x12 camera raycasts for depth/material map",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_multi_view = BoolProperty(
        name="Multi-View",
        description="Top/front/light-POV ray grids for complete spatial coverage",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_hierarchy = BoolProperty(
        name="Hierarchy & Groups",
        description="Parent chains and collection membership",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_physics = BoolProperty(
        name="Physics State",
        description="Rigid body type, mass, velocity",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_animation = BoolProperty(
        name="Animation State",
        description="Active actions, current frame, play state",
        default=True
    )
    bpy.types.Scene.blenderweave_fb_micro_render = BoolProperty(
        name="Micro Render",
        description="64x64 EEVEE render for ground-truth brightness and palette",
        default=True
    )

    # Perception radius
    bpy.types.Scene.blenderweave_perception_radius = FloatProperty(
        name="Radius", description="Perception radius in meters (0=unlimited)",
        default=15.0, min=0.0, max=500.0)

    # Perception budget caps
    bpy.types.Scene.blenderweave_cap_obj = IntProperty(
        name="OBJ Cap", description="Max OBJ lines in perception output",
        default=60, min=5, max=200)
    bpy.types.Scene.blenderweave_cap_rel = IntProperty(
        name="REL Cap", description="Max REL lines",
        default=30, min=2, max=50)
    bpy.types.Scene.blenderweave_cap_lit = IntProperty(
        name="LIT Cap", description="Max LIT lines",
        default=20, min=2, max=50)
    bpy.types.Scene.blenderweave_cap_shad = IntProperty(
        name="SHAD Cap", description="Max SHAD lines",
        default=15, min=2, max=50)
    bpy.types.Scene.blenderweave_cap_mat = IntProperty(
        name="MAT Cap", description="Max MAT lines",
        default=20, min=2, max=50)
    bpy.types.Scene.blenderweave_cap_spatial = IntProperty(
        name="SPATIAL Cap", description="Max SPATIAL lines",
        default=20, min=2, max=50)
    bpy.types.Scene.blenderweave_cap_hier = IntProperty(
        name="HIER Cap", description="Max HIER lines",
        default=8, min=2, max=30)
    bpy.types.Scene.blenderweave_cap_contain = IntProperty(
        name="CONTAIN Cap", description="Max CONTAIN lines",
        default=15, min=2, max=30)

    # Perception tuning
    bpy.types.Scene.blenderweave_ray_grid_res = IntProperty(
        name="Ray Grid Resolution", description="NxN ray grid for coverage",
        default=12, min=4, max=32)
    bpy.types.Scene.blenderweave_micro_render_size = IntProperty(
        name="Micro Render Size", description="Pixel size of micro EEVEE render",
        default=64, min=32, max=256)

    bpy.types.Scene.blenderweave_use_sketchfab = BoolProperty(
        name="Use Sketchfab",
        description="Enable Sketchfab asset integration",
        default=False
    )

    bpy.types.Scene.blenderweave_sketchfab_api_key = StringProperty(
        name="Sketchfab API Key",
        subtype="PASSWORD",
        description="API Key provided by Sketchfab",
        default=""
    )

    # AmbientCG (free, no key)
    bpy.types.Scene.blenderweave_use_ambientcg = BoolProperty(
        name="Use AmbientCG",
        description="Enable AmbientCG PBR textures and HDRIs (CC0, no API key)",
        default=True
    )

    # Poly Pizza (free key)
    bpy.types.Scene.blenderweave_use_polypizza = BoolProperty(
        name="Use Poly Pizza",
        description="Enable Poly Pizza low-poly 3D models",
        default=False
    )
    bpy.types.Scene.blenderweave_polypizza_api_key = StringProperty(
        name="Poly Pizza API Key",
        subtype="PASSWORD",
        description="Free API key from poly.pizza/settings/api",
        default=""
    )

    # Smithsonian 3D (free key from api.data.gov)
    bpy.types.Scene.blenderweave_use_smithsonian = BoolProperty(
        name="Use Smithsonian 3D",
        description="Enable Smithsonian 3D museum scans (CC0)",
        default=False
    )
    bpy.types.Scene.blenderweave_smithsonian_api_key = StringProperty(
        name="Smithsonian API Key",
        subtype="PASSWORD",
        description="Free API key from api.data.gov/signup",
        default=""
    )


def unregister_properties():
    props = [
        "blenderweave_panel_tab",
        "blenderweave_server_choice",
        "blenderweave_server_running",
        "blenderweave_perception_mode",
        "blenderweave_fb_thumbnail",
        "blenderweave_fb_spatial",
        "blenderweave_fb_lighting",
        "blenderweave_fb_materials",
        "blenderweave_fb_constraints",
        "blenderweave_fb_shadows",
        "blenderweave_fb_ray_grid",
        "blenderweave_fb_multi_view",
        "blenderweave_fb_hierarchy",
        "blenderweave_fb_physics",
        "blenderweave_fb_animation",
        "blenderweave_fb_micro_render",
        "blenderweave_cap_obj",
        "blenderweave_cap_rel",
        "blenderweave_cap_lit",
        "blenderweave_cap_shad",
        "blenderweave_cap_mat",
        "blenderweave_cap_spatial",
        "blenderweave_cap_hier",
        "blenderweave_cap_contain",
        "blenderweave_ray_grid_res",
        "blenderweave_micro_render_size",
        "blenderweave_use_polyhaven",
        "blenderweave_use_hyper3d",
        "blenderweave_hyper3d_mode",
        "blenderweave_hyper3d_api_key",
        "blenderweave_use_sketchfab",
        "blenderweave_sketchfab_api_key",
        "blenderweave_use_ambientcg",
        "blenderweave_use_polypizza",
        "blenderweave_polypizza_api_key",
        "blenderweave_use_smithsonian",
        "blenderweave_smithsonian_api_key",
        "blenderweave_use_hunyuan3d",
        "blenderweave_hunyuan3d_mode",
        "blenderweave_hunyuan3d_secret_id",
        "blenderweave_hunyuan3d_secret_key",
        "blenderweave_hunyuan3d_api_url",
        "blenderweave_hunyuan3d_octree_resolution",
        "blenderweave_hunyuan3d_num_inference_steps",
        "blenderweave_hunyuan3d_guidance_scale",
        "blenderweave_hunyuan3d_texture",
        "blenderweave_hunyuan3d_seed",
        "blenderweave_hunyuan3d_texture_steps",
        "blenderweave_hunyuan3d_texture_guidance",
        "blenderweave_use_trellis2",
        "blenderweave_trellis2_api_url",
        "blenderweave_trellis2_seed",
        "blenderweave_trellis2_steps",
        "blenderweave_trellis2_pipeline_type",
        "blenderweave_trellis2_guidance_strength",
        "blenderweave_trellis2_texture_guidance",
        "blenderweave_trellis2_texture_size",
    ]
    for prop in props:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
