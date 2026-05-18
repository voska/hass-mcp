# Hass-MCP

A Model Context Protocol (MCP) server for Home Assistant integration with Claude and other LLMs.

<a href="https://glama.ai/mcp/servers/@voska/hass-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@voska/hass-mcp/badge" alt="Hass-MCP MCP server" />
</a>

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

### uv/uvx

1. Install uv on your system.

2. Add the MCP server to Claude Desktop:

   a. Open Claude Desktop and go to Settings
   b. Navigate to Developer > Edit Config
   c. Add the following configuration to your `claude_desktop_config.json` file:

   ```json
   {
     "mcpServers": {
       "hass-mcp": {
         "command": "uvx",
         "args": ["hass-mcp"],
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

## HTTP Transport (Streamable)

For deployments that can't use stdio — running behind an MCP gateway, hosting on Smithery, sharing one server across multiple clients, or connecting from network-based tools like LibreChat or OpenWebUI — Hass-MCP supports the MCP [streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports). The server runs in stateless mode (no `Mcp-Session-Id`, JSON responses), suitable for horizontally-scaled hosts.

> [!CAUTION]
> **HTTP mode exposes full Home Assistant control over the network.** Anyone who can reach the port can call any tool — turn off lights, unlock doors, trigger automations, restart HA. The MCP spec does not yet ship a built-in auth layer in this server. Until it does, you **must** put it behind one of:
>
> - A reverse proxy (nginx, Caddy, Traefik) doing basic-auth or bearer-token validation
> - A VPN or zero-trust network (Tailscale, WireGuard, Cloudflare Access)
> - Localhost binding only (the default — change `--host` only if you know what you're doing)
>
> Do not expose `:8000` to the open internet without auth.

### Running locally

**Using uvx:**

```bash
HA_URL=http://homeassistant.local:8123 \
HA_TOKEN=YOUR_LONG_LIVED_TOKEN \
uvx hass-mcp --http --port 8000
```

The server binds `127.0.0.1` by default. Override with `--host 0.0.0.0` only when you've also configured auth in front of it.

### Running in Docker

```bash
docker run --rm -p 8000:8000 \
  -e HA_URL=http://homeassistant.local:8123 \
  -e HA_TOKEN=YOUR_LONG_LIVED_TOKEN \
  voska/hass-mcp:latest --http --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is required inside Docker so the port is reachable through the bridge. Bind the publish (`-p`) to `127.0.0.1:8000:8000` if you only want it reachable from the host, or put a reverse proxy in front.

### Endpoint

The MCP endpoint is at `/mcp`. Point your client at `http://<host>:<port>/mcp`.

### Smithery / PaaS

The server honors the `PORT` environment variable (Smithery's convention) in addition to `MCP_PORT`. Smithery deployment requires `--http` mode and reads `PORT` automatically.

## Custom / private CA

If your Home Assistant instance serves a certificate signed by your own CA (step-ca, smallstep, homelab OpenSSL), hass-mcp can verify it without disabling TLS:

- **Locally**: install the CA root in your OS trust store (macOS Keychain, Windows Cert Store, or `update-ca-certificates` on Linux). hass-mcp picks it up automatically via [truststore](https://truststore.readthedocs.io/).
- **In Docker** (or any sandboxed runtime): bind-mount the CA file and point `SSL_CERT_FILE` at it.

```bash
docker run --rm \
  -v /path/to/your-ca.crt:/etc/ssl/certs/your-ca.crt:ro \
  -e SSL_CERT_FILE=/etc/ssl/certs/your-ca.crt \
  -e HA_URL=https://homeassistant.example.internal:8123 \
  -e HA_TOKEN=YOUR_LONG_LIVED_TOKEN \
  voska/hass-mcp:latest
```

`SSL_CERT_FILE` always takes precedence over the OS store when set. `verify=False` is intentionally not supported — use `HA_URL=http://...` if you genuinely want unencrypted local LAN traffic.

## Usage Examples

Here are some examples of prompts you can use with Claude once Hass-MCP is set up:

- "What's the current state of my living room lights?"
- "Turn off all the lights in the kitchen"
- "What's the temperature in the master bedroom?"
- "List everything in the guest room"
- "List all my sensors that contain temperature data"
- "Give me a summary of my climate entities"
- "Create an automation that turns on the lights at sunset"
- "Help me troubleshoot why my bedroom motion sensor automation isn't working"
- "Search for entities related to my living room"
- "Show me the last 50 ERROR lines from the Home Assistant log"
- "What's been failing on the mqtt integration today?"
- "Show me power usage by day for the last month"
- "What happened with the front door sensor last Tuesday?"

## Available Tools

Hass-MCP provides several tools for interacting with Home Assistant:

- `get_version`: Get the Home Assistant version
- `get_entity`: Get the state of a specific entity with optional field filtering
- `entity_action`: Perform actions on entities (turn on, off, toggle)
- `list_entities`: Get a list of entities with optional domain filtering and search
- `search_entities_tool`: Search for entities matching a query
- `domain_summary_tool`: Get a summary of a domain's entities
- `list_automations`: Get a list of all automations
- `call_service_tool`: Call any Home Assistant service
- `restart_ha`: Restart Home Assistant
- `get_history`: Get the state history of an entity (last N hours)
- `get_history_range`: Get state-change history for an entity over an
  explicit date/time range (`start_time` / `end_time`, ISO-8601)
- `get_statistics`: Get long-term aggregated statistics (mean / min / max
  per bucket) for an entity over the last N hours — works for data older
  than the recorder's short-term retention window
- `get_statistics_range`: Same, but for an explicit date/time range —
  useful for monthly / yearly trend queries
- `get_error_log`: Get the Home Assistant error log, with optional
  `level` / `integration` / `search_term` / `lines` filters applied
  server-side so noisy logs don't blow Claude's context
- `get_entities_by_area`: List entities in a specific area / room

## Prompts for Guided Conversations

Hass-MCP includes several prompts for guided conversations:

- `create_automation`: Guide for creating Home Assistant automations based on trigger type
- `debug_automation`: Troubleshooting help for automations that aren't working
- `troubleshoot_entity`: Diagnose issues with entities
- `routine_optimizer`: Analyze usage patterns and suggest optimized routines based on actual behavior
- `automation_health_check`: Review all automations, find conflicts, redundancies, or improvement opportunities
- `entity_naming_consistency`: Audit entity names and suggest standardization improvements
- `dashboard_layout_generator`: Create optimized dashboards based on user preferences and usage patterns

## Available Resources

Hass-MCP provides the following resource endpoints:

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