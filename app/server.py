import functools
import logging
import json
import httpx
from typing import List, Dict, Any, Optional, Callable, Awaitable, TypeVar, cast

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from app.hass import (
    get_hass_version, get_entity_state, call_service, get_entities,
    get_automations, restart_home_assistant, 
    cleanup_client, filter_fields, summarize_domain, get_system_overview,
    get_hass_error_log, get_entity_history
)

# Type variable for generic functions
T = TypeVar('T')

# Create an MCP server
from mcp.server.fastmcp import FastMCP, Context, Image
from mcp.server.stdio import stdio_server
import mcp.types as types
mcp = FastMCP("Hass-MCP")

def async_handler(command_type: str):
    """
    Simple decorator that logs the command
    
    Args:
        command_type: The type of command (for logging)
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            logger.info(f"Executing command: {command_type}")
            return await func(*args, **kwargs)
        return cast(Callable[..., Awaitable[T]], wrapper)
    return decorator

@mcp.tool()
@async_handler("get_version")
async def get_version() -> str:
    """
    Get the Home Assistant version
    
    Returns:
        A string with the Home Assistant version (e.g., "2025.3.0")
    """
    logger.info("Getting Home Assistant version")
    return await get_hass_version()

@mcp.tool()
@async_handler("get_entity")
async def get_entity(entity_id: str, fields: Optional[List[str]] = None, detailed: bool = False) -> dict:
    """
    Get the state of a Home Assistant entity with optional field filtering
    
    Args:
        entity_id: The entity ID to get (e.g. 'light.living_room')
        fields: Optional list of fields to include (e.g. ['state', 'attr.brightness'])
        detailed: If True, returns all entity fields without filtering
                
    Examples:
        entity_id="light.living_room" - basic state check
        entity_id="light.living_room", fields=["state", "attr.brightness"] - specific fields
        entity_id="light.living_room", detailed=True - all details
    """
    logger.info(f"Getting entity state: {entity_id}")
    if detailed:
        # Return all fields
        return await get_entity_state(entity_id, lean=False)
    elif fields:
        # Return only the specified fields
        return await get_entity_state(entity_id, fields=fields)
    else:
        # Return lean format with essential fields
        return await get_entity_state(entity_id, lean=True)

@mcp.tool()
@async_handler("entity_action")
async def entity_action(entity_id: str, action: str, params: Optional[Dict[str, Any]] = None) -> dict:
    """
    Perform an action on a Home Assistant entity (on, off, toggle)
    
    Args:
        entity_id: The entity ID to control (e.g. 'light.living_room')
        action: The action to perform ('on', 'off', 'toggle')
        params: Optional dictionary of additional parameters for the service call
    
    Returns:
        The response from Home Assistant
    
    Examples:
        entity_id="light.living_room", action="on", params={"brightness": 255}
        entity_id="switch.garden_lights", action="off"
        entity_id="climate.living_room", action="on", params={"temperature": 22.5}
    
    Domain-Specific Parameters:
        - Lights: brightness (0-255), color_temp, rgb_color, transition, effect
        - Covers: position (0-100), tilt_position
        - Climate: temperature, target_temp_high, target_temp_low, hvac_mode
        - Media players: source, volume_level (0-1)
    """
    if action not in ["on", "off", "toggle"]:
        return {"error": f"Invalid action: {action}. Valid actions are 'on', 'off', 'toggle'"}
    
    # Map action to service name
    service = action if action == "toggle" else f"turn_{action}"
    
    # Extract the domain from the entity_id
    domain = entity_id.split(".")[0]
    
    # Prepare service data
    data = {"entity_id": entity_id, **(params or {})}
    
    logger.info(f"Performing action '{action}' on entity: {entity_id} with params: {params}")
    return await call_service(domain, service, data)

@mcp.resource("hass://entities/{entity_id}")
@async_handler("get_entity_resource")
async def get_entity_resource(entity_id: str) -> str:
    """
    Get the state of a Home Assistant entity as a resource
    
    This endpoint provides a standard view with common entity information.
    For comprehensive attribute details, use the /detailed endpoint.
    
    Args:
        entity_id: The entity ID to get information for
    """
    logger.info(f"Getting entity resource: {entity_id}")
    
    # Get the entity state with caching (using lean format for token efficiency)
    state = await get_entity_state(entity_id, use_cache=True, lean=True)
    
    # Check if there was an error
    if "error" in state:
        return f"# Entity: {entity_id}\n\nError retrieving entity: {state['error']}"
    
    # Format the entity as markdown
    result = f"# Entity: {entity_id}\n\n"
    
    # Get friendly name if available
    friendly_name = state.get("attributes", {}).get("friendly_name")
    if friendly_name and friendly_name != entity_id:
        result += f"**Name**: {friendly_name}\n\n"
    
    # Add state
    result += f"**State**: {state.get('state')}\n\n"
    
    # Add domain info
    domain = entity_id.split(".")[0]
    result += f"**Domain**: {domain}\n\n"
    
    # Add key attributes based on domain type
    attributes = state.get("attributes", {})
    
    # Add a curated list of important attributes
    important_attrs = []
    
    # Common attributes across many domains
    common_attrs = ["device_class", "unit_of_measurement", "friendly_name"]
    
    # Domain-specific important attributes
    if domain == "light":
        important_attrs = ["brightness", "color_temp", "rgb_color", "supported_features", "supported_color_modes"] 
    elif domain == "sensor":
        important_attrs = ["unit_of_measurement", "device_class", "state_class"]
    elif domain == "climate":
        important_attrs = ["hvac_mode", "hvac_action", "temperature", "current_temperature", "target_temp_*"]
    elif domain == "media_player":
        important_attrs = ["media_title", "media_artist", "source", "volume_level", "media_content_type"]
    elif domain == "switch" or domain == "binary_sensor":
        important_attrs = ["device_class", "is_on"]
    
    # Combine with common attributes
    important_attrs.extend(common_attrs)
    
    # Deduplicate the list while preserving order
    important_attrs = list(dict.fromkeys(important_attrs))
    
    # Create and add the important attributes section
    result += "## Key Attributes\n\n"
    
    # Display only the important attributes that exist
    displayed_attrs = 0
    for attr_name in important_attrs:
        # Handle wildcard attributes (e.g., target_temp_*)
        if attr_name.endswith("*"):
            prefix = attr_name[:-1]
            matching_attrs = [name for name in attributes if name.startswith(prefix)]
            for name in matching_attrs:
                result += f"- **{name}**: {attributes[name]}\n"
                displayed_attrs += 1
        # Regular attribute match
        elif attr_name in attributes:
            attr_value = attributes[attr_name]
            if isinstance(attr_value, (list, dict)) and len(str(attr_value)) > 100:
                result += f"- **{attr_name}**: *[Complex data]*\n"
            else:
                result += f"- **{attr_name}**: {attr_value}\n"
            displayed_attrs += 1
    
    # If no important attributes were found, show a message
    if displayed_attrs == 0:
        result += "No key attributes found for this entity type.\n\n"
    
    # Add attribute count and link to detailed view
    total_attr_count = len(attributes)
    if total_attr_count > displayed_attrs:
        hidden_count = total_attr_count - displayed_attrs
        result += f"\n**Note**: Showing {displayed_attrs} of {total_attr_count} total attributes. "
        result += f"{hidden_count} additional attributes are available in the [detailed view](/api/resource/hass://entities/{entity_id}/detailed).\n\n"
    
    # Add last updated time if available
    if "last_updated" in state:
        result += f"**Last Updated**: {state['last_updated']}\n"
    
    return result

@mcp.tool()
@async_handler("list_entities")
async def list_entities(
    domain: Optional[str] = None, 
    search_query: Optional[str] = None, 
    limit: int = 100,
    fields: Optional[List[str]] = None,
    detailed: bool = False
) -> List[Dict[str, Any]]:
    """
    Get a list of Home Assistant entities with optional filtering
    
    Args:
        domain: Optional domain to filter by (e.g., 'light', 'switch', 'sensor')
        search_query: Optional search term to filter entities by name, id, or attributes
                     (Note: Does not support wildcards. To get all entities, leave this empty)
        limit: Maximum number of entities to return (default: 100)
        fields: Optional list of specific fields to include in each entity
        detailed: If True, returns all entity fields without filtering
    
    Returns:
        A list of entity dictionaries with lean formatting by default
    
    Examples:
        domain="light" - get all lights
        search_query="kitchen", limit=20 - search entities
        domain="sensor", detailed=True - full sensor details
    
    Best Practices:
        - Use lean format (default) for most operations
        - Prefer domain filtering over no filtering
        - For domain overviews, use domain_summary_tool instead of list_entities
        - Only request detailed=True when necessary for full attribute inspection
        - To get all entity types/domains, use list_entities without a domain filter, 
          then extract domains from entity_ids
    """
    log_message = "Getting entities"
    if domain:
        log_message += f" for domain: {domain}"
    if search_query:
        log_message += f" matching: '{search_query}'"
    if limit != 100:
        log_message += f" (limit: {limit})"
    if detailed:
        log_message += " (detailed format)"
    elif fields:
        log_message += f" (custom fields: {fields})"
    else:
        log_message += " (lean format)"
    
    logger.info(log_message)
    
    # Handle special case where search_query is a wildcard/asterisk - just ignore it
    if search_query == "*":
        search_query = None
        logger.info("Converting '*' search query to None (retrieving all entities)")
    
    # Use the updated get_entities function with field filtering
    return await get_entities(
        domain=domain, 
        search_query=search_query, 
        limit=limit,
        fields=fields,
        lean=not detailed  # Use lean format unless detailed is requested
    )

@mcp.resource("hass://entities")
@async_handler("get_all_entities_resource")
async def get_all_entities_resource() -> str:
    """
    Get a list of all Home Assistant entities as a resource
    
    This endpoint returns a complete list of all entities in Home Assistant, 
    organized by domain. For token efficiency with large installations,
    consider using domain-specific endpoints or the domain summary instead.
    
    Returns:
        A markdown formatted string listing all entities grouped by domain
        
    Examples:
        ```
        # Get all entities
        entities = mcp.get_resource("hass://entities")
        ```
        
    Best Practices:
        - WARNING: This endpoint can return large amounts of data with many entities
        - Prefer domain-filtered endpoints: hass://entities/domain/{domain}
        - For overview information, use domain summaries instead of full entity lists
        - Consider starting with a search if looking for specific entities
    """
    logger.info("Getting all entities as a resource")
    entities = await get_entities(lean=True)
    
    # Check if there was an error
    if isinstance(entities, dict) and "error" in entities:
        return f"Error retrieving entities: {entities['error']}"
    if len(entities) == 1 and isinstance(entities[0], dict) and "error" in entities[0]:
        return f"Error retrieving entities: {entities[0]['error']}"
    
    # Format the entities as a string
    result = "# Home Assistant Entities\n\n"
    result += f"Total entities: {len(entities)}\n\n"
    result += "⚠️ **Note**: For better performance and token efficiency, consider using:\n"
    result += "- Domain filtering: `hass://entities/domain/{domain}`\n"
    result += "- Domain summaries: `hass://entities/domain/{domain}/summary`\n"
    result += "- Entity search: `hass://search/{query}`\n\n"
    
    # Group entities by domain for better organization
    domains = {}
    for entity in entities:
        domain = entity["entity_id"].split(".")[0]
        if domain not in domains:
            domains[domain] = []
        domains[domain].append(entity)
    
    # Build the string with entities grouped by domain
    for domain in sorted(domains.keys()):
        domain_count = len(domains[domain])
        result += f"## {domain.capitalize()} ({domain_count})\n\n"
        for entity in sorted(domains[domain], key=lambda e: e["entity_id"]):
            # Get a friendly name if available
            friendly_name = entity.get("attributes", {}).get("friendly_name", "")
            result += f"- **{entity['entity_id']}**: {entity['state']}"
            if friendly_name and friendly_name != entity["entity_id"]:
                result += f" ({friendly_name})"
            result += "\n"
        result += "\n"
    
    return result

@mcp.tool()
@async_handler("search_entities_tool")
async def search_entities_tool(query: str, limit: int = 20) -> Dict[str, Any]:
    """
    Search for entities matching a query string
    
    Args:
        query: The search query to match against entity IDs, names, and attributes.
              (Note: Does not support wildcards. To get all entities, leave this blank or use list_entities tool)
        limit: Maximum number of results to return (default: 20)
    
    Returns:
        A dictionary containing search results and metadata:
        - count: Total number of matching entities found
        - results: List of matching entities with essential information
        - domains: Map of domains with counts (e.g. {"light": 3, "sensor": 2})
        
    Examples:
        query="temperature" - find temperature entities
        query="living room", limit=10 - find living room entities
        query="", limit=500 - list all entity types
        
    """
    logger.info(f"Searching for entities matching: '{query}' with limit: {limit}")
    
    # Special case - treat "*" as empty query to just return entities without filtering
    if query == "*":
        query = ""
        logger.info("Converting '*' to empty query (retrieving all entities up to limit)")
    
    # Handle empty query as a special case to just return entities up to the limit
    if not query or not query.strip():
        logger.info(f"Empty query - retrieving up to {limit} entities without filtering")
        entities = await get_entities(limit=limit, lean=True)
        
        # Check if there was an error
        if isinstance(entities, dict) and "error" in entities:
            return {"error": entities["error"], "count": 0, "results": [], "domains": {}}
        
        # No query, but we'll return a structured result anyway
        domains_count = {}
        simplified_entities = []
        
        for entity in entities:
            domain = entity["entity_id"].split(".")[0]
            
            # Count domains
            if domain not in domains_count:
                domains_count[domain] = 0
            domains_count[domain] += 1
            
            # Create simplified entity representation
            simplified_entity = {
                "entity_id": entity["entity_id"],
                "state": entity["state"],
                "domain": domain,
                "friendly_name": entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
            }
            
            # Add key attributes based on domain
            attributes = entity.get("attributes", {})
            
            # Include domain-specific important attributes
            if domain == "light" and "brightness" in attributes:
                simplified_entity["brightness"] = attributes["brightness"]
            elif domain == "sensor" and "unit_of_measurement" in attributes:
                simplified_entity["unit"] = attributes["unit_of_measurement"]
            elif domain == "climate" and "temperature" in attributes:
                simplified_entity["temperature"] = attributes["temperature"]
            elif domain == "media_player" and "media_title" in attributes:
                simplified_entity["media_title"] = attributes["media_title"]
            
            simplified_entities.append(simplified_entity)
        
        # Return structured response for empty query
        return {
            "count": len(simplified_entities),
            "results": simplified_entities,
            "domains": domains_count,
            "query": "all entities (no filtering)"
        }
    
    # Normal search with non-empty query
    entities = await get_entities(search_query=query, limit=limit, lean=True)
    
    # Check if there was an error
    if isinstance(entities, dict) and "error" in entities:
        return {"error": entities["error"], "count": 0, "results": [], "domains": {}}
    
    # Prepare the results
    domains_count = {}
    simplified_entities = []
    
    for entity in entities:
        domain = entity["entity_id"].split(".")[0]
        
        # Count domains
        if domain not in domains_count:
            domains_count[domain] = 0
        domains_count[domain] += 1
        
        # Create simplified entity representation
        simplified_entity = {
            "entity_id": entity["entity_id"],
            "state": entity["state"],
            "domain": domain,
            "friendly_name": entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
        }
        
        # Add key attributes based on domain
        attributes = entity.get("attributes", {})
        
        # Include domain-specific important attributes
        if domain == "light" and "brightness" in attributes:
            simplified_entity["brightness"] = attributes["brightness"]
        elif domain == "sensor" and "unit_of_measurement" in attributes:
            simplified_entity["unit"] = attributes["unit_of_measurement"]
        elif domain == "climate" and "temperature" in attributes:
            simplified_entity["temperature"] = attributes["temperature"]
        elif domain == "media_player" and "media_title" in attributes:
            simplified_entity["media_title"] = attributes["media_title"]
        
        simplified_entities.append(simplified_entity)
    
    # Return structured response
    return {
        "count": len(simplified_entities),
        "results": simplified_entities,
        "domains": domains_count,
        "query": query
    }
    
@mcp.resource("hass://search/{query}/{limit}")
@async_handler("search_entities_resource_with_limit")
async def search_entities_resource_with_limit(query: str, limit: str) -> str:
    """
    Search for entities matching a query string with a specified result limit
    
    This endpoint extends the basic search functionality by allowing you to specify
    a custom limit on the number of results returned. It's useful for both broader
    searches (larger limit) and more focused searches (smaller limit).
    
    Args:
        query: The search query to match against entity IDs, names, and attributes
        limit: Maximum number of entities to return (as a string, will be converted to int)
    
    Returns:
        A markdown formatted string with search results and a JSON summary
        
    Examples:
        ```
        # Search with a larger limit (up to 50 results)
        results = mcp.get_resource("hass://search/sensor/50")
        
        # Search with a smaller limit for focused results
        results = mcp.get_resource("hass://search/kitchen/5")
        ```
        
    Best Practices:
        - Use smaller limits (5-10) for focused searches where you need just a few matches
        - Use larger limits (30-50) for broader searches when you need more comprehensive results
        - Balance larger limits against token usage - more results means more tokens
        - Consider domain-specific searches for better precision: "light kitchen" instead of just "kitchen"
    """
    try:
        limit_int = int(limit)
        if limit_int <= 0:
            limit_int = 20
    except ValueError:
        limit_int = 20
        
    logger.info(f"Searching for entities matching: '{query}' with custom limit: {limit_int}")
    
    if not query or not query.strip():
        return "# Entity Search\n\nError: No search query provided"
    
    entities = await get_entities(search_query=query, limit=limit_int, lean=True)
    
    # Check if there was an error
    if isinstance(entities, dict) and "error" in entities:
        return f"# Entity Search\n\nError retrieving entities: {entities['error']}"
    
    # Format the search results
    result = f"# Entity Search Results for '{query}' (Limit: {limit_int})\n\n"
    
    if not entities:
        result += "No entities found matching your search query.\n"
        return result
    
    result += f"Found {len(entities)} matching entities:\n\n"
    
    # Group entities by domain for better organization
    domains = {}
    for entity in entities:
        domain = entity["entity_id"].split(".")[0]
        if domain not in domains:
            domains[domain] = []
        domains[domain].append(entity)
    
    # Build the string with entities grouped by domain
    for domain in sorted(domains.keys()):
        result += f"## {domain.capitalize()}\n\n"
        for entity in sorted(domains[domain], key=lambda e: e["entity_id"]):
            # Get a friendly name if available
            friendly_name = entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
            result += f"- **{entity['entity_id']}**: {entity['state']}"
            if friendly_name != entity["entity_id"]:
                result += f" ({friendly_name})"
            result += "\n"
        result += "\n"
    
    # Add a more structured summary section for easy LLM processing
    result += "## Summary in JSON format\n\n"
    result += "```json\n"
    
    # Create a simplified JSON representation with only essential fields
    simplified_entities = []
    for entity in entities:
        simplified_entity = {
            "entity_id": entity["entity_id"],
            "state": entity["state"],
            "domain": entity["entity_id"].split(".")[0],
            "friendly_name": entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
        }
        
        # Add key attributes based on domain type if they exist
        domain = entity["entity_id"].split(".")[0]
        attributes = entity.get("attributes", {})
        
        # Include domain-specific important attributes
        if domain == "light" and "brightness" in attributes:
            simplified_entity["brightness"] = attributes["brightness"]
        elif domain == "sensor" and "unit_of_measurement" in attributes:
            simplified_entity["unit"] = attributes["unit_of_measurement"]
        elif domain == "climate" and "temperature" in attributes:
            simplified_entity["temperature"] = attributes["temperature"]
        elif domain == "media_player" and "media_title" in attributes:
            simplified_entity["media_title"] = attributes["media_title"]
        
        simplified_entities.append(simplified_entity)
    
    result += json.dumps(simplified_entities, indent=2)
    result += "\n```\n"
    
    return result

# The domain_summary_tool is already implemented, no need to duplicate it

@mcp.tool()
@async_handler("domain_summary")
async def domain_summary_tool(domain: str, example_limit: int = 3) -> Dict[str, Any]:
    """
    Get a summary of entities in a specific domain
    
    Args:
        domain: The domain to summarize (e.g., 'light', 'switch', 'sensor')
        example_limit: Maximum number of examples to include for each state
    
    Returns:
        A dictionary containing:
        - total_count: Number of entities in the domain
        - state_distribution: Count of entities in each state
        - examples: Sample entities for each state
        - common_attributes: Most frequently occurring attributes
        
    Examples:
        domain="light" - get light summary
        domain="climate", example_limit=5 - climate summary with more examples
    Best Practices:
        - Use this before retrieving all entities in a domain to understand what's available    """
    logger.info(f"Getting domain summary for: {domain}")
    return await summarize_domain(domain, example_limit)

@mcp.tool()
@async_handler("system_overview")
async def system_overview() -> Dict[str, Any]:
    """
    Get a comprehensive overview of the entire Home Assistant system
    
    Returns:
        A dictionary containing:
        - total_entities: Total count of all entities
        - domains: Dictionary of domains with their entity counts and state distributions
        - domain_samples: Representative sample entities for each domain (2-3 per domain)
        - domain_attributes: Common attributes for each domain
        - area_distribution: Entities grouped by area (if available)
        
    Examples:
        Returns domain counts, sample entities, and common attributes
    Best Practices:
        - Use this as the first call when exploring an unfamiliar Home Assistant instance
        - Perfect for building context about the structure of the smart home
        - After getting an overview, use domain_summary_tool to dig deeper into specific domains
    """
    logger.info("Generating complete system overview")
    return await get_system_overview()

@mcp.resource("hass://entities/{entity_id}/detailed")
@async_handler("get_entity_resource_detailed")
async def get_entity_resource_detailed(entity_id: str) -> str:
    """
    Get detailed information about a Home Assistant entity as a resource
    
    Use this detailed view selectively when you need to:
    - Understand all available attributes of an entity
    - Debug entity behavior or capabilities
    - See comprehensive state information
    
    For routine operations where you only need basic state information,
    prefer the standard entity endpoint or specify fields in the get_entity tool.
    
    Args:
        entity_id: The entity ID to get information for
    """
    logger.info(f"Getting detailed entity resource: {entity_id}")
    
    # Get all fields, no filtering (detailed view explicitly requests all data)
    state = await get_entity_state(entity_id, use_cache=True, lean=False)
    
    # Check if there was an error
    if "error" in state:
        return f"# Entity: {entity_id}\n\nError retrieving entity: {state['error']}"
    
    # Format the entity as markdown
    result = f"# Entity: {entity_id} (Detailed View)\n\n"
    
    # Get friendly name if available
    friendly_name = state.get("attributes", {}).get("friendly_name")
    if friendly_name and friendly_name != entity_id:
        result += f"**Name**: {friendly_name}\n\n"
    
    # Add state
    result += f"**State**: {state.get('state')}\n\n"
    
    # Add domain and entity type information
    domain = entity_id.split(".")[0]
    result += f"**Domain**: {domain}\n\n"
    
    # Add usage guidance
    result += "## Usage Note\n"
    result += "This is the detailed view showing all entity attributes. For token-efficient interactions, "
    result += "consider using the standard entity endpoint or the get_entity tool with field filtering.\n\n"
    
    # Add all attributes with full details
    attributes = state.get("attributes", {})
    if attributes:
        result += "## Attributes\n\n"
        
        # Sort attributes for better organization
        sorted_attrs = sorted(attributes.items())
        
        # Format each attribute with complete information
        for attr_name, attr_value in sorted_attrs:
            # Format the attribute value
            if isinstance(attr_value, (list, dict)):
                attr_str = json.dumps(attr_value, indent=2)
                result += f"- **{attr_name}**:\n```json\n{attr_str}\n```\n"
            else:
                result += f"- **{attr_name}**: {attr_value}\n"
    
    # Add context data section
    result += "\n## Context Data\n\n"
    
    # Add last updated time if available
    if "last_updated" in state:
        result += f"**Last Updated**: {state['last_updated']}\n"
    
    # Add last changed time if available
    if "last_changed" in state:
        result += f"**Last Changed**: {state['last_changed']}\n"
    
    # Add entity ID and context information
    if "context" in state:
        context = state["context"]
        result += f"**Context ID**: {context.get('id', 'N/A')}\n"
        if "parent_id" in context:
            result += f"**Parent Context**: {context['parent_id']}\n"
        if "user_id" in context:
            result += f"**User ID**: {context['user_id']}\n"
    
    # Add related entities suggestions
    related_domains = []
    if domain == "light":
        related_domains = ["switch", "scene", "automation"]
    elif domain == "sensor":
        related_domains = ["binary_sensor", "input_number", "utility_meter"]
    elif domain == "climate":
        related_domains = ["sensor", "switch", "fan"]
    elif domain == "media_player":
        related_domains = ["remote", "switch", "sensor"]
    
    if related_domains:
        result += "\n## Related Entity Types\n\n"
        result += "You may want to check entities in these related domains:\n"
        for related in related_domains:
            result += f"- {related}\n"
    
    return result

@mcp.resource("hass://entities/domain/{domain}")
@async_handler("list_states_by_domain_resource")
async def list_states_by_domain_resource(domain: str) -> str:
    """
    Get a list of entities for a specific domain as a resource
    
    This endpoint provides all entities of a specific type (domain). It's much more
    token-efficient than retrieving all entities when you only need entities of a 
    specific type.
    
    Args:
        domain: The domain to filter by (e.g., 'light', 'switch', 'sensor')
    
    Returns:
        A markdown formatted string with all entities in the specified domain
        
    Examples:
        ```
        # Get all lights
        lights = mcp.get_resource("hass://entities/domain/light")
        
        # Get all climate devices
        climate = mcp.get_resource("hass://entities/domain/climate")
        
        # Get all sensors
        sensors = mcp.get_resource("hass://entities/domain/sensor")
        ```
        
    Best Practices:
        - Use this endpoint when you need detailed information about all entities of a specific type
        - For a more concise overview, use the domain summary endpoint: hass://entities/domain/{domain}/summary
        - For sensors and other high-count domains, consider using a search to further filter results
    """
    logger.info(f"Getting entities for domain: {domain}")
    
    # Fixed pagination values for now
    page = 1
    page_size = 50
    
    # Get all entities for the specified domain (using lean format for token efficiency)
    entities = await get_entities(domain=domain, lean=True)
    
    # Check if there was an error
    if isinstance(entities, dict) and "error" in entities:
        return f"Error retrieving entities: {entities['error']}"
    
    # Format the entities as a string
    result = f"# {domain.capitalize()} Entities\n\n"
    
    # Pagination info (fixed for now due to MCP limitations)
    total_entities = len(entities)
    
    # List the entities
    for entity in sorted(entities, key=lambda e: e["entity_id"]):
        # Get a friendly name if available
        friendly_name = entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
        result += f"- **{entity['entity_id']}**: {entity['state']}"
        if friendly_name != entity["entity_id"]:
            result += f" ({friendly_name})"
        result += "\n"
    
    # Add link to summary
    result += f"\n## Related Resources\n\n"
    result += f"- [View domain summary](/api/resource/hass://entities/domain/{domain}/summary)\n"
    
    return result

# Automation management MCP tools
@mcp.tool()
@async_handler("list_automations")
async def list_automations() -> List[Dict[str, Any]]:
    """
    Get a list of all automations from Home Assistant
    
    This function retrieves all automations configured in Home Assistant,
    including their IDs, entity IDs, state, and display names.
    
    Returns:
        A list of automation dictionaries, each containing id, entity_id, 
        state, and alias (friendly name) fields.
        
    Examples:
        Returns all automation objects with state and friendly names
    
    """
    logger.info("Getting all automations")
    try:
        # Get automations will now return data from states API, which is more reliable
        automations = await get_automations()
        
        # Handle error responses that might still occur
        if isinstance(automations, dict) and "error" in automations:
            logger.warning(f"Error getting automations: {automations['error']}")
            return []
            
        # Handle case where response is a list with error
        if isinstance(automations, list) and len(automations) == 1 and isinstance(automations[0], dict) and "error" in automations[0]:
            logger.warning(f"Error getting automations: {automations[0]['error']}")
            return []
            
        return automations
    except Exception as e:
        logger.error(f"Error in list_automations: {str(e)}")
        return []

# We already have a list_automations tool, so no need to duplicate functionality

@mcp.tool()
@async_handler("restart_ha")
async def restart_ha() -> Dict[str, Any]:
    """
    Restart Home Assistant
    
    ⚠️ WARNING: Temporarily disrupts all Home Assistant operations
    
    Returns:
        Result of restart operation
    """
    logger.info("Restarting Home Assistant")
    return await restart_home_assistant()

@mcp.tool()
@async_handler("call_service")
async def call_service_tool(domain: str, service: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Call any Home Assistant service (low-level API access)
    
    Args:
        domain: The domain of the service (e.g., 'light', 'switch', 'automation')
        service: The service to call (e.g., 'turn_on', 'turn_off', 'toggle')
        data: Optional data to pass to the service (e.g., {'entity_id': 'light.living_room'})
    
    Returns:
        The response from Home Assistant (usually empty for successful calls)
    
    Examples:
        domain='light', service='turn_on', data={'entity_id': 'light.x', 'brightness': 255}
        domain='automation', service='reload'
        domain='fan', service='set_percentage', data={'entity_id': 'fan.x', 'percentage': 50}
    
    """
    logger.info(f"Calling Home Assistant service: {domain}.{service} with data: {data}")
    return await call_service(domain, service, data or {})

# Prompt functionality
@mcp.prompt()
def create_automation(trigger_type: str, entity_id: str = None):
    """
    Guide a user through creating a Home Assistant automation
    
    This prompt provides a step-by-step guided conversation for creating
    a new automation in Home Assistant based on the specified trigger type.
    
    Args:
        trigger_type: The type of trigger for the automation (state, time, etc.)
        entity_id: Optional entity to use as the trigger source
    
    Returns:
        A list of messages for the interactive conversation
    """
    # Define the initial system message
    system_message = """You are an automation creation assistant for Home Assistant.
You'll guide the user through creating an automation with the following steps:
1. Define the trigger conditions based on their specified trigger type
2. Specify the actions to perform
3. Add any conditions (optional)
4. Review and confirm the automation"""
    
    # Define the first user message based on parameters
    trigger_description = {
        "state": "an entity changing state",
        "time": "a specific time of day",
        "numeric_state": "a numeric value crossing a threshold",
        "zone": "entering or leaving a zone",
        "sun": "sun events (sunrise/sunset)",
        "template": "a template condition becoming true"
    }
    
    description = trigger_description.get(trigger_type, trigger_type)
    
    if entity_id:
        user_message = f"I want to create an automation triggered by {description} for {entity_id}."
    else:
        user_message = f"I want to create an automation triggered by {description}."
    
    # Return the conversation starter messages
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

@mcp.prompt()
def debug_automation(automation_id: str):
    """
    Help a user troubleshoot an automation that isn't working
    
    This prompt guides the user through the process of diagnosing and fixing
    issues with an existing Home Assistant automation.
    
    Args:
        automation_id: The entity ID of the automation to troubleshoot
    
    Returns:
        A list of messages for the interactive conversation
    """
    system_message = """You are a Home Assistant automation troubleshooting expert.
You'll help the user diagnose problems with their automation by checking:
1. Trigger conditions and whether they're being met
2. Conditions that might be preventing execution
3. Action configuration issues
4. Entity availability and connectivity
5. Permissions and scope issues"""
    
    user_message = f"My automation {automation_id} isn't working properly. Can you help me troubleshoot it?"
    
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

@mcp.prompt()
def troubleshoot_entity(entity_id: str):
    """
    Guide a user through troubleshooting issues with an entity
    
    This prompt helps diagnose and resolve problems with a specific
    Home Assistant entity that isn't functioning correctly.
    
    Args:
        entity_id: The entity ID having issues
    
    Returns:
        A list of messages for the interactive conversation
    """
    system_message = """You are a Home Assistant entity troubleshooting expert.
You'll help the user diagnose problems with their entity by checking:
1. Entity status and availability
2. Integration status
3. Device connectivity
4. Recent state changes and error patterns
5. Configuration issues
6. Common problems with this entity type"""
    
    user_message = f"My entity {entity_id} isn't working properly. Can you help me troubleshoot it?"
    
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

@mcp.prompt()
def routine_optimizer():
    """
    Analyze usage patterns and suggest optimized routines based on actual behavior
    
    This prompt helps users analyze their Home Assistant usage patterns and create
    more efficient routines, automations, and schedules based on real usage data.
    
    Returns:
        A list of messages for the interactive conversation
    """
    system_message = """You are a Home Assistant optimization expert specializing in routine analysis.
You'll help the user analyze their usage patterns and create optimized routines by:
1. Reviewing entity state histories to identify patterns
2. Analyzing when lights, climate controls, and other devices are used
3. Finding correlations between different device usages
4. Suggesting automations based on detected routines
5. Optimizing existing automations to better match actual usage
6. Creating schedules that adapt to the user's lifestyle
7. Identifying energy-saving opportunities based on usage patterns"""
    
    user_message = "I'd like to optimize my home automations based on my actual usage patterns. Can you help analyze how I use my smart home and suggest better routines?"
    
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

@mcp.prompt()
def automation_health_check():
    """
    Review all automations, find conflicts, redundancies, or improvement opportunities
    
    This prompt helps users perform a comprehensive review of their Home Assistant
    automations to identify issues, optimize performance, and improve reliability.
    
    Returns:
        A list of messages for the interactive conversation
    """
    system_message = """You are a Home Assistant automation expert specializing in system optimization.
You'll help the user perform a comprehensive audit of their automations by:
1. Reviewing all automations for potential conflicts (e.g., opposing actions)
2. Identifying redundant automations that could be consolidated
3. Finding inefficient trigger patterns that might cause unnecessary processing
4. Detecting missing conditions that could improve reliability
5. Suggesting template optimizations for more efficient processing
6. Uncovering potential race conditions between automations
7. Recommending structural improvements to the automation organization
8. Highlighting best practices and suggesting implementation changes"""
    
    user_message = "I'd like to do a health check on all my Home Assistant automations. Can you help me review them for conflicts, redundancies, and potential improvements?"
    
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

@mcp.prompt()
def entity_naming_consistency():
    """
    Audit entity names and suggest standardization improvements
    
    This prompt helps users analyze their entity naming conventions and create
    a more consistent, organized naming system across their Home Assistant instance.
    
    Returns:
        A list of messages for the interactive conversation
    """
    system_message = """You are a Home Assistant organization expert specializing in entity naming conventions.
You'll help the user audit and improve their entity naming by:
1. Analyzing current entity IDs and friendly names for inconsistencies
2. Identifying patterns in existing naming conventions
3. Suggesting standardized naming schemes based on entity types and locations
4. Creating clear guidelines for future entity naming
5. Proposing specific name changes for entities that don't follow conventions
6. Showing how to implement these changes without breaking automations
7. Explaining benefits of consistent naming for automation and UI organization"""
    
    user_message = "I'd like to make my Home Assistant entity names more consistent and organized. Can you help me audit my current naming conventions and suggest improvements?"
    
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

@mcp.prompt()
def dashboard_layout_generator():
    """
    Create optimized dashboards based on user preferences and usage patterns
    
    This prompt helps users design effective, user-friendly dashboards
    for their Home Assistant instance based on their specific needs.
    
    Returns:
        A list of messages for the interactive conversation
    """
    system_message = """You are a Home Assistant UI design expert specializing in dashboard creation.
You'll help the user create optimized dashboards by:
1. Analyzing which entities they interact with most frequently
2. Identifying logical groupings of entities (by room, function, or use case)
3. Suggesting dashboard layouts with the most important controls prominently placed
4. Creating specialized views for different contexts (mobile, tablet, wall-mounted)
5. Designing intuitive card arrangements that minimize scrolling/clicking
6. Recommending specialized cards and custom components that enhance usability
7. Balancing information density with visual clarity
8. Creating consistent visual patterns that aid in quick recognition"""
    
    user_message = "I'd like to redesign my Home Assistant dashboards to be more functional and user-friendly. Can you help me create optimized layouts based on how I actually use my system?"
    
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

# Documentation endpoint
@mcp.tool()
@async_handler("get_history")
async def get_history(entity_id: str, hours: int = 24) -> Dict[str, Any]:
    """
    Get the history of an entity's state changes
    
    Args:
        entity_id: The entity ID to get history for
        hours: Number of hours of history to retrieve (default: 24)
    
    Returns:
        A dictionary containing:
        - entity_id: The entity ID requested
        - states: List of state objects with timestamps
        - count: Number of state changes found
        - first_changed: Timestamp of earliest state change
        - last_changed: Timestamp of most recent state change
        
    Examples:
        entity_id="light.living_room" - get 24h history
        entity_id="sensor.temperature", hours=168 - get 7 day history
    Best Practices:
        - Keep hours reasonable (24-72) for token efficiency
        - Use for entities with discrete state changes rather than continuously changing sensors
        - Consider the state distribution rather than every individual state    
    """
    logger.info(f"Getting history for entity: {entity_id}, hours: {hours}")
    
    try:
        # Call the new hass function to get history
        history_data = await get_entity_history(entity_id, hours)
        
        # Check for errors from the API call
        if isinstance(history_data, dict) and "error" in history_data:
            return {
                "entity_id": entity_id,
                "error": history_data["error"],
                "states": [],
                "count": 0
            }
        
        # The result from the API is a list of lists of state changes
        # We need to flatten it and process it
        states = []
        if history_data and isinstance(history_data, list):
            for state_list in history_data:
                states.extend(state_list)
        
        if not states:
            return {
                "entity_id": entity_id,
                "states": [],
                "count": 0,
                "first_changed": None,
                "last_changed": None,
                "note": "No state changes found in the specified timeframe."
            }
        
        # Sort states by last_changed timestamp
        states.sort(key=lambda x: x.get("last_changed", ""))
        
        # Extract first and last changed timestamps
        first_changed = states[0].get("last_changed")
        last_changed = states[-1].get("last_changed")
        
        return {
            "entity_id": entity_id,
            "states": states,
            "count": len(states),
            "first_changed": first_changed,
            "last_changed": last_changed
        }
    except Exception as e:
        logger.error(f"Error processing history for {entity_id}: {str(e)}")
        return {
            "entity_id": entity_id,
            "error": f"Error processing history: {str(e)}",
            "states": [],
            "count": 0
        }

@mcp.tool()
@async_handler("get_error_log")
async def get_error_log() -> Dict[str, Any]:
    """
    Get the Home Assistant error log for troubleshooting
    
    Returns:
        A dictionary containing:
        - log_text: The full error log text
        - error_count: Number of ERROR entries found
        - warning_count: Number of WARNING entries found
        - integration_mentions: Map of integration names to mention counts
        - error: Error message if retrieval failed
        
    Examples:
        Returns errors, warnings count and integration mentions
    Best Practices:
        - Use this tool when troubleshooting specific Home Assistant errors
        - Look for patterns in repeated errors
        - Pay attention to timestamps to correlate errors with events
        - Focus on integrations with many mentions in the log    
    """
    logger.info("Getting Home Assistant error log")
    return await get_hass_error_log()
