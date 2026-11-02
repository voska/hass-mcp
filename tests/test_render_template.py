"""Tests for the render_template tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_renders_template():
    """A successful render returns HA's response body verbatim."""
    from app.hass import render_template

    response = MagicMock()
    response.status_code = 200
    response.text = "72.5"
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)

    with patch("app.hass.get_client", AsyncMock(return_value=client)):
        result = await render_template("{{ states('sensor.temp') }}")

    assert result == "72.5"
    _, kwargs = client.post.call_args
    assert kwargs["json"] == {"template": "{{ states('sensor.temp') }}"}


@pytest.mark.asyncio
async def test_passes_variables_when_given():
    from app.hass import render_template

    response = MagicMock()
    response.status_code = 200
    response.text = "42"
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)

    with patch("app.hass.get_client", AsyncMock(return_value=client)):
        await render_template("{{ x * 2 }}", variables={"x": 21})

    _, kwargs = client.post.call_args
    assert kwargs["json"]["variables"] == {"x": 21}


@pytest.mark.asyncio
async def test_omits_variables_key_when_absent():
    from app.hass import render_template

    response = MagicMock()
    response.status_code = 200
    response.text = "ok"
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)

    with patch("app.hass.get_client", AsyncMock(return_value=client)):
        await render_template("{{ 1 }}")

    _, kwargs = client.post.call_args
    assert "variables" not in kwargs["json"]


@pytest.mark.asyncio
async def test_surfaces_jinja_error_rather_than_generic_400():
    """HA puts the actual Jinja message in the 400 body — keep it."""
    from app.hass import render_template

    response = MagicMock()
    response.status_code = 400
    response.text = "UndefinedError: 'nope' is undefined"
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)

    with patch("app.hass.get_client", AsyncMock(return_value=client)):
        result = await render_template("{{ nope.bad }}")

    assert "UndefinedError" in result
    assert "Bad Request" not in result
