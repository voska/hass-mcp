# Security Policy

## Supported versions

Only the latest released version of `hass-mcp` receives security fixes. Please
upgrade to the latest release of the PyPI package `hass-mcp` or the Docker image
`voska/hass-mcp:latest` before reporting.

## Reporting a vulnerability

Please report security issues **privately**. Do not open a public issue.

Use GitHub's [private vulnerability reporting](https://github.com/voska/hass-mcp/security/advisories/new)
(the "Report a vulnerability" button on the repository's **Security** tab).

We aim to acknowledge reports within 5 business days and to ship a fix or
mitigation for confirmed issues as quickly as is practical, crediting reporters
who wish to be named.

## Credentials and exposure

- `HA_TOKEN` is a Home Assistant long-lived access token. It carries the full
  permissions of the Home Assistant user who created it.
- Keep the token out of shell history, logs and committed `.env` files. MCP
  client configuration files also store it in plain text.
- Prefer a dedicated Home Assistant user so its token can be revoked on its own.
- HTTP mode has no built-in authentication and binds `127.0.0.1` by default.
  Put an authenticating reverse proxy or a VPN in front of it before using
  `--host 0.0.0.0` or setting `MCP_HOST=0.0.0.0`. See the README's
  [HTTP transport warning](README.md#http-transport-streamable).
