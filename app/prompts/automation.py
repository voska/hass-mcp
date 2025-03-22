"""Automation creation prompts for Home Assistant."""
from typing import Any, Dict, Optional

from mcp.shared.exceptions import McpError
from mcp.types import (
    ErrorData,
    GetPromptResult,
    PromptMessage,
    TextContent,
)

from app.models import CreateAutomationParams


async def get_automation_prompt(
    arguments: Dict[str, Any]
) -> GetPromptResult:
    """Generate the automation creation prompt based on provided arguments.
    
    Args:
        arguments: Dictionary containing the prompt arguments.
            - purpose: The purpose of the automation (required).
            - available_entities: Optional comma-separated list of entity IDs.
    
    Returns:
        A GetPromptResult object containing the formatted prompt.
        
    Raises:
        McpError: If the required parameters are missing or invalid.
    """
    # Validate arguments using our model
    try:
        # Use the Pydantic model for validation
        params = CreateAutomationParams(**arguments)
        purpose = params.purpose
        available_entities = params.available_entities or ""
    except Exception as e:
        # Convert validation errors to McpError
        raise McpError(ErrorData(
            code=-32602,  # Invalid params error code
            message=f"Invalid parameters: {str(e)}"
        ))
    
    entity_text = ""
    if available_entities:
        entity_text = f"\n\nThe following entities are available to use in this automation:\n{available_entities}"
    
    prompt_text = f"""I'll help you create a Home Assistant automation for: {purpose}.

Here's a systematic approach to creating an effective Home Assistant automation:

## 1. Define the Trigger
What should start the automation? Options include:
- State change (entity enters a specific state)
- Numeric state (sensor crosses a threshold)
- Time-based (specific time or sunset/sunrise)
- Zone event (device enters or leaves a zone)
- MQTT message
- Pattern match (entity state matches pattern)

## 2. Add Conditions (Optional)
What conditions must be true for the automation to execute? Examples:
- Time condition (only during certain hours)
- State condition (another entity has a specific state)
- Numeric condition (sensor value in range)
- Zone condition (device in a specific zone)
- Template condition (custom logic)

## 3. Define Actions
What should happen when the automation triggers? Options include:
- Call a service (turn on lights, adjust thermostat, etc.)
- Set scene 
- Fire an event
- Notify (mobile, TTS, etc.)
- Delay
- Run script
- Choose between actions based on conditions

## 4. YAML Structure
The automation can be defined in YAML like this:

```yaml
automation:
  - id: unique_id_for_this_automation
    alias: Human Readable Name
    description: Optional detailed description
    
    # TRIGGER SECTION
    trigger:
      - platform: [trigger_type]
        # Trigger-specific configuration
        
    # CONDITIONS SECTION (OPTIONAL)
    condition:
      - condition: [condition_type]
        # Condition-specific configuration
        
    # ACTIONS SECTION
    action:
      - service: domain.service
        # Service-specific data
        
    # OPTIONAL SETTINGS  
    mode: single  # or restart, queued, parallel
    max: 10  # maximum number of runs
```{entity_text}

Let me know what specific trigger, conditions, and actions you'd like to use, and I'll help you create the YAML configuration for this automation."""

    # Create a more specific description based on the purpose
    description = f"YAML automation template for: {purpose}"
    if available_entities:
        description += f" (with {len(available_entities.split(','))} available entities)"
        
    return GetPromptResult(
        description=description,
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=prompt_text),
            )
        ],
    )