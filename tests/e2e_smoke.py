"""Every structured tool once against a real Blender (headless, tests/headless_blender.py), as a client calls it:
a scene is built up step by step, and each call must come back without an error. The asset services (Poly Haven,
Sketchfab, Hyper3D, Hunyuan, Trellis, ambientCG, Poly Pizza, Smithsonian) need the network or accounts and are left
out, and so are undo and redo, which background Blender disables. Run: uv run python tests/e2e_smoke.py"""
import asyncio, subprocess, time, os, sys, tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="bw_smoke_")

CALLS = [
    ("create_object", {"type": "CUBE", "name": "Box", "location": [0, 0, 1]}),
    ("create_object", {"type": "UV_SPHERE", "name": "Ball", "location": [2, 0, 1], "radius": 0.5}),
    ("create_object", {"type": "PLANE", "name": "Floor", "size": 10}),
    ("create_object", {"type": "AREA_LIGHT", "name": "Key", "location": [3, -3, 4], "energy": 500}),
    ("transform_object", {"object_name": "Box", "rotation": [0, 0, 30]}),
    ("duplicate_object", {"object_name": "Box", "new_name": "Box2"}),
    ("batch_transform", {"transforms": [{"object_name": "Box2", "location": [-2, 0, 1]}]}),
    ("place_relative", {"object_name": "Ball", "relative_to": "Box", "relation": "right_of", "distance": 1.0}),
    ("manage_materials", {"action": "create", "material_name": "Red", "color": [0.8, 0.1, 0.1, 1]}),
    ("manage_materials", {"action": "assign", "object_name": "Box", "material_name": "Red"}),
    ("manage_materials", {"action": "edit_node", "material_name": "Red", "node_name": "Principled BSDF", "input_name": "Roughness", "value": 0.3}),
    ("manage_materials", {"action": "set_properties", "material_name": "Red", "roughness": 0.4}),
    ("manage_lights", {"action": "list"}),
    ("manage_lights", {"action": "set_properties", "light_name": "Key", "energy": 800, "size": 2}),
    ("manage_world", {"action": "set_color", "color": [0.05, 0.05, 0.06]}),
    ("manage_world", {"action": "set_strength", "strength": 0.5}),
    ("create_object", {"type": "CAMERA", "name": "Cam", "location": [6, -6, 4]}),
    ("set_camera", {"camera_name": "Cam", "focal_length": 50, "look_at": "Box"}),
    ("configure_render_settings", {"settings": {"engine": "CYCLES", "samples": 4, "resolution_x": 160, "resolution_y": 120}}),
    ("modify_object", {"object_name": "Ball", "action": "add_modifier", "modifier_type": "SUBSURF", "properties": {"levels": 1}}),
    ("modify_object", {"object_name": "Ball", "action": "list_modifiers"}),
    ("mesh_operation", {"action": "shade_smooth", "target_object": "Ball"}),
    ("uv_operation", {"object_name": "Box", "action": "smart_project"}),
    ("uv_operation", {"object_name": "Box", "action": "list"}),
    ("manage_shape_keys", {"object_name": "Ball", "action": "add", "key_name": "Basis"}),
    ("manage_shape_keys", {"object_name": "Ball", "action": "add", "key_name": "Squash"}),
    ("manage_shape_keys", {"object_name": "Ball", "action": "set_value", "key_name": "Squash", "value": 0.5}),
    ("manage_armature", {"action": "create", "armature_name": "Rig", "bone_data": [{"name": "root", "head": [0, 0, 0], "tail": [0, 0, 1]}, {"name": "tip", "head": [0, 0, 1], "tail": [0, 0, 2], "parent": "root", "use_connect": True}]}),
    ("manage_weights", {"object_name": "Box", "action": "list"}),
    ("set_keyframe", {"object_name": "Box", "frame": 1, "property": "location"}),
    ("set_keyframe", {"object_name": "Box", "frame": 20, "property": "location", "value": [0, 0, 2]}),
    ("manage_actions", {"action": "list"}),
    ("manage_nla", {"object_name": "Box", "action": "list_tracks"}),
    ("set_frame", {"frame": 10, "start": 1, "end": 20}),
    ("manage_collections", {"action": "create", "collection_name": "Props"}),
    ("manage_collections", {"action": "move_object", "collection_name": "Props", "object_name": "Box2"}),
    ("manage_hierarchy", {"action": "parent", "object_name": "Box2", "parent_name": "Box"}),
    ("manage_hierarchy", {"action": "list_children", "object_name": "Box"}),
    ("manage_custom_properties", {"action": "set", "object_name": "Box", "prop_name": "kind", "value": "crate"}),
    ("manage_drivers", {"action": "add_simple", "object_name": "Box2", "data_path": "location", "target_object": "Box", "target_data_path": "location", "index": 2}),
    ("manage_constraints", {"object_name": "Ball", "action": "add", "constraint_type": "TRACK_TO", "properties": {"target": "Box"}}),
    ("manage_selection", {"action": "select", "object_name": "Ball"}),
    ("manage_curves", {"action": "create", "name": "Path", "curve_type": "BEZIER", "points": [[0, 0, 0], [1, 1, 0], [2, 0, 0]]}),
    ("manage_particles", {"action": "add", "object_name": "Floor", "name": "Grass", "particle_type": "HAIR", "count": 50}),
    ("manage_physics", {"object_name": "Ball", "action": "add", "physics_type": "RIGID_BODY"}),
    ("build_node_graph", {"target": "geometry:Box", "nodes": [{"name": "set", "type": "GeometryNodeSetPosition"}], "links": []}),
    ("get_node_graph", {"target": "shader:Red"}),
    ("list_node_types", {"category": "shader"}),
    ("get_scene_perception", {}),
    ("get_scene_delta", {}),
    ("manage_snapshots", {"action": "save", "name": "before"}),
    ("manage_snapshots", {"action": "compare", "name": "before"}),
    ("generate_lod_chain", {"object_name": "Ball", "ratios": [1.0, 0.5]}),
    ("generate_collision_mesh", {"object_name": "Box", "method": "CONVEX_HULL"}),
    ("create_assembly", {"type": "table", "name": "Table", "location": [0, 3, 0]}),
    ("procedural_generate", {"action": "create_terrain", "size": 4, "resolution": 16}),
    ("volume_operation", {"action": "mesh_to_sdf", "object_name": "Ball", "voxel_size": 0.1}),
    ("camera_walkthrough", {"waypoints": [{"location": [6, -6, 3], "look_at": [0, 0, 1]}, {"location": [-6, -6, 3], "look_at": [0, 0, 1]}]}),
    ("render_region", {"object_name": "Box", "resolution": 64, "samples": 2}),
    ("render_scene", {"output_path": os.path.join(T, "still.png"), "samples": 2, "resolution_x": 96, "resolution_y": 72}),
    ("export_model", {"filepath": os.path.join(T, "scene.glb"), "format": "GLB"}),
    ("import_model", {"filepath": os.path.join(T, "scene.glb")}),
    ("save_file", {"filepath": os.path.join(T, "scene.blend")}),
    ("get_blendfile_summary", {}),
    ("open_file", {"filepath": os.path.join(T, "scene.blend")}),
    ("get_scene_info", {}),
    ("get_object_info", {"object_name": "Box"}),
    ("batch_execute", {"commands": [{"tool": "create_object", "params": {"type": "CUBE", "name": "BatchBox"}}]}),
    ("delete_object", {"object_names": ["BatchBox"]}),
]


async def main():
    params = StdioServerParameters(command="uv", args=["run", "--directory", ROOT, "blender-weave"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            blender = subprocess.Popen(["blender", "-b", "--factory-startup", "--python", os.path.join(ROOT, "tests", "headless_blender.py"), "--", "600"],
                                       stdout=open(os.path.join(T, "blender.log"), "w"), stderr=subprocess.STDOUT)
            failed = []
            try:
                for _ in range(60):
                    res = await s.call_tool("execute_blender_code", {"code": "result = 1"})
                    if res.content and "result: 1" in res.content[0].text: break
                    await asyncio.sleep(1)
                await s.call_tool("execute_blender_code", {"code": "import bpy\nfor o in list(bpy.data.objects):\n    bpy.data.objects.remove(o)"})
                for name, args in CALLS:
                    t = time.time(); res = await s.call_tool(name, args)
                    txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
                    bad = res.isError or "Error executing tool" in txt or '"error"' in txt[:400] or txt.startswith("Error")
                    if bad: failed.append((name, txt[:400]))
                    print(("FAIL" if bad else "ok  "), f"{name:28s}", f"{time.time() - t:5.2f}s", txt[:110].replace("\n", " | ") if bad else "")
            finally:
                open("/tmp/blenderweave_headless_stop", "w").close(); blender.wait(30); os.remove("/tmp/blenderweave_headless_stop")
            print(f"\n{len(CALLS) - len(failed)} of {len(CALLS)} passed")
            for n, t in failed: print("\n---", n, "\n", t)

asyncio.run(main())
