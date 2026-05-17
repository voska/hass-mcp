# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/voska/hass-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/voska/hass-mcp/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/voska/hass-mcp/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/voska/hass-mcp/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/voska/hass-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/voska/hass-mcp/releases/tag/v0.1.0

[#19]: https://github.com/voska/hass-mcp/issues/19
[#29]: https://github.com/voska/hass-mcp/issues/29
[#35]: https://github.com/voska/hass-mcp/issues/35
