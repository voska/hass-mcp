"""Home Assistant service-related tools for the MCP server."""
import asyncio
import json
from typing import Dict, Any, Optional

from app.hass_client import HassClient


async def call_service(client: HassClient, domain: str, service: str, 
                      entity_id: Optional[str] = None, 
                      service_data: Optional[Dict[str, Any]] = None) -> str:
    """Call a service in Home Assistant.
    
    Args:
        client: The Home Assistant client
        domain: The domain of the service to call (e.g., 'light', 'switch')
        service: The service to call (e.g., 'turn_on', 'turn_off')
        entity_id: Optional entity ID to call the service on
        service_data: Optional additional data to pass to the service
        
    Returns:
        String representation of the service call result
    """
    try:
        # Prepare service data
        data = service_data or {}
        
        # Add entity_id to service data if provided
        if entity_id:
            data["entity_id"] = entity_id
            
        # Call the service
        try:
            result = await client.trigger_service(domain, service, **data)
        except Exception as service_error:
            return json.dumps({
                "service_call": {
                    "domain": domain,
                    "service": service,
                    "entity_id": entity_id,
                    "data": data
                },
                "result": "error",
                "error": str(service_error)
            }, indent=2)
        
        # The result is a tuple of states that were changed by the service call
        changed_entities = []
        
        # Process the result if available
        if result and isinstance(result, tuple):
            for state in result:
                state_dict = {
                    "entity_id": state.entity_id,
                    "state": state.state,
                    "attributes": state.attributes,
                    "last_updated": str(state.last_updated),
                    "last_changed": str(state.last_changed)
                }
                changed_entities.append(state_dict)
        
        # If we have a specific entity_id, check if it was updated
        target_entity = None
        if entity_id:
            # First check if it was in the changed entities
            for entity in changed_entities:
                if entity["entity_id"] == entity_id:
                    target_entity = entity
                    break
            
            # If not found in changed entities, fetch the current state
            if not target_entity:
                # Give Home Assistant a moment to update the state
                await asyncio.sleep(0.5)
                
                # Fetch the updated entity state
                states = await client.get_states()
                for state in states:
                    if state.entity_id == entity_id:
                        target_entity = {
                            "entity_id": state.entity_id,
                            "state": state.state,
                            "attributes": state.attributes,
                            "last_updated": str(state.last_updated),
                            "last_changed": str(state.last_changed)
                        }
                        break
        
        # Create the response
        response = {
            "service_call": {
                "domain": domain,
                "service": service,
                "data": data
            },
            "result": "success",
            "changed_entities": changed_entities
        }
        
        # Add target entity if available
        if target_entity:
            response["target_entity"] = target_entity
            
        return json.dumps(response, indent=2)
    except Exception as e:
        return json.dumps({
            "service_call": {
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
                "data": service_data
            },
            "result": "error",
            "error": str(e)
        }, indent=2)