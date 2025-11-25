"""Entry point for running Hass-MCP via uv/uvx tool"""

import argparse
import os

def main():
    """Run the MCP server with stdio or streamable HTTP transport"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    
    if args.http:
        os.environ["MCP_HOST"] = os.environ.get("MCP_HOST", args.host)
        os.environ["MCP_PORT"] = str(args.port)
        os.environ["MCP_TRANSPORT"] = "streamable-http"
    
    from app.server import mcp
    mcp.run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))
