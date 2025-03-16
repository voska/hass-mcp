import asyncio
import functools
import logging
import inspect
import traceback
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

# Now we can import from the app package
from app.config import HA_URL, HA_TOKEN
from app.hass import (
    get_hass_version, get_entity_state, call_service, get_entities,
    get_automations, restart_home_assistant,
    cleanup_client, filter_fields, summarize_domain
)

# Type variable for generic functions
T = TypeVar('T')

# Create an MCP server
from mcp.server.fastmcp import FastMCP, Context, Image
import mcp.types as types
mcp = FastMCP("Hass-MCP", capabilities={
    "resources": {},
    "tools": {},
    "prompts": {}
})

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
    
    Returns the version number of the connected Home Assistant instance.
    Useful for compatibility checks or informational displays.
    
    Returns:
        A string with the Home Assistant version (e.g., "2025.3.0")
    
    Example:
        ```python
        version = await get_version()
        # Returns: "2025.3.0"
        ```
    """
    logger.info("Getting Home Assistant version")
    return await get_hass_version()




@mcp.tool()
@async_handler("get_entity")
async def get_entity(entity_id: str, fields: Optional[List[str]] = None, detailed: bool = False) -> dict:
    """
    Get the state of a Home Assistant entity with optional field filtering
    
    This function provides token-efficient entity information. By default, it returns
    a lean JSON structure with only essential fields. For detailed inspection, set
    detailed=True or specify exactly which fields you need.
    
    Args:
        entity_id: The entity ID to get (e.g. 'light.living_room')
        fields: Optional list of fields to include in response 
                (e.g. ['state', 'attributes', 'attr.brightness'])
        detailed: If True, returns all entity fields without filtering
                
    Examples:
        Basic state check: 
          get_entity("light.living_room") - returns lean format with key fields
          
        Control operation: 
          get_entity("light.living_room", fields=["state", "attr.brightness", "attr.supported_features"])
          
        Full details: 
          get_entity("light.living_room", detailed=True) - returns everything
          
        Specific attribute: 
          get_entity("sensor.temperature", fields=["attr.device_class", "attr.unit_of_measurement"])
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
async def entity_action(entity_id: str, action: str, **params) -> dict:
    """
    Perform an action on a Home Assistant entity
    
    This is the primary method for controlling Home Assistant entities. It supports
    common operations (on, off, toggle) across all entity types, with domain-specific
    parameters passed as keyword arguments.
    
    Args:
        entity_id: The entity ID to control (e.g. 'light.living_room')
        action: The action to perform ('on', 'off', 'toggle')
        **params: Additional parameters for the service call
    
    Returns:
        The response from Home Assistant
    
    Examples:
        ```python
        # Turn on a light with brightness
        result = await entity_action("light.living_room", "on", brightness=255)
        
        # Turn off a switch
        result = await entity_action("switch.garden_lights", "off")
        
        # Toggle a light with transition
        result = await entity_action("light.bedroom", "toggle", transition=2)
        
        # Turn on a climate entity with target temperature
        result = await entity_action("climate.living_room", "on", temperature=22.5)
        ```
    
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
    data = {"entity_id": entity_id, **params}
    
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
    Get a list of all Home Assistant entities with optional domain filtering and search
    
    This function provides a flexible way to retrieve entities. By default, it returns
    token-efficient lean JSON structures. For token efficiency:
    - Always use domain filtering when you know the entity type
    - Use search_query for fuzzy matching instead of retrieving all entities
    - Use a reasonable limit (20-50) for most queries
    - Keep the default lean format unless you need specific fields
    
    Args:
        domain: Optional domain to filter by (e.g., 'light', 'switch', 'sensor')
        search_query: Optional search term to filter entities by name, id, or attributes
        limit: Maximum number of entities to return (default: 100)
        fields: Optional list of specific fields to include in each entity
        detailed: If True, returns all entity fields without filtering
    
    Returns:
        A list of entity dictionaries with lean formatting by default
    
    Examples:
        ```python
        # Get all lights (lean format)
        lights = await list_entities(domain="light")
        
        # Search for entities with specific fields
        kitchen_devices = await list_entities(
            search_query="kitchen", 
            limit=20,
            fields=["state", "attr.friendly_name"]
        )
        
        # Get detailed entities (all fields)
        detailed_sensors = await list_entities(
            domain="sensor", 
            search_query="temperature",
            detailed=True
        )
        ```
    
    Best Practices:
        - Use lean format (default) for most operations to reduce token usage
        - Prefer domain filtering over no filtering (1-2 orders of magnitude fewer tokens)
        - For domain overviews, use domain_summary_tool instead of list_entities
        - Only request detailed=True when necessary for full attribute inspection
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
    
    This tool provides a flexible way to find entities by matching against
    entity IDs, friendly names, states, and attribute values. It returns a structured,
    token-efficient response with grouped results for easy processing.
    
    Args:
        query: The search query to match against entity IDs, names, and attributes
        limit: Maximum number of results to return (default: 20)
    
    Returns:
        A dictionary containing search results and metadata:
        - count: Total number of matching entities found
        - results: List of matching entities with essential information
        - domains: Map of domains with counts (e.g. {"light": 3, "sensor": 2})
        
    Examples:
        ```python
        # Search for temperature-related entities
        results = await search_entities_tool("temperature")
        
        # Search for entities in the living room with a limit of 10
        results = await search_entities_tool("living room", limit=10)
        
        # Access results
        for entity in results["results"]:
            print(f"{entity['entity_id']}: {entity['state']}")
        ```
        
    Best Practices:
        - Use specific search terms to reduce result count
        - For exact entity_id matches, use get_entity instead of search
        - For domain-specific searches, include the domain in the query
        - Use a reasonable limit (10-20) for most searches to reduce token usage
    """
    logger.info(f"Searching for entities matching: '{query}' with limit: {limit}")
    
    if not query or not query.strip():
        return {"error": "No search query provided", "count": 0, "results": [], "domains": {}}
    
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
    
    This function provides a token-efficient overview of all entities in a specific domain.
    It's ideal for understanding what's available without retrieving full entity details.
    
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
        ```python
        # Get summary of lights
        light_summary = await domain_summary_tool("light")
        # Number of lights: light_summary['total_count']
        # Lights that are on: light_summary['state_distribution'].get('on', 0)
        
        # Get climate devices with more examples
        climate_summary = await domain_summary_tool("climate", example_limit=5)
        
        # Get sensor summary
        sensor_summary = await domain_summary_tool("sensor")
        # Most common sensor attributes: sensor_summary['common_attributes']
        ```
    
    Best Practices:
        - Use this before retrieving all entities in a domain to understand what's available
        - Great for reporting on home status (e.g., "5 lights are on, 12 are off")
        - 10-100x more token-efficient than retrieving all entities
    """
    logger.info(f"Getting domain summary for: {domain}")
    return await summarize_domain(domain, example_limit)

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
        ```python
        # Get all automations
        automations = await list_automations()
        
        # Find a specific automation by name
        morning_routine = next(
            (a for a in await list_automations() 
             if "morning" in a.get("alias", "").lower()),
            None
        )
        ```
    
    Best Practices:
        - Automations are less numerous than entities, so retrieving all at once is usually efficient
        - Use entity_action with automation domain to trigger specific automations
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
    
    Initiates a restart of the Home Assistant server. This is useful when you've made
    configuration changes that require a restart to take effect.
    
    ⚠️ WARNING: This will temporarily disrupt Home Assistant operations and may
    disconnect clients. Use sparingly and only when absolutely necessary.
    
    Returns:
        A dictionary with the result of the restart operation
        
    Example:
        ```python
        # Restart Home Assistant
        result = await restart_ha()
        # Home Assistant is now restarting, it may take several seconds to complete
        ```
    """
    logger.info("Restarting Home Assistant")
    return await restart_home_assistant()


@mcp.tool()
@async_handler("call_service")
async def call_service_tool(domain: str, service: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Call any Home Assistant service
    
    This is a low-level tool for calling any service not covered by the more specific
    entity_action tool. It provides direct access to Home Assistant's service API.
    
    Args:
        domain: The domain of the service (e.g., 'light', 'switch', 'automation')
        service: The service to call (e.g., 'turn_on', 'turn_off', 'toggle')
        data: Optional data to pass to the service (e.g., {'entity_id': 'light.living_room'})
    
    Returns:
        The response from Home Assistant (usually empty for successful calls)
    
    Examples:
        ```python
        # Call a light service with specific parameters
        result = await call_service('light', 'turn_on', {
            'entity_id': 'light.living_room', 
            'brightness': 255
        })
        
        # Reload automations
        result = await call_service('automation', 'reload', {})
        
        # Toggle a switch
        result = await call_service('switch', 'toggle', {
            'entity_id': 'switch.garden_lights'
        })
        
        # Set fan speed
        result = await call_service('fan', 'set_percentage', {
            'entity_id': 'fan.bedroom',
            'percentage': 50
        })
        ```
    
    Best Practices:
        - For simple on/off/toggle operations, prefer entity_action over call_service
        - For entity control, always include 'entity_id' in the data parameter
        - Check entity attributes (via get_entity) before calling services to ensure 
          the entity supports the service and parameters you're using
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

# Documentation endpoint
@mcp.tool()
@async_handler("get_history")
async def get_history(entity_id: str, hours: int = 24) -> Dict[str, Any]:
    """
    Get the history of an entity's state changes
    
    This tool provides the state change history for a specific entity over a
    specified time period. It's useful for analyzing patterns, troubleshooting,
    and understanding how an entity's state changes over time.
    
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
        ```python
        # Get last 24 hours of history for a light
        history = await get_history("light.living_room")
        
        # Get last 7 days of history for a sensor
        history = await get_history("sensor.temperature", hours=168)
        ```
        
    Best Practices:
        - Keep hours reasonable (24-72) for token efficiency
        - Use for entities with discrete state changes rather than continuously changing sensors
        - Consider the state distribution rather than every individual state
    """
    logger.info(f"Getting history for entity: {entity_id}, hours: {hours}")
    
    try:
        # Get current state to ensure entity exists
        current = await get_entity_state(entity_id, detailed=True)
        if isinstance(current, dict) and "error" in current:
            return {
                "entity_id": entity_id,
                "error": current["error"],
                "states": [],
                "count": 0
            }
        
        # For now, this is a stub that returns minimal dummy data
        # In a real implementation, this would call the Home Assistant history API
        now = current.get("last_updated", "2023-03-15T12:00:00.000Z")
        
        # Create a dummy history (would be replaced with real API call)
        states = [
            {
                "state": current.get("state", "unknown"),
                "last_changed": now,
                "attributes": current.get("attributes", {})
            }
        ]
        
        # Add a note about this being placeholder data
        return {
            "entity_id": entity_id,
            "states": states,
            "count": len(states),
            "first_changed": now,
            "last_changed": now,
            "note": "This is placeholder data. Future versions will include real historical data."
        }
    except Exception as e:
        logger.error(f"Error retrieving history for {entity_id}: {str(e)}")
        return {
            "entity_id": entity_id,
            "error": f"Error retrieving history: {str(e)}",
            "states": [],
            "count": 0
        }

@mcp.tool()
@async_handler("get_error_log")
async def get_error_log() -> Dict[str, Any]:
    """
    Get the Home Assistant error log
    
    This tool provides direct access to the Home Assistant error log,
    which is useful for troubleshooting issues with Home Assistant itself.
    The log contains errors, warnings, and other important messages that
    can help identify problems with components, integrations, or automations.
    
    Returns:
        A dictionary containing:
        - log_text: The full error log text
        - error_count: Number of ERROR entries found
        - warning_count: Number of WARNING entries found
        - integration_mentions: Map of integration names to mention counts
        - error: Error message if retrieval failed
        
    Examples:
        ```python
        # Get the error log and count errors
        log_data = await get_error_log()
        print(f"Found {log_data['error_count']} errors and {log_data['warning_count']} warnings")
        
        # Look for specific integration issues
        for integration, count in log_data['integration_mentions'].items():
            if count > 5:  # Many mentions might indicate problems
                print(f"Integration {integration} mentioned {count} times")
        ```
        
    Best Practices:
        - Use this tool when troubleshooting specific Home Assistant errors
        - Look for patterns in repeated errors
        - Pay attention to timestamps to correlate errors with events
        - Focus on integrations with many mentions in the log
    """
    logger.info("Getting Home Assistant error log")
    
    try:
        # Call the Home Assistant API error_log endpoint
        url = f"{HA_URL}/api/error_log"
        headers = {
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                log_text = response.text
                
                # Count errors and warnings
                error_count = log_text.count("ERROR")
                warning_count = log_text.count("WARNING")
                
                # Extract integration mentions
                import re
                integration_mentions = {}
                
                # Look for patterns like [mqtt], [zwave], etc.
                for match in re.finditer(r'\[([a-zA-Z0-9_]+)\]', log_text):
                    integration = match.group(1).lower()
                    if integration not in integration_mentions:
                        integration_mentions[integration] = 0
                    integration_mentions[integration] += 1
                
                return {
                    "log_text": log_text,
                    "error_count": error_count,
                    "warning_count": warning_count,
                    "integration_mentions": integration_mentions
                }
            else:
                return {
                    "error": f"Error retrieving error log: {response.status_code} {response.reason_phrase}",
                    "details": response.text,
                    "log_text": "",
                    "error_count": 0,
                    "warning_count": 0,
                    "integration_mentions": {}
                }
    except Exception as e:
        logger.error(f"Error retrieving Home Assistant error log: {str(e)}")
        return {
            "error": f"Error retrieving error log: {str(e)}",
            "log_text": "",
            "error_count": 0,
            "warning_count": 0,
            "integration_mentions": {}
        }
