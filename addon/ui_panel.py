import bpy

RODIN_FREE_TRIAL_KEY = "k9TcfFoEhNd9cCPP2guHAHHHkctZHIRhZDywZ1euGUXwihbYLpOjQhofby80NJez"


class BLENDERWEAVE_PT_Panel(bpy.types.Panel):
    bl_label = "BlenderWeave"
    bl_idname = "BLENDERWEAVE_PT_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Connection controls
        server = getattr(bpy.types, "blenderweave_server", None)
        if server and server.state == server.CONNECTED:
            layout.operator("blenderweave.stop_server", text="Disconnect", icon='PAUSE')
            label = server.server_label or "MCP server"
            layout.label(text=f"Connected to {label}", icon='CHECKMARK')
        elif server and server.state == server.CONNECTING:
            layout.operator("blenderweave.stop_server", text="Cancel", icon='X')
            layout.label(text="Searching for MCP server...", icon='TIME')
        else:
            # Show available servers
            from .server_bridge import discover_servers
            servers = discover_servers()
            if not servers:
                layout.label(text="No MCP server running", icon='ERROR')
                layout.operator("blenderweave.start_server", text="Retry", icon='FILE_REFRESH')
            elif len(servers) == 1:
                layout.operator("blenderweave.start_server", text="Connect", icon='PLAY')
            else:
                # Multiple servers — show dropdown
                layout.prop(scene, "blenderweave_server_choice", text="Server")
                layout.operator("blenderweave.start_server", text="Connect", icon='PLAY')

        layout.separator()

        # Tab switcher
        row = layout.row(align=True)
        row.prop_enum(scene, "blenderweave_panel_tab", "CORE")
        row.prop_enum(scene, "blenderweave_panel_tab", "EXTERNAL")

        # Perception mode always visible in Core tab
        if scene.blenderweave_panel_tab == 'CORE':
            layout.separator()
            layout.prop(scene, "blenderweave_perception_mode", text="Perception")
            if scene.blenderweave_perception_mode == 'SMART':
                layout.label(text="Full minus physics/animation, radius-filtered", icon='INFO')
            elif scene.blenderweave_perception_mode == 'COMPACT':
                layout.label(text="OBJ + DELTA + VERIFY only", icon='INFO')


# ━━━ CORE TAB: Perception sub-panels ━━━


class BLENDERWEAVE_PT_PerceptionToggles(bpy.types.Panel):
    bl_label = "Feature Toggles"
    bl_idname = "BLENDERWEAVE_PT_PerceptionToggles"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_Panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (context.scene.blenderweave_panel_tab == 'CORE' and
                context.scene.blenderweave_perception_mode == 'FULL')

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        row = layout.row()
        row.label(text="Spatial", icon='ORIENTATION_GLOBAL')
        col = layout.column(align=True)
        col.prop(scene, "blenderweave_fb_spatial")
        col.prop(scene, "blenderweave_fb_constraints")
        col.prop(scene, "blenderweave_fb_ray_grid")
        col.prop(scene, "blenderweave_fb_multi_view")

        layout.separator()
        row = layout.row()
        row.label(text="Visual", icon='CAMERA_DATA')
        col = layout.column(align=True)
        col.prop(scene, "blenderweave_fb_micro_render")
        col.prop(scene, "blenderweave_fb_thumbnail")
        col.prop(scene, "blenderweave_fb_lighting")
        col.prop(scene, "blenderweave_fb_shadows")
        col.prop(scene, "blenderweave_fb_materials")

        layout.separator()
        row = layout.row()
        row.label(text="Structure", icon='OUTLINER')
        col = layout.column(align=True)
        col.prop(scene, "blenderweave_fb_hierarchy")
        col.prop(scene, "blenderweave_fb_physics")
        col.prop(scene, "blenderweave_fb_animation")


class BLENDERWEAVE_PT_PerceptionBudgets(bpy.types.Panel):
    bl_label = "Budget Caps"
    bl_idname = "BLENDERWEAVE_PT_PerceptionBudgets"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_Panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.blenderweave_panel_tab == 'CORE'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "blenderweave_perception_radius", text="Radius (m)")
        layout.separator()

        flow = layout.grid_flow(columns=2, align=True)
        flow.prop(scene, "blenderweave_cap_obj", text="OBJ")
        flow.prop(scene, "blenderweave_cap_rel", text="REL")
        flow.prop(scene, "blenderweave_cap_lit", text="LIT")
        flow.prop(scene, "blenderweave_cap_shad", text="SHAD")
        flow.prop(scene, "blenderweave_cap_mat", text="MAT")
        flow.prop(scene, "blenderweave_cap_spatial", text="SPATIAL")
        flow.prop(scene, "blenderweave_cap_hier", text="HIER")

        layout.separator()
        col = layout.column(align=True)
        col.prop(scene, "blenderweave_ray_grid_res", text="Ray Grid NxN")
        col.prop(scene, "blenderweave_micro_render_size", text="Micro Render px")


# ━━━ EXTERNAL TAB: Asset Libraries ━━━


class BLENDERWEAVE_PT_AssetLibraries(bpy.types.Panel):
    bl_label = "Asset Libraries"
    bl_idname = "BLENDERWEAVE_PT_AssetLibraries"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_Panel"

    @classmethod
    def poll(cls, context):
        return context.scene.blenderweave_panel_tab == 'EXTERNAL'

    def draw(self, context):
        layout = self.layout
        layout.label(text="Search and download 3D assets", icon='ASSET_MANAGER')


class BLENDERWEAVE_PT_PolyHaven(bpy.types.Panel):
    bl_label = "Poly Haven"
    bl_idname = "BLENDERWEAVE_PT_PolyHaven"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_AssetLibraries"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "blenderweave_use_polyhaven", text="")

    def draw(self, context):
        layout = self.layout
        layout.active = context.scene.blenderweave_use_polyhaven
        layout.label(text="HDRIs, PBR textures, 3D models", icon='WORLD')
        layout.label(text="CC0 — No API key needed", icon='CHECKMARK')


class BLENDERWEAVE_PT_AmbientCG(bpy.types.Panel):
    bl_label = "AmbientCG"
    bl_idname = "BLENDERWEAVE_PT_AmbientCG"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_AssetLibraries"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "blenderweave_use_ambientcg", text="")

    def draw(self, context):
        layout = self.layout
        layout.active = context.scene.blenderweave_use_ambientcg
        layout.label(text="2400+ PBR materials & HDRIs", icon='MATERIAL')
        layout.label(text="CC0 — No API key needed", icon='CHECKMARK')


class BLENDERWEAVE_PT_Sketchfab(bpy.types.Panel):
    bl_label = "Sketchfab"
    bl_idname = "BLENDERWEAVE_PT_Sketchfab"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_AssetLibraries"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "blenderweave_use_sketchfab", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.active = scene.blenderweave_use_sketchfab
        layout.label(text="Millions of 3D models", icon='MESH_MONKEY')
        if scene.blenderweave_use_sketchfab:
            layout.prop(scene, "blenderweave_sketchfab_api_key", text="API Key")


class BLENDERWEAVE_PT_PolyPizza(bpy.types.Panel):
    bl_label = "Poly Pizza"
    bl_idname = "BLENDERWEAVE_PT_PolyPizza"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_AssetLibraries"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "blenderweave_use_polypizza", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.active = scene.blenderweave_use_polypizza
        layout.label(text="7000+ low-poly 3D models", icon='MESH_ICOSPHERE')
        if scene.blenderweave_use_polypizza:
            layout.prop(scene, "blenderweave_polypizza_api_key", text="API Key")
            layout.label(text="Free key: poly.pizza/settings/api", icon='INFO')


class BLENDERWEAVE_PT_Smithsonian(bpy.types.Panel):
    bl_label = "Smithsonian 3D"
    bl_idname = "BLENDERWEAVE_PT_Smithsonian"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_AssetLibraries"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "blenderweave_use_smithsonian", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.active = scene.blenderweave_use_smithsonian
        layout.label(text="4000+ museum 3D scans", icon='SCENE_DATA')
        if scene.blenderweave_use_smithsonian:
            layout.prop(scene, "blenderweave_smithsonian_api_key", text="API Key")
            layout.label(text="Free key: api.data.gov/signup", icon='INFO')


# ━━━ EXTERNAL TAB: AI Generation ━━━


class BLENDERWEAVE_PT_AIGeneration(bpy.types.Panel):
    bl_label = "AI Generation"
    bl_idname = "BLENDERWEAVE_PT_AIGeneration"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_Panel"

    @classmethod
    def poll(cls, context):
        return context.scene.blenderweave_panel_tab == 'EXTERNAL'

    def draw(self, context):
        layout = self.layout
        layout.label(text="Text/image to 3D generation", icon='OUTLINER_OB_LIGHT')


class BLENDERWEAVE_PT_Hyper3D(bpy.types.Panel):
    bl_label = "Hyper3D Rodin"
    bl_idname = "BLENDERWEAVE_PT_Hyper3D"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_AIGeneration"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "blenderweave_use_hyper3d", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.active = scene.blenderweave_use_hyper3d
        if scene.blenderweave_use_hyper3d:
            layout.prop(scene, "blenderweave_hyper3d_mode", text="Mode")
            layout.prop(scene, "blenderweave_hyper3d_api_key", text="API Key")
            layout.operator("blenderweave.set_hyper3d_free_trial_api_key",
                            text="Use Free Trial Key", icon='KEY_HLT')


class BLENDERWEAVE_PT_Hunyuan3D(bpy.types.Panel):
    bl_label = "Hunyuan 3D"
    bl_idname = "BLENDERWEAVE_PT_Hunyuan3D"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_AIGeneration"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "blenderweave_use_hunyuan3d", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.active = scene.blenderweave_use_hunyuan3d
        if scene.blenderweave_use_hunyuan3d:
            layout.prop(scene, "blenderweave_hunyuan3d_mode", text="Mode")
            if scene.blenderweave_hunyuan3d_mode == 'OFFICIAL_API':
                layout.prop(scene, "blenderweave_hunyuan3d_secret_id", text="SecretId")
                layout.prop(scene, "blenderweave_hunyuan3d_secret_key", text="SecretKey")
            if scene.blenderweave_hunyuan3d_mode == 'LOCAL_API':
                layout.prop(scene, "blenderweave_hunyuan3d_api_url", text="API URL")
                col = layout.column(align=True)
                col.prop(scene, "blenderweave_hunyuan3d_seed", text="Seed")
                col.prop(scene, "blenderweave_hunyuan3d_octree_resolution", text="Octree Res")
                col.prop(scene, "blenderweave_hunyuan3d_num_inference_steps", text="Steps")
                col.prop(scene, "blenderweave_hunyuan3d_guidance_scale", text="Guidance")
                layout.separator()
                layout.prop(scene, "blenderweave_hunyuan3d_texture", text="Generate Texture")
                if scene.blenderweave_hunyuan3d_texture:
                    col = layout.column(align=True)
                    col.prop(scene, "blenderweave_hunyuan3d_texture_steps", text="Texture Steps")
                    col.prop(scene, "blenderweave_hunyuan3d_texture_guidance", text="Texture Guidance")


class BLENDERWEAVE_PT_Trellis2(bpy.types.Panel):
    bl_label = "Trellis 2"
    bl_idname = "BLENDERWEAVE_PT_Trellis2"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderWeave'
    bl_parent_id = "BLENDERWEAVE_PT_AIGeneration"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "blenderweave_use_trellis2", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.active = scene.blenderweave_use_trellis2
        if scene.blenderweave_use_trellis2:
            layout.prop(scene, "blenderweave_trellis2_api_url", text="API URL")
            layout.prop(scene, "blenderweave_trellis2_pipeline_type", text="Pipeline")
            col = layout.column(align=True)
            col.prop(scene, "blenderweave_trellis2_seed", text="Seed")
            col.prop(scene, "blenderweave_trellis2_steps", text="Steps")
            col.prop(scene, "blenderweave_trellis2_guidance_strength", text="Guidance")
            col.prop(scene, "blenderweave_trellis2_texture_guidance", text="Texture Guidance")
            col.prop(scene, "blenderweave_trellis2_texture_size", text="Texture Size")


# ━━━ Operators ━━━


class BLENDERWEAVE_OT_SetFreeTrialHyper3DAPIKey(bpy.types.Operator):
    bl_idname = "blenderweave.set_hyper3d_free_trial_api_key"
    bl_label = "Set Free Trial API Key"

    def execute(self, context):
        context.scene.blenderweave_hyper3d_api_key = RODIN_FREE_TRIAL_KEY
        context.scene.blenderweave_hyper3d_mode = 'MAIN_SITE'
        self.report({'INFO'}, "API Key set successfully!")
        return {'FINISHED'}


class BLENDERWEAVE_OT_StartServer(bpy.types.Operator):
    bl_idname = "blenderweave.start_server"
    bl_label = "Connect"
    bl_description = "Connect to a BlenderWeave MCP server"

    def execute(self, context):
        from .server_bridge import BlenderWeaveClient, discover_servers
        scene = context.scene

        # Determine which server to connect to
        server_id = None
        servers = discover_servers()
        if len(servers) > 1:
            choice = scene.blenderweave_server_choice
            if choice and choice != "NONE":
                server_id = choice

        # Stop existing client if any
        if hasattr(bpy.types, "blenderweave_server") and bpy.types.blenderweave_server:
            bpy.types.blenderweave_server.stop()

        bpy.types.blenderweave_server = BlenderWeaveClient(server_id=server_id)
        bpy.types.blenderweave_server.start()
        scene.blenderweave_server_running = True
        return {'FINISHED'}


class BLENDERWEAVE_OT_StopServer(bpy.types.Operator):
    bl_idname = "blenderweave.stop_server"
    bl_label = "Disconnect"
    bl_description = "Disconnect from the BlenderWeave MCP server"

    def execute(self, context):
        scene = context.scene
        if hasattr(bpy.types, "blenderweave_server") and bpy.types.blenderweave_server:
            bpy.types.blenderweave_server.stop()
            bpy.types.blenderweave_server = None
        scene.blenderweave_server_running = False
        return {'FINISHED'}


# Parents must register before children
UI_CLASSES = [
    BLENDERWEAVE_PT_Panel,
    # Core tab
    BLENDERWEAVE_PT_PerceptionToggles,
    BLENDERWEAVE_PT_PerceptionBudgets,
    # External tab — Asset Libraries
    BLENDERWEAVE_PT_AssetLibraries,
    BLENDERWEAVE_PT_PolyHaven,
    BLENDERWEAVE_PT_AmbientCG,
    BLENDERWEAVE_PT_Sketchfab,
    BLENDERWEAVE_PT_PolyPizza,
    BLENDERWEAVE_PT_Smithsonian,
    # External tab — AI Generation
    BLENDERWEAVE_PT_AIGeneration,
    BLENDERWEAVE_PT_Hyper3D,
    BLENDERWEAVE_PT_Hunyuan3D,
    BLENDERWEAVE_PT_Trellis2,
    # Operators
    BLENDERWEAVE_OT_SetFreeTrialHyper3DAPIKey,
    BLENDERWEAVE_OT_StartServer,
    BLENDERWEAVE_OT_StopServer,
]
