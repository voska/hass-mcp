"""Home Assistant MCP Server.

This package provides an MCP (Model Context Protocol) server that allows an LLM like Claude
to interact with a Home Assistant instance through a set of tools.
"""

__version__ = "0.2.0"

from app.server import serve, main

__all__ = ["serve", "main"]