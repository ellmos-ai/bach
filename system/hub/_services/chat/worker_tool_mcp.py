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
            outcome = await asyncio.to_thread(client.call_detailed, name, arguments)
            response = {"content": [TextContent(type="text", text=outcome.result)],
                        "isError": outcome.is_error}
            if outcome.error is not None:
                response["structuredContent"] = outcome.error
            return CallToolResult(**response)
        except Exception:
            return CallToolResult(content=[TextContent(type="text", text="Werkzeugaufruf nicht bestätigt; keine Wiederholung")],
                                  isError=True)

    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())


if __name__ == "__main__":
    try:
        # Not asyncio.run(): its shutdown joins executor threads, and a thread sitting in
        # a relay HTTP call (timeout 130 s) kept this shim alive long after the parent
        # closed stdin (bach-suite hang on the Mac, T-20261107-512211369).
        asyncio.new_event_loop().run_until_complete(serve())
    except Exception:
        print("Privater Worker-Werkzeugtransport konnte nicht gestartet werden", file=sys.stderr)
        raise SystemExit(2) from None
    # stdio_server already closed stdout; interpreter exit would still join the executor
    # thread, so leave without it (stdin closed means there is nothing left to clean up).
    try:
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(0)
