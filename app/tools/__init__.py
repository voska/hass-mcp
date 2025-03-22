"""Home Assistant tools for the MCP server."""

from .entity import get_entity, list_entities, list_automations
from .system import get_hass_version, get_system_overview, get_error_log
from .service import call_service
from .search import search_entities

__all__ = [
    'get_entity',
    'list_entities',
    'list_automations',
    'get_hass_version',
    'get_system_overview',
    'call_service',
    'search_entities',
    'get_error_log',
]