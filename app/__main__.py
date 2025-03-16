#!/usr/bin/env python
"""Entry point for running Hass-MCP as a module"""

from app.server import mcp


def main():
    """Run the MCP server with stdio communication"""
    mcp.run()


if __name__ == "__main__":
    main()