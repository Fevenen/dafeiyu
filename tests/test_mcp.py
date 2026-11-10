"""Real stdio MCP handshake/schema test; only read-only and rejected calls."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_schema_and_confirmation_rejection(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="pet-mcp-") as temp:
            env = dict(
                os.environ,
                PET_DATA_DIR=temp,
                PET_CONFIG=str(Path(temp) / "config.json"),
                PYTHONDONTWRITEBYTECODE="1",
            )
            params = StdioServerParameters(
                command=sys.executable, args=[str(root / "bridge/server.py")], env=env
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.list_tools()
                    schemas = {
                        tool.name: (
                            tool.input_schema
                            if hasattr(tool, "input_schema")
                            else tool.inputSchema
                        )
                        for tool in result.tools
                    }
                    self.assertIn("route_command", schemas)
                    self.assertIn("list_capabilities", schemas)
                    self.assertIn("confirmation", schemas["confirm_send"]["required"])
                    response = await client.call_tool(
                        "confirm_send", {"confirmation": "好了吗"}
                    )
                    text = "".join(x.text for x in response.content if x.type == "text")
                    self.assertIn("没有作为发送确认", text)
                    capabilities = await client.call_tool("list_capabilities", {})
                    self.assertFalse(
                        capabilities.is_error
                        if hasattr(capabilities, "is_error")
                        else capabilities.isError
                    )


if __name__ == "__main__":
    unittest.main()
