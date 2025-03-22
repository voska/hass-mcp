"""Home Assistant entity-related tools for the MCP server."""
import json
from typing import Optional

from app.hass_client import HassClient


async def get_entity(client: HassClient, entity_id: str) -> str:
    """Get a specific entity from Home Assistant.
    
    Args:
        client: The Home Assistant client
        entity_id: The entity ID to retrieve (e.g., 'light.living_room')
        
    Returns:
        String representation of the entity state
    """
    try:
        # Get all states
        states = await client.get_states()
        
        # Find the specific entity
        for state in states:
            if state.entity_id == entity_id:
                # Format the result as a JSON string
                entity_info = {
                    "entity_id": state.entity_id,
                    "state": state.state,
                    "attributes": state.attributes,
                    "last_updated": str(state.last_updated),
                    "last_changed": str(state.last_changed)
                }
                
                return json.dumps(entity_info, indent=2)
        
        return f"Entity '{entity_id}' not found"
    except Exception as e:
        return f"Error retrieving entity '{entity_id}': {str(e)}"


async def list_entities(client: HassClient, domain: Optional[str] = None) -> str:
    """List entities from Home Assistant with their full details, optionally filtered by domain.
    
    Args:
        client: The Home Assistant client
        domain: Optional domain to filter entities by (e.g., 'light', 'sensor')
        
    Returns:
        String representation of a JSON list containing entities with their details
    """
    try:
        # Get all states
        states = await client.get_states()
        
        # Create a detailed list of all entities, filtering by domain if specified
        entities = []
        for state in states:
            # Apply domain filter if specified
            if domain and not state.entity_id.startswith(f"{domain}."):
                continue
                
            # Format each entity with full details, similar to get_entity
            entity_info = {
                "entity_id": state.entity_id,
                "state": state.state,
                "attributes": state.attributes,
                "last_updated": str(state.last_updated),
                "last_changed": str(state.last_changed)
            }
            
            entities.append(entity_info)
        
        # Sort entities by entity_id
        entities.sort(key=lambda x: x["entity_id"])
        
        # Return a simple JSON list of entities without any wrapper
        return json.dumps(entities, indent=2)
    except Exception as e:
        return f"Error retrieving entities: {str(e)}"


async def list_automations(client: HassClient) -> str:
    """List all automations from Home Assistant.
    
    Args:
        client: The Home Assistant client
        
    Returns:
        String representation of all automations with detailed information
    """
    try:
        # Get all states
        states = await client.get_states()
        
        # Filter for automation entities
        automations = []
        for state in states:
            if state.entity_id.startswith("automation."):
                # Collect all available attributes
                automation_info = {
                    "id": state.entity_id,
                    "name": state.attributes.get("friendly_name", state.entity_id.replace("automation.", "")),
                    "state": state.state,
                    "last_triggered": state.attributes.get("last_triggered", "Never"),
                    "mode": state.attributes.get("mode", "single"),
                    "current_run": state.attributes.get("current", None),
                    "max_runs": state.attributes.get("max", None)
                }
                
                automations.append(automation_info)
        
        if not automations:
            return "No automations found"
        
        # Sort automations by name
        automations.sort(key=lambda x: x["name"])
        
        return json.dumps(automations, indent=2)
    except Exception as e:
        return f"Error retrieving automations: {str(e)}"