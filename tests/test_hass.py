import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import json
import httpx
from typing import Dict, List, Any

from app.hass import get_entity_state, call_service, get_entities, get_automations, handle_api_errors

class TestHassAPI:
    """Test the Home Assistant API functions."""

    @pytest.mark.asyncio
    async def test_get_entities(self, mock_config):
        """Test getting all entities."""
        # Mock response data
        mock_states = [
            {"entity_id": "light.living_room", "state": "on", "attributes": {"brightness": 255}},
            {"entity_id": "switch.kitchen", "state": "off", "attributes": {}}
        ]
        
        # Create mock response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_states
        
        # Create properly awaitable mock
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        
        # Setup client mocking
        with patch('app.hass.get_client', return_value=mock_client):
            with patch('app.hass.HA_URL', mock_config["hass_url"]):
                with patch('app.hass.HA_TOKEN', mock_config["hass_token"]):
                            # Test function
                            states = await get_entities()
                            
                            # Assertions
                            assert isinstance(states, list)
                            assert len(states) == 2
                            
                            # Verify API was called correctly
                            mock_client.get.assert_called_once()
                            called_url = mock_client.get.call_args[0][0]
                            assert called_url == f"{mock_config['hass_url']}/api/states"

    @pytest.mark.asyncio
    async def test_get_entity_state(self, mock_config):
        """Test getting a specific entity state."""
        # Mock response data
        mock_state = {"entity_id": "light.living_room", "state": "on"}
        
        # Create mock response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_state
        
        # Create properly awaitable mock
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        
        # Patch the client
        with patch('app.hass.get_client', return_value=mock_client):
            with patch('app.hass.HA_URL', mock_config["hass_url"]):
                with patch('app.hass.HA_TOKEN', mock_config["hass_token"]):
                    # Test function - use_cache parameter has been removed
                    state = await get_entity_state("light.living_room")
                    
                    # Assertions
                    assert isinstance(state, dict)
                    assert state["entity_id"] == "light.living_room"
                    assert state["state"] == "on"
                    
                    # Verify API was called correctly
                    mock_client.get.assert_called_once()
                    called_url = mock_client.get.call_args[0][0]
                    assert called_url == f"{mock_config['hass_url']}/api/states/light.living_room"

    @pytest.mark.asyncio
    async def test_call_service(self, mock_config):
        """Test calling a service."""
        domain = "light"
        service = "turn_on"
        data = {"entity_id": "light.living_room", "brightness": 255}
        
        # Create mock response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        
        # Create properly awaitable mock
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        # Patch the client
        with patch('app.hass.get_client', return_value=mock_client):
            with patch('app.hass.HA_URL', mock_config["hass_url"]):
                with patch('app.hass.HA_TOKEN', mock_config["hass_token"]):
                        # Test function
                        result = await call_service(domain, service, data)
                        
                        # Assertions
                        assert isinstance(result, dict)
                        assert result["result"] == "ok"
                        
                        # Verify API was called correctly
                        mock_client.post.assert_called_once()
                        called_url = mock_client.post.call_args[0][0]
                        called_data = mock_client.post.call_args[1].get('json')
                        assert called_url == f"{mock_config['hass_url']}/api/services/{domain}/{service}"
                        assert called_data == data

    @pytest.mark.asyncio
    async def test_get_automations(self, mock_config):
        """Test getting automations from the states API."""
        # Mock states response with automation entities
        mock_automation_states = [
            {
                "entity_id": "automation.morning_lights", 
                "state": "on", 
                "attributes": {
                    "friendly_name": "Turn on lights in the morning",
                    "last_triggered": "2025-03-15T07:00:00Z"
                }
            },
            {
                "entity_id": "automation.night_lights",
                "state": "off",
                "attributes": {
                    "friendly_name": "Turn off lights at night"
                }
            }
        ]
        
        # Patch the token to avoid the "No token" error
        with patch('app.hass.HA_TOKEN', mock_config["hass_token"]):
            with patch('app.hass.HA_URL', mock_config["hass_url"]):
                # For get_automations we need to mock the get_entities function
                with patch('app.hass.get_entities', AsyncMock(return_value=mock_automation_states)):
                    # Test function
                    automations = await get_automations()
                    
                    # Assertions
                    assert isinstance(automations, list)
                    assert len(automations) == 2
                    
                    # Verify contents of first automation
                    assert automations[0]["entity_id"] == "automation.morning_lights"
                    assert automations[0]["state"] == "on"
                    assert automations[0]["alias"] == "Turn on lights in the morning"
                    assert automations[0]["last_triggered"] == "2025-03-15T07:00:00Z"
                    
                # Test error response
                with patch('app.hass.get_entities', AsyncMock(return_value={"error": "HTTP error: 404 - Not Found"})):
                    # Test function with error
                    automations = await get_automations()
                    
                    # In our new implementation, it should pass through the error
                    assert isinstance(automations, dict)
                    assert "error" in automations
                    assert "404" in automations["error"]

    @pytest.mark.asyncio
    async def test_get_entity_history(self, mock_config):
        """Test getting entity history."""
        entity_id = "sensor.temperature"
        hours = 24

        # Mock response data for history
        mock_history_data = [
            [
                {
                    "state": "25.0",
                    "last_changed": "2025-06-30T10:00:00.000Z",
                    "attributes": {"unit_of_measurement": "°C"}
                },
                {
                    "state": "26.0",
                    "last_changed": "2025-06-30T11:00:00.000Z",
                    "attributes": {"unit_of_measurement": "°C"}
                }
            ]
        ]

        # Create mock response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_history_data

        # Create properly awaitable mock
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        # Patch the client and HA_URL/HA_TOKEN
        with patch('app.hass.get_client', return_value=mock_client):
            with patch('app.hass.HA_URL', mock_config["hass_url"]):
                with patch('app.hass.HA_TOKEN', mock_config["hass_token"]):
                    from app.hass import get_entity_history
                    history = await get_entity_history(entity_id, hours)

                    # Assertions
                    assert isinstance(history, list)
                    assert len(history) == 1  # History API returns list of lists
                    assert len(history[0]) == 2
                    assert history[0][0]["state"] == "25.0"
                    assert history[0][1]["state"] == "26.0"

                    # Verify API was called correctly
                    mock_client.get.assert_called_once()
                    called_url = mock_client.get.call_args[0][0]
                    assert f"{mock_config['hass_url']}/api/history/period/" in called_url
                    assert mock_client.get.call_args[1]["params"]["filter_entity_id"] == entity_id

    def test_handle_api_errors_decorator(self):
        """Test the handle_api_errors decorator."""
        from app.hass import handle_api_errors
        import inspect
        
        # Create a simple test function with a Dict return annotation
        @handle_api_errors
        async def test_dict_function() -> Dict:
            """Test function that returns a dict."""
            return {}
        
        # Create a simple test function with a str return annotation
        @handle_api_errors
        async def test_str_function() -> str:
            """Test function that returns a string."""
            return ""
        
        # Verify that both functions have their return type annotations preserved
        assert "Dict" in str(inspect.signature(test_dict_function).return_annotation)
        assert "str" in str(inspect.signature(test_str_function).return_annotation)
        
        # Verify that both functions have a docstring
        assert test_dict_function.__doc__ == "Test function that returns a dict."
        assert test_str_function.__doc__ == "Test function that returns a string."