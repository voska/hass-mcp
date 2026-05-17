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


@pytest.fixture(autouse=True)
def reset_area_cache():
    """Area cache is a module-level singleton; force a fresh fetch each test
    so respx mocks of /api/template are honored."""
    from app.areas import invalidate_cache
    invalidate_cache()
    yield
    invalidate_cache()


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
    respx.post("http://localhost:8123/api/template").mock(
        return_value=httpx.Response(200, text="light.kitchen\x1fKitchen")
    )
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_entity", arguments={"entity_id": "light.kitchen"}
        )
        assert not result.isError
        text = result.content[0].text
        assert "on" in text
        assert "Kitchen" in text, "area should be surfaced in the lean response"


# --- area resolution -------------------------------------------------------

@respx.mock
async def test_get_entity_includes_area_from_template():
    """Single-entity area lookup hits /api/template; area surfaces in output."""
    respx.get("http://localhost:8123/api/states/light.living_room").mock(
        return_value=httpx.Response(200, json={
            "entity_id": "light.living_room",
            "state": "on",
            "attributes": {"friendly_name": "Living Room Lamp"},
            "last_changed": "2026-01-01T00:00:00+00:00",
            "last_updated": "2026-01-01T00:00:00+00:00",
        })
    )
    respx.post("http://localhost:8123/api/template").mock(
        return_value=httpx.Response(
            200, text="light.living_room\x1fLiving Room\nlight.kitchen\x1fKitchen"
        )
    )
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_entity", arguments={"entity_id": "light.living_room"}
        )
        assert not result.isError
        assert "Living Room" in result.content[0].text


@respx.mock
async def test_entity_without_area_returns_null_not_unknown():
    """Entities with no area assigned must surface as None, not 'Unknown' —
    Issue #28 was caused by the previous 'Unknown' fallback misleading the LLM."""
    import json

    respx.get("http://localhost:8123/api/states/sensor.backup_state").mock(
        return_value=httpx.Response(200, json={
            "entity_id": "sensor.backup_state",
            "state": "idle",
            "attributes": {},
            "last_changed": "2026-01-01T00:00:00+00:00",
            "last_updated": "2026-01-01T00:00:00+00:00",
        })
    )
    # Template returns the entity with empty area (the canonical "no area" shape).
    respx.post("http://localhost:8123/api/template").mock(
        return_value=httpx.Response(200, text="sensor.backup_state\x1f")
    )
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_entity",
            arguments={"entity_id": "sensor.backup_state", "detailed": True},
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["area"] is None, f"area should be null, got {payload['area']!r}"


@respx.mock
async def test_get_entities_by_area_filters_correctly():
    """get_entities_by_area must return only entities in the named area,
    case-insensitively, and pass through additional domain filtering."""
    import json

    respx.get("http://localhost:8123/api/states").mock(
        return_value=httpx.Response(200, json=[
            {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
            {"entity_id": "light.bedroom", "state": "off", "attributes": {}},
            {"entity_id": "sensor.kitchen_temp", "state": "20", "attributes": {}},
        ])
    )
    respx.post("http://localhost:8123/api/template").mock(
        return_value=httpx.Response(200, text=(
            "light.kitchen\x1fKitchen\n"
            "light.bedroom\x1fBedroom\n"
            "sensor.kitchen_temp\x1fKitchen"
        ))
    )

    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        # Case-insensitive area match, no domain filter.
        result = await client.call_tool("get_entities_by_area", {"area": "kitchen"})
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["count"] == 2
        ids = {e["entity_id"] for e in payload["entities"]}
        assert ids == {"light.kitchen", "sensor.kitchen_temp"}
        assert payload["area"] == "Kitchen"  # canonicalized from the matched entities


@respx.mock
async def test_area_cache_handles_template_failure_gracefully():
    """If /api/template fails, area lookups return None but the tool still
    succeeds — area is a best-effort enrichment, not a hard requirement."""
    import json

    respx.get("http://localhost:8123/api/states/light.kitchen").mock(
        return_value=httpx.Response(200, json={
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {},
            "last_changed": "2026-01-01T00:00:00+00:00",
            "last_updated": "2026-01-01T00:00:00+00:00",
        })
    )
    respx.post("http://localhost:8123/api/template").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_entity",
            arguments={"entity_id": "light.kitchen", "detailed": True},
        )
        assert not result.isError, "tool must not fail when area enrichment fails"
        payload = json.loads(result.content[0].text)
        assert payload["area"] is None


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


# --- Filter tests (#34) -----------------------------------------------------

# Realistic sample log: mix of levels, integrations (bare + namespaced),
# entity IDs to grep, and enough lines to test `lines` truncation.
SAMPLE_LOG = (
    "2026-05-16 12:00:00 INFO (MainThread) [homeassistant.core] starting up\n"
    "2026-05-16 12:00:01 ERROR (MainThread) [homeassistant.components.mqtt] connection refused\n"
    "2026-05-16 12:00:02 WARNING (MainThread) [zwave_js] node 5 retrying\n"
    "2026-05-16 12:00:03 ERROR (MainThread) [homeassistant.components.zwave_js] command timeout on light.kitchen\n"
    "2026-05-16 12:00:04 INFO (MainThread) [homeassistant.components.light] turning on light.living_room\n"
    "2026-05-16 12:00:05 ERROR (MainThread) [homeassistant.components.mqtt] reconnect failed\n"
    "2026-05-16 12:00:06 WARNING (MainThread) [homeassistant.components.light] light.kitchen unavailable\n"
)


def _mock_hassio_log(text: str = SAMPLE_LOG):
    respx.get("http://localhost:8123/api/hassio/core/logs").mock(
        return_value=httpx.Response(200, text=text)
    )


@respx.mock
async def test_get_error_log_filter_by_level():
    """level=ERROR keeps only ERROR lines and recomputes counts."""
    import json
    _mock_hassio_log()
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_error_log", arguments={"level": "ERROR"}
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["error_count"] == 3
        assert payload["warning_count"] == 0
        assert payload["total_lines"] == 3
        assert "WARNING" not in payload["log_text"]
        assert "INFO" not in payload["log_text"]
        assert payload["filters_applied"] == {"level": "ERROR"}


@respx.mock
async def test_get_error_log_filter_by_integration_namespaced():
    """integration=mqtt matches [homeassistant.components.mqtt]."""
    import json
    _mock_hassio_log()
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_error_log", arguments={"integration": "mqtt"}
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["total_lines"] == 2
        assert payload["error_count"] == 2
        assert "zwave" not in payload["log_text"].lower()


@respx.mock
async def test_get_error_log_filter_by_integration_bare():
    """integration=zwave_js also matches the bare `[zwave_js]` form."""
    import json
    _mock_hassio_log()
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_error_log", arguments={"integration": "zwave_js"}
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)
        # Both `[zwave_js]` (bare) and `[homeassistant.components.zwave_js]`.
        assert payload["total_lines"] == 2


@respx.mock
async def test_get_error_log_filter_by_search_term():
    """search_term matches a substring, case-insensitive."""
    import json
    _mock_hassio_log()
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_error_log", arguments={"search_term": "light.kitchen"}
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["total_lines"] == 2
        assert all(
            "light.kitchen" in line.lower()
            for line in payload["log_text"].splitlines()
        )


@respx.mock
async def test_get_error_log_filter_by_lines_returns_tail():
    """lines=N returns only the last N lines after other filters."""
    import json
    _mock_hassio_log()
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_error_log", arguments={"lines": 2}
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["total_lines"] == 2
        # The last two lines of SAMPLE_LOG.
        assert "reconnect failed" in payload["log_text"]
        assert "light.kitchen unavailable" in payload["log_text"]


@respx.mock
async def test_get_error_log_filters_combine_and_stats_match_filtered():
    """Combined filters AND together; stats are computed over filtered text."""
    import json
    _mock_hassio_log()
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "get_error_log",
            arguments={"level": "ERROR", "integration": "mqtt"},
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["total_lines"] == 2
        assert payload["error_count"] == 2
        # integration_mentions should reflect mqtt-only output.
        assert payload["integration_mentions"].get("mqtt") == 2
        assert "zwave_js" not in payload["integration_mentions"]
        assert payload["filters_applied"] == {
            "level": "ERROR",
            "integration": "mqtt",
        }


@respx.mock
async def test_get_error_log_no_filters_applied_field_empty():
    """With no filters, filters_applied is an empty dict (not missing)."""
    import json
    _mock_hassio_log()
    async with create_connected_server_and_client_session(
        mcp._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool("get_error_log", arguments={})
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload["filters_applied"] == {}
        assert payload["total_lines"] == 7
