"""End to end: the MCP server over stdio, a headless Blender connected, the v1.1 tools called as a client would."""
import asyncio, subprocess, time, os, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

async def main():
    params = StdioServerParameters(command="uv", args=["run", "--directory", ROOT, "blender-weave"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            blender = subprocess.Popen(["blender", "-b", "--factory-startup", "--python", os.path.join(ROOT, "tests", "headless_blender.py"), "--", "240"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ok = True
            try:
                for _ in range(60):
                    res = await s.call_tool("execute_blender_code", {"code": "result = 1 + 1"})
                    txt = res.content[0].text if res.content else ""
                    if "result: 2" in txt: break
                    await asyncio.sleep(1)
                checks = [
                    ("execute_blender_code", {"code": "import bpy\nprint('hello')\nresult = [o.name for o in bpy.data.objects]"}, "hello"),
                    ("execute_blender_code", {"code": "x = 41", "keep_namespace": True}, "successfully"),
                    ("execute_blender_code", {"code": "result = x + 1", "keep_namespace": True}, "result: 42"),
                    ("execute_blender_code", {"code": "1 / 0"}, "ZeroDivisionError"),
                    ("execute_blender_code", {"code": "result = 'still connected'"}, "still connected"),
                    ("search_blender_api", {"query": "principled bsdf subsurface"}, "ShaderNodeBsdfPrincipled"),
                    ("get_blender_api", {"path": "bpy.types.ShaderNodeBsdfPrincipled"}, "Subsurface Radius"),
                    ("get_blender_api", {"path": "bpy.ops.render.render"}, "write_still"),
                    ("search_blender_manual", {"query": "random walk skin subsurface"}, "sss"),
                    ("get_blender_manual", {"path": "render/shader_nodes/shader/principled"}, "Subsurface"),
                    ("get_blendfile_summary", {}, "objects"),
                    ("get_blendfile_paths", {}, "paths"),
                    ("get_linked_libraries", {}, "libraries"),
                    ("run_blender_background", {"code": "import bpy\nprint('BG', bpy.app.version_string)", "timeout": 120}, "BG 5.2"),
                    ("get_window_layout", {}, ""),
                ]
                for name, args, want in checks:
                    t = time.time(); res = await s.call_tool(name, args)
                    txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
                    good = ("Error executing tool" not in txt or want == "ZeroDivisionError") and want in txt
                    if name == "get_window_layout": good = "workspace" in txt or "No Blender window" in txt
                    ok &= good
                    print(("PASS" if good else "FAIL"), name, round(time.time() - t, 2), "s", "|", txt[:160].replace("\n", " | "))
            finally:
                open("/tmp/blenderweave_headless_stop", "w").close(); blender.wait(30); os.remove("/tmp/blenderweave_headless_stop")
            print("ALL PASS" if ok else "SOME FAILED")

asyncio.run(main())
