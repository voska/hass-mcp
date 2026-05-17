"""Entry point for running Hass-MCP via uv/uvx tool."""

import argparse
import os


def main():
    """Run the MCP server. Defaults to stdio; pass --http for streamable HTTP."""
    parser = argparse.ArgumentParser(prog="hass-mcp", description="Home Assistant MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run as streamable HTTP server instead of stdio (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "127.0.0.1"),
        help="Host to bind when --http is set (default: 127.0.0.1; override with MCP_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", os.environ.get("MCP_PORT", "8000"))),
        help="Port to bind when --http is set (default: 8000; override with PORT or MCP_PORT)",
    )
    args = parser.parse_args()

    if args.http:
        # The server module reads these at import time to configure FastMCP.
        os.environ["MCP_TRANSPORT"] = "streamable-http"
        os.environ["MCP_HOST"] = args.host
        os.environ["MCP_PORT"] = str(args.port)

    from app.server import mcp

    mcp.run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))
