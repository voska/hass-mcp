"""Home Assistant search-related tools for the MCP server."""
import json
import re
from typing import Optional, List, Dict, Any

from app.hass_client import HassClient


async def search_entities(client: HassClient, 
                         query: str, 
                         domain: Optional[str] = None,
                         search_attributes: bool = True) -> str:
    """Search for entities by name, state, or attributes.
    
    Args:
        client: The Home Assistant client
        query: The search query string (case-insensitive)
        domain: Optional domain to filter entities by (e.g., 'light', 'sensor')
        search_attributes: Whether to search in entity attributes (default: True)
        
    Returns:
        String representation of a JSON list containing matching entities with their details
    """
    try:
        # Get all states
        states = await client.get_states()
        
        # Prepare the search query
        query_pattern = re.compile(query, re.IGNORECASE)
        
        # Track the matches
        matches = []
        
        # Search through all entities
        for state in states:
            # Apply domain filter if specified
            if domain and not state.entity_id.startswith(f"{domain}."):
                continue
            
            # Check if entity matches any of our criteria
            matched = False
            
            # Check entity_id and state match
            if (query_pattern.search(state.entity_id) or 
                query_pattern.search(state.state)):
                matched = True
            
            # Check attributes match
            elif search_attributes:
                for attr_name, attr_value in state.attributes.items():
                    # Match in attribute name
                    if query_pattern.search(attr_name):
                        matched = True
                        break
                    
                    # Match in attribute value (if it's a string)
                    if isinstance(attr_value, str) and query_pattern.search(attr_value):
                        matched = True
                        break
            
            # If there's any match, add to results
            if matched:
                matches.append({
                    "entity_id": state.entity_id,
                    "state": state.state,
                    "friendly_name": state.attributes.get("friendly_name", "")
                })
        
        # Return empty list if no matches
        if not matches:
            return json.dumps({
                "query": query,
                "domain_filter": domain,
                "count": 0,
                "results": []
            }, indent=2)
        
        # Sort matches by entity_id
        matches.sort(key=lambda x: x["entity_id"])
        
        # Create the response
        response = {
            "query": query,
            "domain_filter": domain,
            "count": len(matches),
            "results": matches
        }
        
        return json.dumps(response, indent=2)
    except Exception as e:
        return json.dumps({
            "query": query,
            "domain_filter": domain,
            "error": str(e),
            "results": []
        }, indent=2)
