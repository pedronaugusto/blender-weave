"""A tool's failure message and image results reach the client on both mcp generations."""
import asyncio

import pytest

from blender_weave import server


def call(name):
    try:
        return repr(asyncio.run(server.mcp.call_tool(name, {})))
    except Exception as exc:
        return str(exc)


def test_failure_message_reaches_client():
    @server.mcp.tool()
    def _failing_tool() -> str:
        raise RuntimeError("the real reason")

    assert "the real reason" in call("_failing_tool")


def test_failure_message_reaches_client_from_async_tool():
    @server.mcp.tool()
    async def _failing_async_tool() -> str:
        raise ConnectionError("no connection here")

    assert "no connection here" in call("_failing_async_tool")


def test_decorated_function_keeps_its_own_exceptions():
    @server.mcp.tool()
    def _direct_tool() -> str:
        raise KeyError("direct")

    with pytest.raises(KeyError):
        _direct_tool()


def test_image_results_reach_client():
    @server.mcp.tool()
    def _image_tool() -> server.Image:
        return server.Image(data=b"png-bytes", format="png")

    result = call("_image_tool")
    assert "image/png" in result and "ImageContent" in result
