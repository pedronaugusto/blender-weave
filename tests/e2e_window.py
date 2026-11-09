"""The window tools against a real Blender with a window (it opens, connects, is looked at, quits):
uv run python tests/e2e_window.py"""
import asyncio, subprocess, os, time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "/tmp/bw_window"

async def main():
    os.makedirs(OUT, exist_ok=True)
    params = StdioServerParameters(command="uv", args=["run", "--directory", ROOT, "blender-weave"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            blender = subprocess.Popen(["blender"], stdout=open(f"{OUT}/blender.log", "w"), stderr=subprocess.STDOUT)
            for _ in range(90):
                res = await s.call_tool("execute_blender_code", {"code": "result = 'up'"})
                if res.content and "result: up" in res.content[0].text: break
                await asyncio.sleep(1)
            ok = True
            for name, args in [("get_window_screenshot", {"max_size": 1400}), ("get_area_screenshot", {"area_type": "VIEW_3D"}),
                               ("get_area_screenshot", {"area_type": "PROPERTIES"}), ("get_window_layout", {}),
                               ("jump_to_workspace", {"name": "Shading"}), ("get_window_screenshot", {"max_size": 1000, "max_bytes": 250_000}),
                               ("jump_to_object", {"object_name": "Cube"}), ("get_viewport_screenshot", {})]:
                res = await s.call_tool(name, args)
                imgs = [c for c in res.content if getattr(c, "type", "") == "image"]
                txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
                good = not res.isError and (imgs or ("Error" not in txt))
                ok &= bool(good)
                for i, im in enumerate(imgs):
                    import base64; data = base64.b64decode(im.data); path = f"{OUT}/{name}_{args.get('area_type', '')}{args.get('max_bytes', '')}.png"
                    open(path, "wb").write(data); txt = f"image {len(data)} bytes -> {path}"
                print("PASS" if good else "FAIL", name, args, "|", txt[:150].replace("\n", " | "))
            await s.call_tool("execute_blender_code", {"code": "import bpy\nbpy.app.timers.register(lambda: bpy.ops.wm.quit_blender(), first_interval=0.5)"})
            blender.wait(30)
            print("ALL PASS" if ok else "SOME FAILED")

asyncio.run(main())
