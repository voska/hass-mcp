import httpx
from typing import Dict, Any, Optional, List, TypeVar, Callable, Awaitable, Union, cast
import functools
import inspect
import logging
import os
import ssl
from datetime import datetime, timedelta, timezone

import truststore

from app.areas import get_area, get_all_areas
from app.config import HA_URL, HA_TOKEN, get_ha_headers

# Set up logging
logger = logging.getLogger(__name__)

# Define a generic type for our API function return values
T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Awaitable[Any]])

# HTTP client
_client: Optional[httpx.AsyncClient] = None

# Default field sets for different verbosity levels
# Lean fields for standard requests (optimized for token efficiency)
DEFAULT_LEAN_FIELDS = ["entity_id", "state", "area", "attr.friendly_name"]

# Common fields that are typically needed for entity operations
DEFAULT_STANDARD_FIELDS = ["entity_id", "state", "attributes", "last_updated"]

# Domain-specific important attributes to include in lean responses
DOMAIN_IMPORTANT_ATTRIBUTES = {
    "light": ["brightness", "color_temp", "rgb_color", "supported_color_modes"],
    "switch": ["device_class"],
    "binary_sensor": ["device_class"],
    "sensor": ["device_class", "unit_of_measurement", "state_class"],
    "climate": ["hvac_mode", "current_temperature", "temperature", "hvac_action"],
    "media_player": ["media_title", "media_artist", "source", "volume_level"],
    "cover": ["current_position", "current_tilt_position"],
    "fan": ["percentage", "preset_mode"],
    "camera": ["entity_picture"],
    "automation": ["last_triggered"],
    "scene": [],
    "script": ["last_triggered"],
}

def handle_api_errors(func: F) -> F:
    """
    Decorator to handle common error cases for Home Assistant API calls
    
    Args:
        func: The async function to decorate
        
    Returns:
        Wrapped function that handles errors
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Determine return type from function annotation
        return_type = inspect.signature(func).return_annotation
        is_dict_return = 'Dict' in str(return_type)
        is_list_return = 'List' in str(return_type)
        
        # Prepare error formatters based on return type
        def format_error(msg: str) -> Any:
            if is_dict_return:
                return {"error": msg}
            elif is_list_return:
                return [{"error": msg}]
            else:
                return msg
        
        try:
            # Check if token is available
            if not HA_TOKEN:
                return format_error("No Home Assistant token provided. Please set HA_TOKEN in .env file.")
            
            # Call the original function
            return await func(*args, **kwargs)
        except httpx.ConnectError:
            return format_error(f"Connection error: Cannot connect to Home Assistant at {HA_URL}")
        except httpx.TimeoutException:
            return format_error(f"Timeout error: Home Assistant at {HA_URL} did not respond in time")
        except httpx.HTTPStatusError as e:
            return format_error(f"HTTP error: {e.response.status_code} - {e.response.reason_phrase}")
        except httpx.RequestError as e:
            return format_error(f"Error connecting to Home Assistant: {str(e)}")
        except Exception as e:
            return format_error(f"Unexpected error: {str(e)}")
    
    return cast(F, wrapper)

def _build_ssl_context() -> ssl.SSLContext:
    """Build the TLS verification context.

    Layered so users running an in-house CA (e.g. step-ca, smallstep) can
    connect to a properly-signed HA instance on any platform / deployment
    mode without weakening verification:

    1. If `SSL_CERT_FILE` is set, use it. This is the OpenSSL standard env
       var, honored by every modern tool. It's the primary mechanism for
       Docker (bind-mount the CA, set the env var) and explicit overrides.
    2. Otherwise use truststore, which bridges to the OS-native trust store
       (macOS Keychain, Windows Cert Store, Linux ca-certificates). Users
       who installed their CA at the OS level get it for free.

    No REQUESTS_CA_BUNDLE shim — that's a requests-ism, not a standard.
    No verify=False fallback — silent downgrade is worse than a hard failure.
    """
    cert_file = os.environ.get("SSL_CERT_FILE")
    if cert_file:
        logger.debug("TLS: using SSL_CERT_FILE=%s", cert_file)
        return ssl.create_default_context(cafile=cert_file)
    logger.debug("TLS: using OS native trust store via truststore")
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


# Persistent HTTP client
async def get_client() -> httpx.AsyncClient:
    """Get a persistent httpx client for Home Assistant API calls"""
    global _client
    if _client is None:
        logger.debug("Creating new HTTP client")
        _client = httpx.AsyncClient(timeout=10.0, verify=_build_ssl_context())
    return _client

async def cleanup_client() -> None:
    """Close the HTTP client when shutting down"""
    global _client
    if _client:
        logger.debug("Closing HTTP client")
        await _client.aclose()
        _client = None

# Direct entity retrieval function
async def get_all_entity_states() -> Dict[str, Dict[str, Any]]:
    """Fetch all entity states from Home Assistant"""
    client = await get_client()
    response = await client.get(f"{HA_URL}/api/states", headers=get_ha_headers())
    response.raise_for_status()
    entities = response.json()
    
    # Create a mapping for easier access
    return {entity["entity_id"]: entity for entity in entities}

def filter_fields(data: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
    """
    Filter entity data to only include requested fields
    
    This function helps reduce token usage by returning only requested fields.
    
    Args:
        data: The complete entity data dictionary
        fields: List of fields to include in the result
               - "state": Include the entity state
               - "attributes": Include all attributes
               - "attr.X": Include only attribute X (e.g. "attr.brightness")
               - "context": Include context data
               - "last_updated"/"last_changed": Include timestamp fields
    
    Returns:
        A filtered dictionary with only the requested fields
    """
    if not fields:
        return data
        
    result = {"entity_id": data["entity_id"]}
    
    for field in fields:
        if field == "state":
            result["state"] = data.get("state")
        elif field == "area":
            # Area is injected by hass-mcp from the HA area registry; absent
            # in the raw /api/states payload but added before filtering.
            result["area"] = data.get("area")
        elif field == "attributes":
            result["attributes"] = data.get("attributes", {})
        elif field.startswith("attr.") and len(field) > 5:
            attr_name = field[5:]
            attributes = data.get("attributes", {})
            if attr_name in attributes:
                if "attributes" not in result:
                    result["attributes"] = {}
                result["attributes"][attr_name] = attributes[attr_name]
        elif field == "context":
            if "context" in data:
                result["context"] = data["context"]
        elif field in ["last_updated", "last_changed"]:
            if field in data:
                result[field] = data[field]
    
    return result

# API Functions
@handle_api_errors
async def get_hass_version() -> str:
    """Get the Home Assistant version from the API"""
    client = await get_client()
    response = await client.get(f"{HA_URL}/api/config", headers=get_ha_headers())
    response.raise_for_status()
    data = response.json()
    return data.get("version", "unknown")

@handle_api_errors
async def get_entity_state(
    entity_id: str,
    fields: Optional[List[str]] = None,
    lean: bool = False
) -> Dict[str, Any]:
    """
    Get the state of a Home Assistant entity
    
    Args:
        entity_id: The entity ID to get
        fields: Optional list of specific fields to include in the response
        lean: If True, returns a token-efficient version with minimal fields
              (overridden by fields parameter if provided)
    
    Returns:
        Entity state dictionary, optionally filtered to include only specified fields
    """
    # Fetch directly
    client = await get_client()
    response = await client.get(
        f"{HA_URL}/api/states/{entity_id}",
        headers=get_ha_headers()
    )
    response.raise_for_status()
    entity_data = response.json()

    # Enrich with area data from the HA area registry (HA's REST states
    # endpoint omits this; we resolve it via /api/template — see app/areas.py).
    entity_data["area"] = await get_area(client, entity_id)

    # Apply field filtering if requested
    if fields:
        # User-specified fields take precedence
        return filter_fields(entity_data, fields)
    elif lean:
        # Build domain-specific lean fields
        lean_fields = DEFAULT_LEAN_FIELDS.copy()
        
        # Add domain-specific important attributes
        domain = entity_id.split('.')[0]
        if domain in DOMAIN_IMPORTANT_ATTRIBUTES:
            for attr in DOMAIN_IMPORTANT_ATTRIBUTES[domain]:
                lean_fields.append(f"attr.{attr}")
        
        return filter_fields(entity_data, lean_fields)
    else:
        # Return full entity data
        return entity_data

@handle_api_errors
async def get_entities(
    domain: Optional[str] = None, 
    search_query: Optional[str] = None, 
    limit: int = 100,
    fields: Optional[List[str]] = None,
    lean: bool = True
) -> List[Dict[str, Any]]:
    """
    Get a list of all entities from Home Assistant with optional filtering and search
    
    Args:
        domain: Optional domain to filter entities by (e.g., 'light', 'switch')
        search_query: Optional case-insensitive search term to filter by entity_id, friendly_name or other attributes
        limit: Maximum number of entities to return (default: 100)
        fields: Optional list of specific fields to include in each entity
        lean: If True (default), returns token-efficient versions with minimal fields
    
    Returns:
        List of entity dictionaries, optionally filtered by domain and search terms,
        and optionally limited to specific fields
    """
    # Get all entities directly
    client = await get_client()
    response = await client.get(f"{HA_URL}/api/states", headers=get_ha_headers())
    response.raise_for_status()
    entities = response.json()

    # Enrich each entity with area data. One bulk template call covers
    # the whole list regardless of size.
    areas = await get_all_areas(client)
    for entity in entities:
        entity["area"] = areas.get(entity["entity_id"])

    # Filter by domain if specified
    if domain:
        entities = [entity for entity in entities if entity["entity_id"].startswith(f"{domain}.")]
    
    # Search if query is provided
    if search_query and search_query.strip():
        search_term = search_query.lower().strip()
        filtered_entities = []
        
        for entity in entities:
            # Search in entity_id
            if search_term in entity["entity_id"].lower():
                filtered_entities.append(entity)
                continue
                
            # Search in friendly_name
            friendly_name = entity.get("attributes", {}).get("friendly_name", "").lower()
            if friendly_name and search_term in friendly_name:
                filtered_entities.append(entity)
                continue
                
            # Search in other common attributes (state, area_id, etc.)
            if search_term in entity.get("state", "").lower():
                filtered_entities.append(entity)
                continue
                
            # Search in other attributes
            for attr_name, attr_value in entity.get("attributes", {}).items():
                # Check if attribute value can be converted to string
                if isinstance(attr_value, (str, int, float, bool)):
                    if search_term in str(attr_value).lower():
                        filtered_entities.append(entity)
                        break
        
        entities = filtered_entities
    
    # Apply the limit
    if limit > 0 and len(entities) > limit:
        entities = entities[:limit]
    
    # Apply field filtering if requested
    if fields:
        # Use explicit field list when provided
        return [filter_fields(entity, fields) for entity in entities]
    elif lean:
        # Apply domain-specific lean fields to each entity
        result = []
        for entity in entities:
            # Get the entity's domain
            entity_domain = entity["entity_id"].split('.')[0]
            
            # Start with basic lean fields
            lean_fields = DEFAULT_LEAN_FIELDS.copy()
            
            # Add domain-specific important attributes
            if entity_domain in DOMAIN_IMPORTANT_ATTRIBUTES:
                for attr in DOMAIN_IMPORTANT_ATTRIBUTES[entity_domain]:
                    lean_fields.append(f"attr.{attr}")
            
            # Filter and add to result
            result.append(filter_fields(entity, lean_fields))
        
        return result
    else:
        # Return full entities
        return entities

@handle_api_errors
async def call_service(domain: str, service: str, data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Call a Home Assistant service.

    Returns:
        List of affected entity states (may be empty for services like reload).
    """
    if data is None:
        data = {}
    
    client = await get_client()
    response = await client.post(
        f"{HA_URL}/api/services/{domain}/{service}", 
        headers=get_ha_headers(),
        json=data
    )
    response.raise_for_status()
    
    # Invalidate cache after service calls as they might change entity states
    global _entities_timestamp
    _entities_timestamp = 0
    
    return response.json()

@handle_api_errors
async def summarize_domain(domain: str, example_limit: int = 3) -> Dict[str, Any]:
    """
    Generate a summary of entities in a domain
    
    Args:
        domain: The domain to summarize (e.g., 'light', 'switch')
        example_limit: Maximum number of examples to include for each state
        
    Returns:
        Dictionary with summary information
    """
    entities = await get_entities(domain=domain)
    
    # Check if we got an error response
    if isinstance(entities, dict) and "error" in entities:
        return entities  # Just pass through the error
    
    try:
        # Initialize summary data
        total_count = len(entities)
        state_counts = {}
        state_examples = {}
        attributes_summary = {}
        
        # Process entities to build the summary
        for entity in entities:
            state = entity.get("state", "unknown")
            
            # Count states
            if state not in state_counts:
                state_counts[state] = 0
                state_examples[state] = []
            state_counts[state] += 1
            
            # Add examples (up to the limit)
            if len(state_examples[state]) < example_limit:
                example = {
                    "entity_id": entity["entity_id"],
                    "friendly_name": entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
                }
                state_examples[state].append(example)
            
            # Collect attribute keys for summary
            for attr_key in entity.get("attributes", {}):
                if attr_key not in attributes_summary:
                    attributes_summary[attr_key] = 0
                attributes_summary[attr_key] += 1
        
        # Create the summary
        summary = {
            "domain": domain,
            "total_count": total_count,
            "state_distribution": state_counts,
            "examples": state_examples,
            "common_attributes": sorted(
                [(k, v) for k, v in attributes_summary.items()], 
                key=lambda x: x[1], 
                reverse=True
            )[:10]  # Top 10 most common attributes
        }
        
        return summary
    except Exception as e:
        return {"error": f"Error generating domain summary: {str(e)}"}

@handle_api_errors
async def get_automations() -> List[Dict[str, Any]]:
    """Get a list of all automations from Home Assistant"""
    # Reuse the get_entities function with domain filtering
    automation_entities = await get_entities(domain="automation")
    
    # Check if we got an error response
    if isinstance(automation_entities, dict) and "error" in automation_entities:
        return automation_entities  # Just pass through the error
    
    # Process automation entities
    result = []
    try:
        for entity in automation_entities:
            # Extract relevant information
            automation_info = {
                "id": entity["entity_id"].split(".")[1],
                "entity_id": entity["entity_id"],
                "state": entity["state"],
                "alias": entity["attributes"].get("friendly_name", entity["entity_id"]),
            }
            
            # Add any additional attributes that might be useful
            if "last_triggered" in entity["attributes"]:
                automation_info["last_triggered"] = entity["attributes"]["last_triggered"]
            
            result.append(automation_info)
    except (TypeError, KeyError) as e:
        # Handle errors in processing the entities
        return {"error": f"Error processing automation entities: {str(e)}"}
        
    return result

@handle_api_errors
async def reload_automations() -> Dict[str, Any]:
    """Reload all automations in Home Assistant"""
    return await call_service("automation", "reload", {})

@handle_api_errors
async def restart_home_assistant() -> Dict[str, Any]:
    """Restart Home Assistant"""
    return await call_service("homeassistant", "restart", {})

@handle_api_errors
async def get_hass_error_log(
    level: Optional[str] = None,
    integration: Optional[str] = None,
    search_term: Optional[str] = None,
    lines: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get the Home Assistant error log for troubleshooting.

    All filters are optional and combine (AND semantics). Filtering happens
    client-side after the full log is fetched from HA; stats (counts,
    integration mentions, total_lines) are computed over the filtered text
    so they match what's returned.

    Args:
        level: Filter to lines containing this log level (ERROR, WARNING,
               INFO, DEBUG). Case-insensitive.
        integration: Filter to lines mentioning this integration. Matches
                     `[name]` or `[homeassistant.components.name]`.
                     Case-insensitive.
        search_term: Case-insensitive substring filter applied to each line.
        lines: Return only the most recent N lines (after other filters).

    Returns:
        A dictionary containing:
        - log_text: The filtered log text (ANSI codes stripped)
        - error_count: ERROR entries in the filtered text
        - warning_count: WARNING entries in the filtered text
        - integration_mentions: Map of integration names to counts
        - total_lines: Total lines returned
        - filters_applied: Echo of which filters were active
        - error: Set only on retrieval failure
    """
    import re

    ansi_pattern = re.compile(r'\x1b\[[0-9;]*m')

    def apply_filters(text: str) -> str:
        log_lines = text.splitlines()
        if level:
            needle = level.upper()
            log_lines = [ln for ln in log_lines if needle in ln]
        if integration:
            needle = integration.lower()
            bare = f"[{needle}]"
            namespaced = f"[homeassistant.components.{needle}]"
            log_lines = [ln for ln in log_lines if bare in ln.lower() or namespaced in ln.lower()]
        if search_term:
            needle = search_term.lower()
            log_lines = [ln for ln in log_lines if needle in ln.lower()]
        if lines is not None and lines > 0:
            log_lines = log_lines[-lines:]
        return "\n".join(log_lines)

    def parse_log_text(log_text: str) -> Dict[str, Any]:
        # HA OS logs include ANSI color codes that distort ERROR/WARNING counts
        # and contaminate the returned text.
        clean_text = ansi_pattern.sub('', log_text)
        # Filtering happens after ANSI stripping so substring matches aren't
        # disrupted by escape sequences.
        filtered = apply_filters(clean_text)

        error_count = filtered.count("ERROR")
        warning_count = filtered.count("WARNING")

        integration_mentions: Dict[str, int] = {}
        for match in re.finditer(r'\[([a-zA-Z0-9_\.]+)\]', filtered):
            name = match.group(1).lower()
            # Collapse homeassistant.components.X to X
            if name.startswith('homeassistant.components.'):
                name = name.split('.')[-1]
            integration_mentions[name] = integration_mentions.get(name, 0) + 1

        filters_applied = {
            k: v for k, v in {
                "level": level, "integration": integration,
                "search_term": search_term, "lines": lines,
            }.items() if v is not None
        }

        return {
            "log_text": filtered,
            "error_count": error_count,
            "warning_count": warning_count,
            "integration_mentions": integration_mentions,
            "total_lines": len(filtered.splitlines()) if filtered else 0,
            "filters_applied": filters_applied,
        }

    try:
        headers = get_ha_headers()

        async with httpx.AsyncClient() as client:
            # HA OS / Supervised — the most common deployment — exposes Core
            # logs at /api/hassio/core/logs. /api/error_log returns 404 there.
            hassio_url = f"{HA_URL}/api/hassio/core/logs"
            response = await client.get(hassio_url, headers=headers, timeout=30)

            if response.status_code == 200:
                return parse_log_text(response.text)

            # Fall back to standalone Home Assistant.
            standalone_url = f"{HA_URL}/api/error_log"
            response = await client.get(standalone_url, headers=headers, timeout=30)

            if response.status_code == 200:
                return parse_log_text(response.text)

            return {
                "error": f"Error retrieving error log: {response.status_code} {response.reason_phrase}",
                "details": "Neither /api/hassio/core/logs nor /api/error_log are available",
                "log_text": "",
                "error_count": 0,
                "warning_count": 0,
                "integration_mentions": {},
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

@handle_api_errors
async def get_entity_history(entity_id: str, hours: int) -> List[Dict[str, Any]]:
    """
    Get the history of an entity's state changes from Home Assistant.

    Args:
        entity_id: The entity ID to get history for.
        hours: Number of hours of history to retrieve.

    Returns:
        A list of state change objects, or an error dictionary.
    """
    client = await get_client()
    
    # Calculate the end time for the history lookup
    end_time = datetime.now(timezone.utc)
    end_time_iso = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Calculate the start time for the history lookup based on end_time
    start_time = end_time - timedelta(hours=hours)
    start_time_iso = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Construct the API URL
    url = f"{HA_URL}/api/history/period/{start_time_iso}"
    
    # Set query parameters
    params = {
        "filter_entity_id": entity_id,
        "minimal_response": "true",
        "end_time": end_time_iso,
    }
    
    # Make the API call
    response = await client.get(url, headers=get_ha_headers(), params=params)
    response.raise_for_status()
    
    # Return the JSON response
    return response.json()

@handle_api_errors
async def get_system_overview() -> Dict[str, Any]:
    """
    Get a comprehensive overview of the entire Home Assistant system
    
    Returns:
        A dictionary containing:
        - total_entities: Total count of all entities
        - domains: Dictionary of domains with their entity counts and state distributions
        - domain_samples: Representative sample entities for each domain (2-3 per domain)
        - domain_attributes: Common attributes for each domain
        - area_distribution: Entities grouped by area (if available)
    """
    try:
        # Get ALL entities with minimal fields for efficiency
        # We retrieve all entities since API calls don't consume tokens, only responses do
        client = await get_client()
        response = await client.get(f"{HA_URL}/api/states", headers=get_ha_headers())
        response.raise_for_status()
        all_entities_raw = response.json()

        # Resolve areas in one bulk template call.
        areas = await get_all_areas(client)

        # Apply lean formatting to reduce token usage in the response
        all_entities = []
        for entity in all_entities_raw:
            entity["area"] = areas.get(entity["entity_id"])
            domain = entity["entity_id"].split(".")[0]

            # Start with basic lean fields
            lean_fields = ["entity_id", "state", "area", "attr.friendly_name"]

            # Add domain-specific important attributes
            if domain in DOMAIN_IMPORTANT_ATTRIBUTES:
                for attr in DOMAIN_IMPORTANT_ATTRIBUTES[domain]:
                    lean_fields.append(f"attr.{attr}")

            # Filter and add to result
            all_entities.append(filter_fields(entity, lean_fields))
        
        # Initialize overview structure
        overview = {
            "total_entities": len(all_entities),
            "domains": {},
            "domain_samples": {},
            "domain_attributes": {},
            "area_distribution": {}
        }
        
        # Group entities by domain
        domain_entities = {}
        for entity in all_entities:
            domain = entity["entity_id"].split(".")[0]
            if domain not in domain_entities:
                domain_entities[domain] = []
            domain_entities[domain].append(entity)
        
        # Process each domain
        for domain, entities in domain_entities.items():
            # Count entities in this domain
            count = len(entities)
            
            # Collect state distribution
            state_distribution = {}
            for entity in entities:
                state = entity.get("state", "unknown")
                if state not in state_distribution:
                    state_distribution[state] = 0
                state_distribution[state] += 1
            
            # Store domain information
            overview["domains"][domain] = {
                "count": count,
                "states": state_distribution
            }
            
            # Select representative samples (2-3 per domain)
            sample_limit = min(3, count)
            samples = []
            for i in range(sample_limit):
                entity = entities[i]
                samples.append({
                    "entity_id": entity["entity_id"],
                    "state": entity.get("state", "unknown"),
                    "friendly_name": entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
                })
            overview["domain_samples"][domain] = samples
            
            # Collect common attributes for this domain
            attribute_counts = {}
            for entity in entities:
                for attr in entity.get("attributes", {}):
                    if attr not in attribute_counts:
                        attribute_counts[attr] = 0
                    attribute_counts[attr] += 1
            
            # Get top 5 most common attributes for this domain
            common_attributes = sorted(attribute_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            overview["domain_attributes"][domain] = [attr for attr, count in common_attributes]
            
            # Group by area. Entities without an area land under "Unassigned"
            # rather than the misleading "Unknown" the previous implementation
            # produced (it was reading area from attributes, which HA does
            # not populate — see Issue #28).
            for entity in entities:
                area_name = entity.get("area") or "Unassigned"

                if area_name not in overview["area_distribution"]:
                    overview["area_distribution"][area_name] = {}

                if domain not in overview["area_distribution"][area_name]:
                    overview["area_distribution"][area_name][domain] = 0

                overview["area_distribution"][area_name][domain] += 1
        
        # Add summary information
        overview["domain_count"] = len(domain_entities)
        overview["most_common_domains"] = sorted(
            [(domain, len(entities)) for domain, entities in domain_entities.items()],
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return overview
    except Exception as e:
        logger.error(f"Error generating system overview: {str(e)}")
        return {"error": f"Error generating system overview: {str(e)}"}
