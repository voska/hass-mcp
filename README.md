# Hass-MCP-Plus

An enhanced Model Context Protocol (MCP) server for Home Assistant integration with Claude and other LLMs, built on [voska/hass-mcp](https://github.com/voska/hass-mcp). Thanks to [Matt Voska](https://github.com/voska) for creating the original project.

**What's new in Plus:**
- Automation trace debugging (list and inspect execution traces)
- Enhanced historical data tools (statistics with date ranges)
- Improved token efficiency for LLM context management
- WebSocket API for error log retrieval

## Overview

Hass-MCP-Plus enables AI assistants like Claude to interact directly with your Home Assistant instance, allowing them to:

- Query the state of devices and sensors
- Control lights, switches, and other entities
- Get summaries of your smart home
- Troubleshoot automations and entities
- Search for specific entities
- Create guided conversations for common tasks

## Features

- **Entity Management**: Get states, control devices, and search for entities
- **Domain Summaries**: Get high-level information about entity types
- **Automation Support**: List automations and debug with execution traces
- **Historical Data**: Query statistics and history with date range support
- **Guided Conversations**: Use prompts for common tasks like creating automations
- **Smart Search**: Find entities by name, type, or state
- **Token Efficiency**: Lean JSON responses to minimize context usage

## Installation

### Prerequisites

- Home Assistant instance with Long-Lived Access Token
- One of the following:
  - Docker (recommended)
  - Python 3.13+ and [uv](https://github.com/astral-sh/uv)

## Setting Up With Claude Desktop

### Docker Installation (Recommended)

1. Pull the Docker image:

   ```bash
   docker pull rmaher001/hass-mcp-plus:latest
   ```

2. Add the MCP server to Claude Desktop:

   a. Open Claude Desktop and go to Settings
   b. Navigate to Developer > Edit Config
   c. Add the following configuration to your `claude_desktop_config.json` file:

   ```json
   {
     "mcpServers": {
       "hass-mcp-plus": {
         "command": "docker",
         "args": [
           "run",
           "-i",
           "--rm",
           "-e",
           "HA_URL",
           "-e",
           "HA_TOKEN",
           "rmaher001/hass-mcp-plus"
         ],
         "env": {
           "HA_URL": "http://homeassistant.local:8123",
           "HA_TOKEN": "YOUR_LONG_LIVED_TOKEN"
         }
       }
     }
   }
   ```

   d. Replace `YOUR_LONG_LIVED_TOKEN` with your actual Home Assistant long-lived access token
   e. Update the `HA_URL`:

   - If running Home Assistant on the same machine: use `http://host.docker.internal:8123` (Docker Desktop on Mac/Windows)
   - If running Home Assistant on another machine: use the actual IP or hostname

   f. Save the file and restart Claude Desktop

3. The "Hass-MCP-Plus" tool should now appear in your Claude Desktop tools menu

> **Note**: If you're running Home Assistant in Docker on the same machine, you may need to add `--network host` to the Docker args for the container to access Home Assistant. Alternatively, use the IP address of your machine instead of `host.docker.internal`.

### uv/uvx

1. Install uv on your system.

2. Add the MCP server to Claude Desktop:

   a. Open Claude Desktop and go to Settings
   b. Navigate to Developer > Edit Config
   c. Add the following configuration to your `claude_desktop_config.json` file:

   ```json
   {
     "mcpServers": {
       "hass-mcp-plus": {
         "command": "uvx",
         "args": ["hass-mcp-plus"],
         "env": {
           "HA_URL": "http://homeassistant.local:8123",
           "HA_TOKEN": "YOUR_LONG_LIVED_TOKEN"
         }
       }
     }
   }
   ```

   d. Replace `YOUR_LONG_LIVED_TOKEN` with your actual Home Assistant long-lived access token
   e. Update the `HA_URL`:

   - If running Home Assistant on the same machine: use `http://host.docker.internal:8123` (Docker Desktop on Mac/Windows)
   - If running Home Assistant on another machine: use the actual IP or hostname

   f. Save the file and restart Claude Desktop

3. The "Hass-MCP-Plus" tool should now appear in your Claude Desktop tools menu

## Other MCP Clients

### Cursor

1. Go to Cursor Settings > MCP > Add New MCP Server
2. Fill in the form:
   - Name: `Hass-MCP-Plus`
   - Type: `command`
   - Command:
     ```
     docker run -i --rm -e HA_URL=http://homeassistant.local:8123 -e HA_TOKEN=YOUR_LONG_LIVED_TOKEN rmaher001/hass-mcp-plus
     ```
   - Replace `YOUR_LONG_LIVED_TOKEN` with your actual Home Assistant token
   - Update the HA_URL to match your Home Assistant instance address
3. Click "Add" to save

### Claude Code (CLI)

To use with Claude Code CLI, you can add the MCP server directly using the `mcp add` command:

**Using Docker (recommended):**

```bash
claude mcp add hass-mcp-plus -e HA_URL=http://homeassistant.local:8123 -e HA_TOKEN=YOUR_LONG_LIVED_TOKEN -- docker run -i --rm -e HA_URL -e HA_TOKEN rmaher001/hass-mcp-plus
```

Replace `YOUR_LONG_LIVED_TOKEN` with your actual Home Assistant token and update the HA_URL to match your Home Assistant instance address.

## Usage Examples

Here are some examples of prompts you can use with Claude once Hass-MCP-Plus is set up:

- "What's the current state of my living room lights?"
- "Turn off all the lights in the kitchen"
- "List all my sensors that contain temperature data"
- "Give me a summary of my climate entities"
- "Create an automation that turns on the lights at sunset"
- "Help me troubleshoot why my bedroom motion sensor automation isn't working"
- "Search for entities related to my living room"

## Available Tools

Hass-MCP-Plus provides several tools for interacting with Home Assistant:

### Entity Management
- `get_entity`: Get the state of a specific entity with optional field filtering
- `entity_action`: Perform actions on entities (turn on, off, toggle)
- `list_entities`: Get a list of entities with optional domain filtering and search
- `search_entities_tool`: Search for entities matching a query
- `domain_summary_tool`: Get a summary of a domain's entities
- `system_overview`: Get a comprehensive overview of the entire Home Assistant system

### Automation & Debugging
- `list_automations`: Get a list of all automations
- `list_automation_traces`: Get recent execution traces for a specific automation
- `get_automation_trace`: Get detailed trace for a specific automation run
- `get_error_log`: Get the Home Assistant error log

### Historical Data
- `get_history`: Get raw state history of an entity
- `get_history_range`: Get state history for a specific date/time range
- `get_statistics`: Get aggregated statistics (mean, min, max) for an entity
- `get_statistics_range`: Get statistics for a specific date/time range

### System
- `get_version`: Get the Home Assistant version
- `call_service_tool`: Call any Home Assistant service
- `restart_ha`: Restart Home Assistant

## Prompts for Guided Conversations

Hass-MCP-Plus includes several prompts for guided conversations:

- `create_automation`: Guide for creating Home Assistant automations based on trigger type
- `debug_automation`: Troubleshooting help for automations that aren't working
- `troubleshoot_entity`: Diagnose issues with entities
- `routine_optimizer`: Analyze usage patterns and suggest optimized routines based on actual behavior
- `automation_health_check`: Review all automations, find conflicts, redundancies, or improvement opportunities
- `entity_naming_consistency`: Audit entity names and suggest standardization improvements
- `dashboard_layout_generator`: Create optimized dashboards based on user preferences and usage patterns

## Available Resources

Hass-MCP-Plus provides the following resource endpoints:

- `hass://entities/{entity_id}`: Get the state of a specific entity
- `hass://entities/{entity_id}/detailed`: Get detailed information about an entity with all attributes
- `hass://entities`: List all Home Assistant entities grouped by domain
- `hass://entities/domain/{domain}`: Get a list of entities for a specific domain
- `hass://search/{query}/{limit}`: Search for entities matching a query with custom result limit

## Development

### Running Tests

```bash
uv run pytest tests/
```

## License

[MIT License](LICENSE)