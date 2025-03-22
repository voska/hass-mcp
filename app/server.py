"""Home Assistant MCP server implementation."""
import asyncio
import logging
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool, Prompt, PromptArgument

from app.hass_client import HassClient
from app.models import (
    EmptyParams, 
    GetEntityParams, 
    ListEntitiesParams, 
    CallServiceParams,
    SearchEntitiesParams,
    GetErrorLogParams,
    CreateAutomationParams
)
from app.tools import (
    get_hass_version, 
    get_entity, 
    list_automations, 
    list_entities,
    get_system_overview,
    call_service,
    search_entities,
    get_error_log
)
from app.prompts.automation import get_automation_prompt

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def serve() -> None:
    """Run the Home Assistant MCP server."""
    # Create server instance
    server = Server("hass-mcp")
    
    # Set up Home Assistant connection
    client = HassClient()
    
    # Verify connection
    try:
        await client.verify_connection()
    except Exception:
        return
    
    try:
        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="get_hass_version",
                    description="Get the Home Assistant version",
                    inputSchema=EmptyParams.model_json_schema()
                ),
                Tool(
                    name="get_entity",
                    description="Get a specific entity from Home Assistant",
                    inputSchema=GetEntityParams.model_json_schema()
                ),
                Tool(
                    name="list_automations",
                    description="List all automations in Home Assistant",
                    inputSchema=EmptyParams.model_json_schema()
                ),
                Tool(
                    name="list_entities",
                    description="List all entities in Home Assistant, optionally filtered by domain",
                    inputSchema=ListEntitiesParams.model_json_schema()
                ),
                Tool(
                    name="search_entities",
                    description="Search for entities by name, state, or attributes with optional domain filtering",
                    inputSchema=SearchEntitiesParams.model_json_schema()
                ),
                Tool(
                    name="get_system_overview",
                    description="Get a comprehensive overview of the entire Home Assistant system",
                    inputSchema=EmptyParams.model_json_schema()
                ),
                Tool(
                    name="call_service",
                    description="Call any Home Assistant service (e.g., turn on a light, toggle a switch)",
                    inputSchema=CallServiceParams.model_json_schema()
                ),
                Tool(
                    name="get_error_log",
                    description="Get the Home Assistant error log with optional line limit",
                    inputSchema=GetErrorLogParams.model_json_schema()
                ),
            ]

        @server.list_prompts()
        async def list_prompts() -> list[Prompt]:
            """List available prompts for the Home Assistant MCP server."""
            return [
                Prompt(
                    name="create_automation",
                    description="Interactive guide for creating custom Home Assistant automations with YAML examples",
                    arguments=[
                        PromptArgument(
                            name="purpose",
                            description="The purpose of the automation (e.g., 'Turn on lights when motion is detected')",
                            required=True,
                        ),
                        PromptArgument(
                            name="available_entities",
                            description="Optional comma-separated list of entity IDs to use in the automation",
                            required=False,
                        ),
                    ],
                )
            ]
            
        @server.get_prompt()
        async def get_prompt(name: str, arguments: dict | None) -> any:
            """Get a prompt with specified arguments."""
            if arguments is None:
                arguments = {}
            
            # Handle different prompt types    
            if name == "create_automation":
                try:
                    return await get_automation_prompt(arguments)
                except Exception as e:
                    logger.error(f"Error generating automation prompt: {e}")
                    raise
            
            # Unknown prompt
            logger.error(f"Unknown prompt requested: {name}")
            raise ValueError(f"Unknown prompt: {name}")

        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            if name == "get_hass_version":
                # No parameters needed
                version = await get_hass_version(client)
                return [TextContent(type="text", text=version)]
            elif name == "get_entity":
                # Parse and validate parameters
                params = GetEntityParams(**arguments)
                entity_data = await get_entity(client, params.entity_id)
                return [TextContent(type="text", text=entity_data)]
            elif name == "list_automations":
                # No parameters needed
                automations = await list_automations(client)
                return [TextContent(type="text", text=automations)]
            elif name == "list_entities":
                # Parse and validate parameters
                params = ListEntitiesParams(**arguments)
                entities = await list_entities(client, params.domain)
                return [TextContent(type="text", text=entities)]
            elif name == "search_entities":
                # Parse and validate parameters
                params = SearchEntitiesParams(**arguments)
                results = await search_entities(
                    client, 
                    params.query, 
                    params.domain, 
                    params.search_attributes
                )
                return [TextContent(type="text", text=results)]
            elif name == "get_system_overview":
                # No parameters needed
                overview = await get_system_overview(client)
                return [TextContent(type="text", text=overview)]
            elif name == "call_service":
                # Parse and validate parameters
                params = CallServiceParams(**arguments)
                service_result = await call_service(
                    client, 
                    params.domain, 
                    params.service, 
                    params.entity_id, 
                    params.service_data
                )
                return [TextContent(type="text", text=service_result)]
            elif name == "get_error_log":
                # Parse and validate parameters
                params = GetErrorLogParams(**arguments)
                log_result = await get_error_log(client, params.max_lines)
                return [TextContent(type="text", text=log_result)]
            
            raise ValueError(f"Unknown tool: {name}")

        # Run server
        options = server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, options, raise_exceptions=True)
    finally:
        # Clean up client resources
        await client.close()


def main():
    """Run the Home Assistant MCP server."""
    # Use asyncio.run with proper cleanup options
    asyncio.run(serve(), debug=True)


if __name__ == "__main__":
    # Load .env file for local development
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        try:
            # Only import dotenv when running directly
            from dotenv import load_dotenv
            load_dotenv(env_path)
            logger.info(f"Loaded environment variables from {env_path}")
        except ImportError:
            logger.warning("python-dotenv not installed, skipping .env loading.")
    
    main()
