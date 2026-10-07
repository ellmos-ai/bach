"""CLI stdio MCP shim for a private worker relay; no TaskDB access or fallback."""
import asyncio
import os
import sys

if __package__:
    from .worker_tool_client import WorkerToolClient
else:
    from worker_tool_client import WorkerToolClient


async def serve():
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, TextContent, Tool

    client = WorkerToolClient.from_environment(os.environ)
    server = Server("bach_worker")

    @server.list_tools()
    async def list_tools():
        tools = await asyncio.to_thread(client.tools)
        return [Tool(name=tool["function"]["name"], description=tool["function"].get("description", ""),
                     inputSchema=tool["function"]["parameters"]) for tool in tools]

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            result, failed = await asyncio.to_thread(client.call, name, arguments)
            return CallToolResult(content=[TextContent(type="text", text=result)], isError=failed)
        except Exception:
            return CallToolResult(content=[TextContent(type="text", text="Werkzeugaufruf nicht bestätigt; keine Wiederholung")],
                                  isError=True)

    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())


if __name__ == "__main__":
    try:
        asyncio.run(serve())
    except Exception:
        print("Privater Worker-Werkzeugtransport konnte nicht gestartet werden", file=sys.stderr)
        raise SystemExit(2) from None
