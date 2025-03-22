# Hass-MCP

A Model Context Protocol (MCP) server for Home Assistant integration with Claude and other LLMs.

[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](https://github.com/voska/hass-mcp)

## Overview

Hass-MCP enables AI assistants like Claude to interact directly with your Home Assistant instance, allowing them to:

- Query the state of devices and sensors
- Control lights, switches, and other entities
- Get summaries of your smart home
- Troubleshoot automations and entities
- Search for specific entities
- Create guided conversations for common tasks

## Screenshots

<img width="700" alt="Screenshot 2025-03-16 at 15 48 01" src="https://github.com/user-attachments/assets/5f9773b4-6aef-4139-a978-8ec2cc8c0aea" />
<img width="400" alt="Screenshot 2025-03-16 at 15 50 59" src="https://github.com/user-attachments/assets/17e1854a-9399-4e6d-92cf-cf223a93466e" />
<img width="400" alt="Screenshot 2025-03-16 at 15 49 26" src="https://github.com/user-attachments/assets/4565f3cd-7e75-4472-985c-7841e1ad6ba8" />

## Features

- **Entity Management**: Get states, control devices, and search for entities
- **Domain Summaries**: Get high-level information about entity types
- **Automation Support**: List and control automations
- **Guided Conversations**: Use prompts for common tasks like creating automations
- **Smart Search**: Find entities by name, type, or state
- **Token Efficiency**: Lean JSON responses to minimize token usage

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
   docker pull voska/hass-mcp:latest
   ```

2. Add the MCP server to Claude Desktop:

   a. Open Claude Desktop and go to Settings
   b. Navigate to Developer > Edit Config
   c. Add the following configuration to your `claude_desktop_config.json` file:

   ```json
   {
     "mcpServers": {
       "hass-mcp": {
         "command": "docker",
         "args": [
           "run",
           "-i",
           "--rm",
           "-e",
           "HA_URL",
           "-e",
           "HA_TOKEN",
           "voska/hass-mcp"
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

3. The "Hass-MCP" tool should now appear in your Claude Desktop tools menu

> **Note**: If you're running Home Assistant in Docker on the same machine, you may need to add `--network host` to the Docker args for the container to access Home Assistant. Alternatively, use the IP address of your machine instead of `host.docker.internal`.

### Direct Installation with Python

1. Clone this repository:

   ```bash
   git clone https://github.com/yourusername/hass-mcp.git
   cd hass-mcp
   ```

2. Install the server in Claude Desktop:

   ```bash
   uv run mcp install app/server.py -e . -f .env
   ```

3. Create a `.env` file with your Home Assistant connection details:

   ```
   HASS_URL=http://homeassistant.local:8123
   HASS_TOKEN=your_long_lived_access_token_here
   ```

4. Restart Claude Desktop

## Other MCP Clients

### Cursor

1. Go to Cursor Settings > MCP > Add New MCP Server
2. Fill in the form:
   - Name: `Hass-MCP`
   - Type: `command`
   - Command:
     ```
     docker run -i --rm -e HA_URL=http://homeassistant.local:8123 -e HA_TOKEN=YOUR_LONG_LIVED_TOKEN voska/hass-mcp
     ```
   - Replace `YOUR_LONG_LIVED_TOKEN` with your actual Home Assistant token
   - Update the HA_URL to match your Home Assistant instance address
3. Click "Add" to save

### Claude Code (CLI)

To use with Claude Code CLI, you can add the MCP server directly using the `mcp add` command:

**Using Docker (recommended):**

```bash
claude mcp add hass-mcp -e HA_URL=http://homeassistant.local:8123 -e HA_TOKEN=YOUR_LONG_LIVED_TOKEN -- docker run -i --rm -e HA_URL -e HA_TOKEN voska/hass-mcp
```

Replace `YOUR_LONG_LIVED_TOKEN` with your actual Home Assistant token and update the HA_URL to match your Home Assistant instance address.

## Usage Examples

Here are some examples of prompts you can use with Claude once Hass-MCP is set up:

- "What's the current state of my living room lights?"
- "List all my sensors that contain temperature data"
- "Give me a summary of my climate entities"
- "Create an automation that turns on the lights at sunset"
- "Help me troubleshoot why my bedroom motion sensor automation isn't working"
- "Search for entities related to my living room"

## Available Tools

Hass-MCP provides the following tools for interacting with Home Assistant:

- `get_hass_version`: Get the Home Assistant version
- `get_entity`: Get detailed information about a specific entity
- `list_automations`: List all automations configured in Home Assistant
- `list_entities`: List all entities, optionally filtered by domain
- `search_entities`: Search for entities by name, state, or attributes
- `get_system_overview`: Get a comprehensive overview of the entire Home Assistant system
- `call_service`: Call any Home Assistant service (turn on lights, toggle switches, etc.)
- `get_error_log`: Retrieve the Home Assistant error log with optional line limit

## Available Prompts for Guided Conversations

Hass-MCP includes the following prompts for guided conversations:

- `create_automation`: Interactive guide for creating custom Home Assistant automations with YAML examples

## Planned Prompts

Future versions of Hass-MCP will include additional prompts:

- `debug_automation`: Troubleshooting help for automations that aren't working
- `troubleshoot_entity`: Diagnose issues with entities
- And more!

## Planned Resources

Future versions of Hass-MCP will provide resource endpoints:

- `hass://entities/{entity_id}`: Get the state of a specific entity
- `hass://entities`: List all Home Assistant entities
- And more!

## Development

### Running Tests

```bash
uv run pytest tests/
```

## Changelog

### v0.2.0 WIP

- **Complete rewrite** of the entire codebase for better stability and performance
- Migrated to the official `homeassistant_api` Python package for backend connectivity
- Fixed numerous bugs from v0.1.0 related to connection management and data handling
- Added MCP prompt support using best practices from the specification
- Enhanced token efficiency for all API responses
- Significantly improved system overview and entity search capabilities
- Added proper logging and error management

### v0.1.0

- Initial proof-of-concept release
- Basic Home Assistant integration with limited functionality
- Preliminary tools for entity access

## License

[MIT License](LICENSE)
