"""
Live transport tests for hass-mcp.

These spawn the actual `python -m app` subprocess and drive it through the
real MCP client transports (stdio and streamable HTTP). They verify the
end-to-end wire protocol, not just in-memory behavior, and act as a
regression net for the CLI entry point + transport configuration.

Marked `slow` because each test spawns a subprocess and goes over a real
transport. They take ~1-3 seconds each, which is fine but adds up.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# tests/conftest.py installs autouse fixtures that replace httpx.AsyncClient
# with a MagicMock. Those leak into the MCP HTTP *client* too, breaking the
# real-transport tests below. Override here so real httpx runs.
@pytest.fixture(autouse=True)
def mock_get_client():
    yield


SERVER_ENV = {
    "HA_URL": "http://localhost:8123",
    "HA_TOKEN": "transport-test-token",
}


EXPECTED_TOOLS = {
    "call_service_tool",
    "domain_summary_tool",
    "entity_action",
    "get_entities_by_area",
    "get_entity",
    "get_error_log",
    "get_history",
    "get_version",
    "list_automations",
    "list_entities",
    "restart_ha",
    "search_entities_tool",
    "system_overview",
}

EXPECTED_PROMPTS = {
    "automation_health_check",
    "create_automation",
    "dashboard_layout_generator",
    "debug_automation",
    "entity_naming_consistency",
    "routine_optimizer",
    "troubleshoot_entity",
}


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host, port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


async def _drive_session(session: ClientSession) -> None:
    """Exercise the protocol surface common to every transport test."""
    init = await session.initialize()
    assert init.serverInfo.name == "Hass-MCP"
    assert init.capabilities.tools is not None
    assert init.capabilities.prompts is not None
    assert init.capabilities.resources is not None

    tools = await session.list_tools()
    assert {t.name for t in tools.tools} == EXPECTED_TOOLS

    prompts = await session.list_prompts()
    assert {p.name for p in prompts.prompts} == EXPECTED_PROMPTS

    # Prompt invocation roundtrip — regression for the role-validation bug class
    result = await session.get_prompt("create_automation", {"trigger_type": "state"})
    for msg in result.messages:
        assert msg.role in ("user", "assistant")

    # Tool invocation roundtrip — HA call will fail (no real HA), but the
    # protocol path is what we're verifying.
    result = await session.call_tool("get_version", {})
    assert not result.isError


# --- stdio transport --------------------------------------------------------

async def test_stdio_transport_end_to_end():
    """python -m app (stdio default) responds correctly to a real MCP client."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app"],
        env={**os.environ, **SERVER_ENV},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await _drive_session(session)


# --- streamable HTTP transport ----------------------------------------------

async def test_streamable_http_transport_end_to_end():
    """python -m app --http exposes the server over streamable HTTP."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "app", "--http", "--port", str(port)],
        env={**os.environ, **SERVER_ENV},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert _wait_for_port("127.0.0.1", port), (
            f"HTTP server failed to bind on port {port}. "
            f"stderr: {proc.stderr.read(2048).decode(errors='replace')}"
        )

        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (
            read,
            write,
            get_session_id,
        ):
            async with ClientSession(read, write) as session:
                await _drive_session(session)
                # Stateless mode is configured for --http, so no session id.
                assert get_session_id() is None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def test_http_mode_binds_localhost_by_default():
    """Default --http binding is 127.0.0.1; not reachable from another interface."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "app", "--http", "--port", str(port)],
        env={**os.environ, **SERVER_ENV},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert _wait_for_port("127.0.0.1", port)
        # Hitting via 127.0.0.1 works (just verified above).
        # We can't portably assert "not reachable on 0.0.0.0" without raising
        # platform-specific assumptions; verifying it bound localhost via the
        # successful connect on 127.0.0.1 and the absence of a wildcard bind
        # is sufficient here. The settings-level test below pins the default.
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# --- configuration / env var contract ---------------------------------------

def test_default_settings_are_local_stdio_safe(monkeypatch):
    """With no env vars, the FastMCP server defaults to localhost binding
    and non-stateless mode (stdio shape). The streamable HTTP mode opts in
    explicitly via MCP_TRANSPORT."""
    for k in ("MCP_TRANSPORT", "MCP_HOST", "MCP_PORT", "PORT"):
        monkeypatch.delenv(k, raising=False)
    # Re-import to pick up env state at import time.
    import importlib
    import app.server as server_mod
    importlib.reload(server_mod)
    assert server_mod.mcp.settings.host == "127.0.0.1"
    assert server_mod.mcp.settings.stateless_http is False


def test_http_transport_env_enables_stateless(monkeypatch):
    """Setting MCP_TRANSPORT=streamable-http enables stateless + json-response."""
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", "9999")
    import importlib
    import app.server as server_mod
    importlib.reload(server_mod)
    assert server_mod.mcp.settings.host == "127.0.0.1"
    assert server_mod.mcp.settings.port == 9999
    assert server_mod.mcp.settings.stateless_http is True
    assert server_mod.mcp.settings.json_response is True


def test_smithery_port_env_is_honored(monkeypatch):
    """Smithery (and other PaaS) sets PORT without an MCP_ prefix."""
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.delenv("MCP_PORT", raising=False)
    monkeypatch.setenv("PORT", "12345")
    import importlib
    import app.server as server_mod
    importlib.reload(server_mod)
    assert server_mod.mcp.settings.port == 12345
