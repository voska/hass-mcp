"""Pydantic models for the Home Assistant MCP server."""
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, validator


class EmptyParams(BaseModel):
    """Empty parameters model for tools that don't require input."""
    pass


class GetEntityParams(BaseModel):
    """Parameters for retrieving a specific Home Assistant entity."""
    entity_id: str = Field(
        description="The entity ID to retrieve (e.g., 'light.living_room', 'sensor.temperature')"
    )


class ListEntitiesParams(BaseModel):
    """Parameters for filtering entities when listing from Home Assistant."""
    domain: Optional[str] = Field(
        description="Optional domain to filter entities by (e.g., 'light', 'sensor', 'automation')",
        default=None
    )


class SearchEntitiesParams(BaseModel):
    """Parameters for searching Home Assistant entities."""
    query: str = Field(
        description="Search query string (case-insensitive)"
    )
    domain: Optional[str] = Field(
        description="Optional domain to filter entities by (e.g., 'light', 'sensor', 'automation')",
        default=None
    )
    search_attributes: bool = Field(
        description="Whether to search in entity attributes",
        default=True
    )


class CallServiceParams(BaseModel):
    """Parameters for calling a Home Assistant service."""
    domain: str = Field(
        description="The domain of the service to call (e.g., 'light', 'switch', 'automation')"
    )
    service: str = Field(
        description="The service to call (e.g., 'turn_on', 'turn_off', 'toggle')"
    )
    entity_id: Optional[str] = Field(
        description="The entity ID to call the service on (e.g., 'light.living_room')",
        default=None
    )
    service_data: Dict[str, Any] = Field(
        description="Additional data to pass to the service (e.g., brightness, color)",
        default_factory=dict
    )


class GetErrorLogParams(BaseModel):
    """Parameters for retrieving the Home Assistant error log."""
    max_lines: Optional[int] = Field(
        description="Maximum number of lines to return from the log (default: 100)",
        default=100
    )
    
    @validator("max_lines")
    def validate_max_lines(cls, v):
        """Validate the max_lines parameter."""
        if v is not None and v < 1:
            raise ValueError("max_lines must be at least 1")
        if v is not None and v > 1000:
            raise ValueError("max_lines must be at most 1000 to avoid excessive token usage")
        return v


class CreateAutomationParams(BaseModel):
    """Parameters for the automation creation prompt."""
    purpose: str = Field(
        description="The purpose of the automation (e.g., 'Turn on lights when motion is detected')"
    )
    available_entities: Optional[str] = Field(
        description="Optional comma-separated list of entity IDs to use in the automation",
        default=""
    )