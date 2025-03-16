# Hass-MCP

A Model Context Protocol (MCP) server for Home Assistant integration with Claude and other LLMs.

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

- Python 3.13+
- Home Assistant instance with Long-Lived Access Token
- [uv](https://github.com/astral-sh/uv)

### Installation Steps

1. Clone the repository:

   ```bash
   git clone https://github.com/voska/hass-mcp.git
   cd hass-mcp
   ```

2. Create a virtual environment and install dependencies:

   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e .
   ```

3. Create a `.env` file with your Home Assistant credentials:
   ```bash
   cp .env.example .env
   ```

## Setting Up With Claude Tools

### Claude Desktop

1. Install the server in Claude Desktop:

   ```bash
   uv run mcp install app/server.py -e . -f .env
   ```

2. Open Claude Desktop and you should see "Hass-MCP" in the available tools dropdown.

### Cursor

1. Go to Cursor Settings > Features > MCP
2. Click "+ Add New MCP Server"
3. Fill in the form:
   - Enter server name "Hass-MCP"
   - Select type "command"
   - For command, enter the full path to Python and the server script:
     ```
     uv run --with mcp[cli] mcp run /PATH/TO/hass-mcp/app/server.py
     ```
   - Add environment variables for HA_URL and HA_TOKEN

### Claude Code (CLI)

To use with Claude Code CLI, you can add the MCP server directly using the `mcp add` command:

```bash
claude mcp add hass-mcp -e HA_URL=http://your-home-assistant-url:8123 -e HA_TOKEN=your_token -- uv run --with mcp[cli] mcp run /PATH/TO/hass-mcp/app/server.py
```

## Usage Examples

Here are some examples of prompts you can use with Claude once Hass-MCP is set up:

- "What's the current state of my living room lights?"
- "Turn off all the lights in the kitchen"
- "List all my sensors that contain temperature data"
- "Give me a summary of my climate entities"
- "Create an automation that turns on the lights at sunset"
- "Help me troubleshoot why my bedroom motion sensor automation isn't working"
- "Search for entities related to my living room"

## Available Tools

Hass-MCP provides several tools for interacting with Home Assistant:

- `get_version`: Get the Home Assistant version
- `get_entity`: Get the state of a specific entity
- `entity_action`: Perform actions on entities (turn on, off, toggle)
- `list_entities`: Get a list of entities with optional filtering
- `search_entities_tool`: Search for entities matching a query
- `domain_summary`: Get a summary of a domain's entities
- `list_automations`: Get a list of all automations
- `call_service`: Call any Home Assistant service
- `restart_ha`: Restart Home Assistant
- `get_history`: Get the state history of an entity
- `get_error_log`: Get the Home Assistant error log
- `get_docs`: Get documentation about available tools and resources

## Prompts for Guided Conversations

Hass-MCP includes several prompts for guided conversations:

- `create_automation`: Guide for creating Home Assistant automations
- `debug_automation`: Troubleshooting help for automations that aren't working
- `troubleshoot_entity`: Diagnose issues with entities

## Development

### Running Tests

```bash
uv run pytest tests/
```

## License

[MIT License](LICENSE)
