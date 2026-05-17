"""
MCP protocol-level tests for hass-mcp.

Drives the server through the real MCP protocol (initialize, list_tools,
call_tool, list_prompts, get_prompt) over an in-memory transport, with the
Home Assistant HTTP backend mocked by respx. Complements tests/test_server.py,
which calls tool functions as plain Python and never crosses the protocol
boundary — that surface misses bugs in tool output serialization and prompt
message validation.

Uses pytest-anyio rather than pytest-asyncio: the MCP SDK's in-memory transport
runs inside an anyio task group, which conflicts with pytest-asyncio's task
boundary across fixture setup and test body.
"""

import pytest
import respx
import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from app.server import mcp


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# tests/conftest.py installs an autouse fixture that replaces httpx.AsyncClient
# with a MagicMock. That prevents respx from intercepting at the transport
# layer. Override here so the real httpx runs and respx can mock it.
@pytest.fixture(autouse=True)
def mock_get_client():
    yield


# --- Sanity tests (expected to pass on master) ------------------------------

async def test_initialize_handshake():
    """The server completes the MCP initialize handshake."""
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.send_ping()
        assert result is not None


EXPECTED_TOOLS = {
    "call_service_tool",
    "domain_summary_tool",
    "entity_action",
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


async def test_list_tools_returns_expected_set():
    """The set of registered tools matches what the server advertises."""
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.list_tools()
        got = {t.name for t in result.tools}
        assert got == EXPECTED_TOOLS, f"Tool surface drift: {got ^ EXPECTED_TOOLS}"


EXPECTED_PROMPTS = {
    "automation_health_check",
    "create_automation",
    "dashboard_layout_generator",
    "debug_automation",
    "entity_naming_consistency",
    "routine_optimizer",
    "troubleshoot_entity",
}


async def test_list_prompts_returns_expected_set():
    """The set of registered prompts matches what the server advertises."""
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.list_prompts()
        got = {p.name for p in result.prompts}
        assert got == EXPECTED_PROMPTS, f"Prompt surface drift: {got ^ EXPECTED_PROMPTS}"


# --- Bug detectors (currently fail on master) -------------------------------

# Minimal arguments needed to invoke each prompt.
PROMPT_ARGS = {
    "create_automation": {"trigger_type": "state"},
    "debug_automation": {"automation_id": "automation.test"},
    "troubleshoot_entity": {"entity_id": "light.test"},
    "routine_optimizer": {},
    "automation_health_check": {},
    "entity_naming_consistency": {},
    "dashboard_layout_generator": {},
}


async def test_all_prompts_use_valid_roles():
    """Every prompt message must have role in {user, assistant} per MCP spec."""
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        prompts = await client.list_prompts()
        bad = []
        for p in prompts.prompts:
            args = PROMPT_ARGS.get(p.name, {})
            result = await client.get_prompt(p.name, arguments=args)
            for i, msg in enumerate(result.messages):
                if msg.role not in ("user", "assistant"):
                    bad.append(f"{p.name}.messages[{i}].role={msg.role!r}")
        assert not bad, "Invalid prompt roles: " + "; ".join(bad)


@respx.mock
async def test_call_service_tool_returns_dict_for_empty_list():
    """call_service_tool must yield a dict even when HA returns [] (e.g. automation.reload).

    The tool is annotated `Dict[str, Any]` and MCP SDKs that enforce return-type
    validation reject list payloads. The serialized result must parse to a dict.
    """
    import json

    respx.post("http://localhost:8123/api/services/automation/reload").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "call_service_tool",
            arguments={"domain": "automation", "service": "reload"},
        )
        assert not result.isError, f"call_service_tool errored: {result.content}"
        payload = json.loads(result.content[0].text)
        assert isinstance(payload, dict), (
            f"call_service_tool returned {type(payload).__name__}, expected dict. "
            f"This breaks MCP output validation on SDKs that enforce the return "
            f"type annotation. Got: {payload!r}"
        )


# --- Roundtrip with respx (expected to pass on master) ----------------------

@respx.mock
async def test_get_entity_via_protocol():
    """End-to-end: MCP protocol -> tool -> mocked HA -> response surfaces in tool output."""
    respx.get("http://localhost:8123/api/states/light.kitchen").mock(
        return_value=httpx.Response(
            200,
            json={
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"brightness": 255},
                "last_changed": "2026-01-01T00:00:00+00:00",
                "last_updated": "2026-01-01T00:00:00+00:00",
            },
        )
    )
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_entity", arguments={"entity_id": "light.kitchen"}
        )
        assert not result.isError
        assert "on" in result.content[0].text


@respx.mock
async def test_get_error_log_uses_hassio_endpoint_on_ha_os():
    """HA OS / Supervised exposes Core logs at /api/hassio/core/logs; the
    standalone /api/error_log endpoint returns 404 there. get_error_log must
    try the hassio endpoint first."""
    import json

    respx.get("http://localhost:8123/api/hassio/core/logs").mock(
        return_value=httpx.Response(
            200,
            text="2026-05-16 12:00:00 ERROR (MainThread) [mqtt] connection lost\n"
                 "2026-05-16 12:00:01 WARNING (MainThread) [zwave] retrying\n",
        )
    )
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool("get_error_log", arguments={})
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["error_count"] == 1
        assert payload["warning_count"] == 1
        assert payload["integration_mentions"]["mqtt"] == 1
        assert payload["integration_mentions"]["zwave"] == 1


@respx.mock
async def test_get_error_log_falls_back_to_standalone_endpoint():
    """When /api/hassio/core/logs is unavailable (standalone Home Assistant
    install), get_error_log must fall back to /api/error_log."""
    import json

    respx.get("http://localhost:8123/api/hassio/core/logs").mock(
        return_value=httpx.Response(404, text="Not Found")
    )
    # ANSI color codes are stripped from the parsed output and excluded from counts.
    respx.get("http://localhost:8123/api/error_log").mock(
        return_value=httpx.Response(
            200,
            text="\x1b[31mERROR\x1b[0m [homeassistant.components.light] failed\n",
        )
    )
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool("get_error_log", arguments={})
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert "\x1b[" not in payload["log_text"], "ANSI codes must be stripped"
        assert payload["error_count"] == 1
        assert payload["integration_mentions"]["light"] == 1
