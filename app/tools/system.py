"""Home Assistant system-related tools for the MCP server."""
import json
from typing import Optional

from app.hass_client import HassClient


async def get_hass_version(client: HassClient) -> str:
    """Get the Home Assistant version."""
    version = await client.get_version()
    return f"Home Assistant version: {version}"


async def get_system_overview(client: HassClient) -> str:
    """Get a comprehensive overview of the entire Home Assistant system.
    
    Args:
        client: The Home Assistant client
        
    Returns:
        A formatted JSON string containing:
        - total_entities: Total count of all entities
        - domains: Dictionary of domains with:
          - count: Number of entities in the domain
          - samples: 1-2 representative entities from that domain
          - common_attributes: Attributes common to all entities in the domain (besides friendly_name)
    """
    try:
        # Get all states
        states = await client.get_states()
        
        # Calculate domain statistics
        domains = {}
        total_entities = len(states)
        
        # Analyze all entities to build the overview
        for state in states:
            domain = state.entity_id.split('.')[0]
            
            # Initialize domain data structure if this is the first entity in this domain
            if domain not in domains:
                domains[domain] = {
                    "count": 0,
                    "common_attributes": set(),
                    "samples": []
                }
            
            # Increment count for this domain
            domains[domain]["count"] += 1
            
            # Track attribute keys for this domain to find common ones
            attribute_keys = set(state.attributes.keys())
            # Remove friendly_name from consideration
            if "friendly_name" in attribute_keys:
                attribute_keys.remove("friendly_name")
                
            if domains[domain]["count"] == 1:
                # First entity for this domain, set initial attributes
                domains[domain]["common_attributes"] = attribute_keys
            else:
                # Update common attributes to be the intersection
                domains[domain]["common_attributes"] &= attribute_keys
            
            # Keep up to 2 sample entities for each domain
            if len(domains[domain]["samples"]) < 2:
                entity_sample = {
                    "entity_id": state.entity_id,
                    "state": state.state,
                    "attributes": state.attributes
                }
                domains[domain]["samples"].append(entity_sample)
        
        # Format the result
        overview = {
            "total_entities": total_entities,
            "domains": {}
        }
        
        # Convert to proper dictionaries
        for domain, data in domains.items():
            overview["domains"][domain] = {
                "count": data["count"],
                "common_attributes": list(data["common_attributes"]),
                "samples": data["samples"]
            }
        
        return json.dumps(overview, indent=2)
    except Exception as e:
        return f"Error retrieving system overview: {str(e)}"
        
        
async def get_error_log(client: HassClient, max_lines: Optional[int] = 100) -> str:
    """Get the Home Assistant error log, with optional line limit.
    
    Args:
        client: The Home Assistant client
        max_lines: Maximum number of lines to return (default: 100)
        
    Returns:
        String representation of the error log, possibly truncated
        
    Examples:
        >>> await get_error_log(client, 50)
        '{"status": "success", "log_type": "error", ...}'
    """
    try:
        # Call the Home Assistant API to get the error log directly from the client
        log_response = await client._client.async_get_error_log()
        
        if not log_response:
            return json.dumps({
                "status": "success",
                "log_type": "error",
                "log": "Error log is empty",
                "truncated": False
            }, indent=2)
        
        # Split the log into lines
        log_lines = log_response.splitlines()
        total_lines = len(log_lines)
        
        # Apply truncation if needed
        truncated = total_lines > max_lines
        if truncated:
            log_lines = log_lines[-max_lines:]  # Get the most recent lines
        
        # Join lines back together
        log_content = "\n".join(log_lines)
        
        # Create the response
        response = {
            "status": "success",
            "log_type": "error",
            "total_lines": total_lines,
            "returned_lines": len(log_lines),
            "truncated": truncated,
            "log": log_content
        }
        
        return json.dumps(response, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "log_type": "error",
            "error": str(e)
        }, indent=2)