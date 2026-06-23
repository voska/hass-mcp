# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-06-23

### Added
- Long-term statistics + date-range history tools. `get_statistics` /
  `get_statistics_range` hit HA's `recorder/statistics_during_period`
  over a new WebSocket client (`app/ws.py`), returning aggregated
  buckets (mean / min / max) that survive the recorder's short-term
  retention window — the right call for monthly / yearly trends or for
  high-frequency sensors where raw history is too verbose.
  `get_history_range` adds an explicit-window variant of the existing
  REST history tool. New dependency: `websockets>=13`. Supersedes
  [#30] — ported as a focused subset (statistics + history range only;
  automation traces and config validation deferred) with thanks to
  @rmaher001 for the original implementation.
- `get_error_log` accepts optional filter parameters: `level`,
  `integration`, `search_term`, and `lines`. Filters combine with AND
  semantics and are applied server-side after ANSI stripping; the
  returned `error_count`, `warning_count`, `integration_mentions`, and
  `total_lines` are computed over the filtered output so they always
  match what's returned. A new `filters_applied` field surfaces which
  filters were active. Supersedes [#34] — ported fresh against current
  master with thanks to @cstosgale for the original implementation.

## [0.4.1] - 2026-05-17

### Added
- Custom CA support for users running their own PKI (step-ca, smallstep,
  homelab OpenSSL). hass-mcp now verifies HTTPS against the OS-native
  trust store (macOS Keychain / Windows Cert Store / Linux
  ca-certificates) via [truststore](https://truststore.readthedocs.io/),
  and honors `SSL_CERT_FILE` for explicit overrides (the canonical
  Docker pattern: bind-mount the CA file, set the env var). Supersedes
  [#15] with a portable, defaults-safe mechanism — no `verify=False`
  fallback, no requests-specific `REQUESTS_CA_BUNDLE` shim.

## [0.4.0] - 2026-05-17

### Added
- Per-entity `area` field on `get_entity`, `list_entities`,
  `search_entities_tool`, and `system_overview`. Areas are resolved
  through HA's area registry (via `/api/template` with the
  `area_name(entity_id)` Jinja helper), which automatically falls back
  to the parent device's area when not set directly on the entity.
- New `get_entities_by_area` tool — list everything in a given room.
  Case-insensitive area match, optional domain filter.

### Fixed
- `system_overview` no longer reports every entity under a fake
  "Unknown" area. The previous code read `attributes.area_id` from
  `/api/states`, which HA never populates; entities without a real
  area are now bucketed under "Unassigned" and entities with one show
  their actual area name. ([#28])

## [0.3.0] - 2026-05-17

### Added
- Streamable HTTP transport. `hass-mcp --http` (or `python -m app --http`)
  runs the server as an MCP streamable HTTP endpoint at `/mcp` instead of
  stdio, enabling shared deployments behind MCP gateways, Smithery hosting,
  and direct integration from network-based MCP clients (LibreChat,
  OpenWebUI, custom). Stateless mode + JSON responses are enabled
  automatically when `--http` is set, suitable for horizontally-scaled
  hosts. Defaults bind to `127.0.0.1`; explicit `--host 0.0.0.0` required
  to expose externally. ([#23], supersedes [#33], thanks @robertlestak)
- End-to-end transport tests in `tests/test_transports.py` and
  `tests/test_docker.py` that spawn the real subprocess (and Docker
  container) and drive it through `stdio_client` / `streamable_http_client`
  — same wire-level clients Claude Desktop uses.

### Changed
- Bumped `mcp[cli]` from `>=1.4.1` to `>=1.27,<2`. Targets the current
  MCP spec (`2025-11-25`); 14-month leap, validated against the protocol
  harness from v0.2.0.

### Security
- HTTP transport ships with a prominent README warning about the auth
  gap. The MCP `2025-11-25` spec defines OAuth 2.1 as the canonical
  HTTP auth mechanism; first-class support is coming in a follow-up
  release. Until then, deploy behind a reverse proxy / VPN / localhost.

## [0.2.0] - 2026-05-16

### Fixed
- `call_service_tool` now returns a dict instead of the raw list from
  Home Assistant. Prevented Pydantic validation errors on services like
  `automation.reload` or `homeassistant.restart` that return `[]`.
  ([#29], thanks @brianegge)
- All 7 prompts now use `role: user` instead of the spec-invalid
  `role: system`. Prompts were unusable end-to-end before. ([#35])
- `get_error_log` now works on Home Assistant OS / Supervised
  installations by trying `/api/hassio/core/logs` first and falling
  back to `/api/error_log` for standalone HA. ANSI color codes are
  stripped and `homeassistant.components.X` integration labels are
  collapsed to `X`. (Thanks @JoeKarlsson, @darinlarimore)

### Added
- MCP protocol-level test harness (`tests/test_protocol.py`) using the
  official MCP SDK in-memory transport and `respx` for mocking the
  Home Assistant backend. Exercises tools, prompts, and resources
  through the real protocol layer rather than direct Python calls.

### Changed
- Release pipeline consolidated into a single tag-triggered workflow
  with OIDC trusted publishing to PyPI, PEP 740 build provenance
  attestations, multi-arch Docker images with sigstore provenance + SBOM,
  and automatic GitHub Release creation. Version is now derived from
  git tags via `hatch-vcs`.
- Docker Hub `:latest` now tracks the most recent tagged release only.
  Master HEAD is published as `:edge` for users who want to test
  unreleased changes.

## [0.1.3] - 2026-05-16

Validation release for the consolidated release pipeline. No functional
changes.

## [0.1.2] - 2026-05-16

Validation release for the new tag-driven release infrastructure
(`hatch-vcs` versioning, OIDC publishing, `:latest` decoupling). No
functional changes.

## [0.1.1] - 2025-08-05

### Fixed
- FastMCP initialization no longer passes the unsupported `capabilities`
  keyword. ([#19])

## [0.1.0] - 2025-07-13

Initial PyPI release.

[Unreleased]: https://github.com/voska/hass-mcp/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/voska/hass-mcp/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/voska/hass-mcp/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/voska/hass-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/voska/hass-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/voska/hass-mcp/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/voska/hass-mcp/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/voska/hass-mcp/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/voska/hass-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/voska/hass-mcp/releases/tag/v0.1.0

[#15]: https://github.com/voska/hass-mcp/pull/15
[#19]: https://github.com/voska/hass-mcp/issues/19
[#23]: https://github.com/voska/hass-mcp/issues/23
[#28]: https://github.com/voska/hass-mcp/issues/28
[#29]: https://github.com/voska/hass-mcp/issues/29
[#30]: https://github.com/voska/hass-mcp/pull/30
[#33]: https://github.com/voska/hass-mcp/pull/33
[#34]: https://github.com/voska/hass-mcp/pull/34
[#35]: https://github.com/voska/hass-mcp/issues/35
