"""Live Lovelace dashboard editing for Home Assistant.

Home Assistant manages dashboards (Lovelace) entirely over its WebSocket API,
and a `lovelace/config/save` pushes the change to every connected browser
instantly — no restart. HA has no partial-edit API: every change is a
read-modify-write of the dashboard's *entire* config. This module provides:

- a **raw layer** (`list_dashboards`, `get_dashboard_config`,
  `set_dashboard_config`) that maps directly onto the HA WS commands, and
- **high-level helpers** (`add_card`/`update_card`/`remove_card`/`move_card`
  and `add_view`/`remove_view`/`update_view`) that do the read-modify-write
  for you, routing every write through `set_dashboard_config`.

`set_dashboard_config` is the single write choke point and enforces all the
safety guardrails: it refuses YAML-mode dashboards (which HA can't save via
the API), validates the config's structure, backs the current config up to
disk before overwriting, and supports `dry_run` previews.

Everything talks to HA through `app.ws.call_ws`, the same authenticated
request/response primitive used by the statistics tools.
"""
from typing import Any, Dict, List, Optional, Union
import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from app.ws import call_ws, HassWebSocketError
from app import config

logger = logging.getLogger(__name__)

# Per-dashboard locks to serialize concurrent writes. HA may resolve an
# omitted url_path to "lovelace", so both selectors always share one key.
_locks: Dict[str, asyncio.Lock] = {}

# A `view` argument that selects an existing view: an integer index, or a
# string matched against each view's `path` or `title`.
ViewSelector = Union[int, str]

# A `section` argument that selects a section inside a "sections"-type view:
# an integer index, or a string matched against the section's `title` or its
# first heading card's `heading`.
SectionSelector = Union[int, str]


class LovelaceError(Exception):
    """Raised for dashboard edits that fail validation or HA constraints.

    Carries a human-readable, actionable message (bad index, YAML-mode
    dashboard, missing card `type`, etc.).
    """


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _content_hash(cfg: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(cfg, sort_keys=True, default=str).encode()
    ).hexdigest()


def _label(url_path: Optional[str]) -> str:
    return f"'{url_path}'" if url_path else "(default)"


def _lock_for(url_path: Optional[str]) -> asyncio.Lock:
    """Return the per-dashboard lock for a dashboard selector."""
    key = "lovelace" if url_path is None else url_path
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _as_int_or_none(value: Any) -> Optional[int]:
    """Interpret a value as an int index, or None. Accepts real ints and
    integer-valued strings like "0" — MCP clients often stringify numeric
    arguments to a Union[int, str] parameter."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _is_config_not_found(err: Exception) -> bool:
    s = str(err).lower()
    return any(k in s for k in ("config_not_found", "no config found", "unknown config"))


def _is_yaml_or_not_storage(err: Exception) -> bool:
    # Only phrases that specifically indicate a YAML-mode / non-storage save
    # rejection. A bare "supported" or a generic "config_not_found" would
    # misclassify unrelated save errors and hide their real cause.
    s = str(err).lower()
    return any(k in s for k in ("yaml", "not storage", "not supported"))


def _view_card_count(view: Dict[str, Any]) -> int:
    """Count a view's cards, whether classic (top-level `cards`) or a
    "sections" view (cards live in `sections[].cards`)."""
    sections = view.get("sections")
    if isinstance(sections, list):
        return sum(
            len(s.get("cards", []) or []) for s in sections if isinstance(s, dict)
        )
    return len(view.get("cards", []) or [])


def _summarize(cfg: Dict[str, Any]) -> Dict[str, Any]:
    views = cfg.get("views", []) or []
    return {
        "views": len(views),
        "total_cards": sum(_view_card_count(v) for v in views),
        "cards_per_view": [_view_card_count(v) for v in views],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_card(card: Any, where: str) -> None:
    if not isinstance(card, dict):
        raise LovelaceError(f"{where} must be a dict.")
    if not isinstance(card.get("type"), str) or not card.get("type"):
        raise LovelaceError(f"{where} must have a non-empty string 'type'.")


def _validate_config(cfg: Any) -> None:
    """Structural-only check. Card *internals* aren't validated — HA core and
    custom cards define open-ended schemas, so we only guard the shape that
    would otherwise break the dashboard render or our own indexing.

    Strategy configs (``{"strategy": {"type": "..."}}``) are accepted by
    the raw read/write layer but rejected by high-level card/view helpers;
    they have no views/cards to edit."""
    if not isinstance(cfg, dict):
        raise LovelaceError("Dashboard config must be a dict.")
    # Strategy dashboards have no views/cards — valid for raw read/write.
    if "strategy" in cfg:
        return
    views = cfg.get("views")
    if not isinstance(views, list):
        raise LovelaceError("Dashboard config must contain a 'views' list.")
    for vi, view in enumerate(views):
        if not isinstance(view, dict):
            raise LovelaceError(f"views[{vi}] must be a dict.")
        cards = view.get("cards")
        if cards is not None:
            if not isinstance(cards, list):
                raise LovelaceError(f"views[{vi}].cards must be a list.")
            for ci, card in enumerate(cards):
                _validate_card(card, f"views[{vi}].cards[{ci}]")
        # "sections"-type views hold their cards inside sections[].cards.
        sections = view.get("sections")
        if sections is not None:
            if not isinstance(sections, list):
                raise LovelaceError(f"views[{vi}].sections must be a list.")
            for si, section in enumerate(sections):
                if not isinstance(section, dict):
                    raise LovelaceError(f"views[{vi}].sections[{si}] must be a dict.")
                scards = section.get("cards")
                if scards is not None:
                    if not isinstance(scards, list):
                        raise LovelaceError(
                            f"views[{vi}].sections[{si}].cards must be a list."
                        )
                    for ci, card in enumerate(scards):
                        _validate_card(card, f"views[{vi}].sections[{si}].cards[{ci}]")


# ---------------------------------------------------------------------------
# View / card resolution
# ---------------------------------------------------------------------------

def _resolve_view(cfg: Dict[str, Any], view: ViewSelector) -> int:
    """Return the index of the view selected by `view` (index, path, or title)."""
    views = cfg.get("views", []) or []
    if isinstance(view, bool):  # bool is an int subclass — reject explicitly
        raise LovelaceError("view must be an int index or a string path/title.")
    if isinstance(view, int):
        if view < 0 or view >= len(views):
            raise LovelaceError(
                f"View index {view} out of range (have {len(views)} view(s))."
            )
        return view
    if isinstance(view, str):
        for i, v in enumerate(views):
            if v.get("path") == view or v.get("title") == view:
                return i
        # No name match — a numeric string (e.g. "0") is an index.
        n = _as_int_or_none(view)
        if n is not None:
            if n < 0 or n >= len(views):
                raise LovelaceError(
                    f"View index {n} out of range (have {len(views)} view(s))."
                )
            return n
        available = [
            f"{i}:{v.get('title') or v.get('path') or '?'}" for i, v in enumerate(views)
        ]
        raise LovelaceError(f"View {view!r} not found. Available views: {available}")
    raise LovelaceError("view must be an int index or a string path/title.")


def _coerce_index(value: Any, length: int, name: str) -> int:
    """Coerce an index argument (int or numeric string — MCP clients stringify
    numeric args) and bounds-check it against `length`. Raises LovelaceError."""
    idx = _as_int_or_none(value)
    if idx is None or idx < 0 or idx >= length:
        raise LovelaceError(
            f"{name} {value!r} out of range (have {length} card(s))."
        )
    return idx


def _coerce_position(value: Any, length: int) -> int:
    """Coerce an insert position (int or numeric string) and clamp into
    [0, length] — insertion tolerates out-of-range by pinning to the ends."""
    pos = _as_int_or_none(value)
    if pos is None:
        raise LovelaceError(f"position must be an integer, got {value!r}.")
    return max(0, min(pos, length))


# ---------------------------------------------------------------------------
# Sections-view support
#
# Home Assistant's modern "sections" view type renders cards from
# view["sections"][n]["cards"], NOT the top-level view["cards"] (which it
# ignores). Card operations must target a section on these views, or the edit
# would save successfully yet never render — a silent failure. `_resolve_card_list`
# is the single place that decides which list a card op mutates.
# ---------------------------------------------------------------------------

def _is_sections_view(view: Dict[str, Any]) -> bool:
    return view.get("type") == "sections" or isinstance(view.get("sections"), list)


def _section_heading(section: Dict[str, Any]) -> Optional[str]:
    """The heading text of a section's first `heading` card, if any."""
    for card in section.get("cards", []) or []:
        if isinstance(card, dict) and card.get("type") == "heading":
            return card.get("heading")
    return None


def _section_labels(sections: List[Dict[str, Any]]) -> List[str]:
    return [
        f"{i}:{s.get('title') or _section_heading(s) or '?'}"
        for i, s in enumerate(sections)
    ]


def _resolve_section(view: Dict[str, Any], section: SectionSelector) -> int:
    """Return the index of the section selected by `section` (index/title/heading)."""
    sections = view.get("sections", []) or []
    if isinstance(section, bool):  # bool is an int subclass — reject explicitly
        raise LovelaceError("section must be an int index or a string title/heading.")
    if isinstance(section, int):
        if section < 0 or section >= len(sections):
            raise LovelaceError(
                f"section index {section} out of range (have {len(sections)} section(s))."
            )
        return section
    if isinstance(section, str):
        for i, s in enumerate(sections):
            if s.get("title") == section or _section_heading(s) == section:
                return i
        # No title/heading match — a numeric string (e.g. "0") is an index.
        n = _as_int_or_none(section)
        if n is not None:
            if n < 0 or n >= len(sections):
                raise LovelaceError(
                    f"section index {n} out of range (have {len(sections)} section(s))."
                )
            return n
        raise LovelaceError(
            f"Section {section!r} not found. Available sections: {_section_labels(sections)}"
        )
    raise LovelaceError("section must be an int index or a string title/heading.")


def _cards_of(container: Dict[str, Any]) -> List[Any]:
    """Return `container["cards"]` as a list, attaching a fresh list when the
    key is absent, null, or otherwise not a list. `dict.setdefault` alone
    doesn't cover an explicit `"cards": null` (which `_validate_config`
    permits), which would then break `.insert` / `len` on the card ops."""
    cards = container.get("cards")
    if not isinstance(cards, list):
        cards = []
        container["cards"] = cards
    return cards


def _resolve_card_list(
    view: Dict[str, Any], section: Optional[SectionSelector], view_idx: int
) -> List[Any]:
    """Return the mutable cards list a card op should operate on.

    For a "sections" view, `section` is required (otherwise the edit would
    write where HA renders nothing); returns that section's `cards`. For a
    classic view, `section` must be omitted; returns the view's `cards`.
    The returned list is attached to the config, so mutating it in place edits
    the config."""
    if _is_sections_view(view):
        if section is None:
            sections = view.get("sections", []) or []
            raise LovelaceError(
                f"View {view_idx} is a 'sections' view — pass `section` (index, "
                f"title, or heading) to say which section to edit. "
                f"Available sections: {_section_labels(sections)}"
            )
        view.setdefault("sections", [])
        si = _resolve_section(view, section)
        return _cards_of(view["sections"][si])
    if section is not None:
        raise LovelaceError(
            f"View {view_idx} is not a 'sections' view; omit `section`."
        )
    return _cards_of(view)


# ---------------------------------------------------------------------------
# Mode detection (YAML guard) + backups
# ---------------------------------------------------------------------------

async def _dashboard_mode(url_path: Optional[str]) -> Optional[str]:
    """Best-effort lookup of a dashboard's mode ('storage' / 'yaml').

    Uses ``lovelace/dashboards/list`` — the only WS command that reliably
    reports per-dashboard mode across HA versions. For the default dashboard
    (url_path=None), checks whether a YAML-backed ``"lovelace"`` entry
    dominates (per ``_handle_errors`` resolution in HA core). Returns None
    when the mode can't be determined; callers then rely on the reactive
    guard (translating HA's save error)."""
    try:
        dashboards = await call_ws("lovelace/dashboards/list")
    except HassWebSocketError:
        return None

    if url_path is None:
        for d in dashboards or []:
            if d.get("url_path") == "lovelace" and d.get("mode") == "yaml":
                return "yaml"
        return "storage"

    for d in dashboards or []:
        if d.get("url_path") == url_path:
            return d.get("mode")
    return None


async def _backup_current(url_path: Optional[str]) -> Optional[str]:
    """Write the dashboard's current config to the backup dir. Returns the
    backup id (filename), or None if there's nothing stored to back up."""
    payload: Dict[str, Any] = {"force": True}
    if url_path is not None:
        payload["url_path"] = url_path
    try:
        current = await call_ws("lovelace/config", **payload)
    except HassWebSocketError as err:
        if _is_config_not_found(err):
            return None  # nothing stored yet — first save creates it
        raise

    backups_dir = config.HASS_MCP_BACKUP_DIR
    os.makedirs(backups_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    slug = url_path if url_path else "default"
    backup_id = f"lovelace_{slug}_{stamp}.json"
    with open(os.path.join(backups_dir, backup_id), "w") as f:
        json.dump(current, f, indent=2)
    return backup_id


# ---------------------------------------------------------------------------
# Raw layer
# ---------------------------------------------------------------------------

async def list_dashboards() -> List[Dict[str, Any]]:
    """List dashboards, including the default 'Overview' (url_path=None).

    Each entry has at least `url_path`, `title`, and `mode` ('storage' or
    'yaml'). Only 'storage'-mode dashboards can be edited via this API."""
    default_mode = await _dashboard_mode(None)
    dashboards: List[Dict[str, Any]] = [
        {"url_path": None, "title": "Overview (default)", "mode": default_mode}
    ]
    try:
        listed = await call_ws("lovelace/dashboards/list")
    except HassWebSocketError:
        listed = []
    for d in listed or []:
        dashboards.append(
            {
                "url_path": d.get("url_path"),
                "title": d.get("title"),
                "mode": d.get("mode"),
                "id": d.get("id"),
                "icon": d.get("icon"),
            }
        )
    return dashboards


async def get_dashboard_config(url_path: Optional[str] = None) -> Dict[str, Any]:
    """Return a dashboard's full config dict.

    `url_path=None` is the default dashboard. If the dashboard has no stored
    config yet (HA auto-generates one), returns an empty scaffold
    `{"views": [], "note": ...}` rather than erroring."""
    payload: Dict[str, Any] = {"force": True}
    if url_path is not None:
        payload["url_path"] = url_path
    try:
        cfg = await call_ws("lovelace/config", **payload)
    except HassWebSocketError as err:
        if _is_config_not_found(err):
            return {
                "views": [],
                "note": (
                    f"Dashboard {_label(url_path)} has no stored config yet "
                    "(auto-generated). The first save will create one."
                ),
            }
        raise
    return cfg


async def set_dashboard_config(
    url_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Overwrite a dashboard's full config — the single write choke point.

    Takes the per-dashboard lock first, so a raw write serializes against
    high-level card/view edits on the same dashboard (they share this
    function's locked body).

    Enforces, in order: structural validation, YAML-mode rejection, dry-run
    preview, then backup-before-save. ⚠️ This replaces the ENTIRE dashboard
    config and is reflected live in every open browser. The prior config is
    backed up first (see `restore_dashboard`)."""
    async with _lock_for(url_path):
        return await _set_dashboard_config_locked(url_path, config, dry_run=dry_run)


async def _set_dashboard_config_locked(
    url_path: Optional[str],
    config: Optional[Dict[str, Any]],
    dry_run: bool,
) -> Dict[str, Any]:
    """Locked body of set_dashboard_config — callers must hold the lock."""
    if config is None:
        raise LovelaceError("config is required.")
    _validate_config(config)

    # Stale snapshot guard: high-level helpers stamp a hash on the config
    # they read. Before writing, re-read and verify it hasn't changed
    # underneath us — another client or the HA frontend may have edited it.
    snapshot_hash = config.pop("_snapshot_hash", None)
    if snapshot_hash is not None:
        current = await get_dashboard_config(url_path)
        current.pop("note", None)
        if _content_hash(current) != snapshot_hash:
            raise LovelaceError(
                "Dashboard config was modified since it was read. "
                "Please retry the operation."
            )

    if await _dashboard_mode(url_path) == "yaml":
        raise LovelaceError(
            f"Dashboard {_label(url_path)} is in YAML mode and cannot be edited "
            "via the API. Edit its YAML file directly."
        )

    if dry_run:
        return {
            "dry_run": True,
            "url_path": url_path,
            "summary": _summarize(config),
            "config": config,
        }

    backup_id = await _backup_current(url_path)

    payload: Dict[str, Any] = {"config": config}
    if url_path is not None:
        payload["url_path"] = url_path
    try:
        await call_ws("lovelace/config/save", **payload)
    except HassWebSocketError as err:
        if _is_yaml_or_not_storage(err):
            raise LovelaceError(
                f"Dashboard {_label(url_path)} cannot be saved via the API "
                "(it is YAML-mode or not storage-backed)."
            )
        raise

    return {
        "success": True,
        "url_path": url_path,
        "backup_id": backup_id,
        "summary": _summarize(config),
    }


# ---------------------------------------------------------------------------
# High-level helpers — read-modify-write through set_dashboard_config
# ---------------------------------------------------------------------------

async def _load_for_edit(url_path: Optional[str]) -> Dict[str, Any]:
    """Read a dashboard config for high-level editing.

    Returns the config with an internal ``_snapshot_hash`` stamp used by
    ``set_dashboard_config`` to detect stale snapshots. Rejects strategy
    dashboards — those have no views/cards to mutate."""
    cfg = await get_dashboard_config(url_path)
    cfg.pop("note", None)  # internal scaffold marker — never persist it
    if "strategy" in cfg:
        raise LovelaceError(
            f"This dashboard uses a generation strategy "
            f"(type: {cfg['strategy'].get('type', 'unknown')}). "
            "Card/view editing is not supported for strategy dashboards. "
            "Use get_dashboard_config/set_dashboard_config instead."
        )
    cfg.setdefault("views", [])
    cfg["_snapshot_hash"] = _content_hash(cfg)
    return cfg


async def add_card(
    url_path: Optional[str] = None,
    view: ViewSelector = 0,
    card: Optional[Dict[str, Any]] = None,
    position: Optional[int] = None,
    section: Optional[SectionSelector] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Add a card to a view. `position` inserts at that index (default: end).

    For a "sections" view, pass `section` (index, title, or heading) to choose
    which section the card goes in."""
    if card is None:
        raise LovelaceError("card is required.")
    _validate_card(card, "card")
    async with _lock_for(url_path):
        cfg = await _load_for_edit(url_path)
        vi = _resolve_view(cfg, view)
        cards = _resolve_card_list(cfg["views"][vi], section, vi)
        idx = len(cards) if position is None else _coerce_position(position, len(cards))
        cards.insert(idx, card)
        return await _set_dashboard_config_locked(url_path, cfg, dry_run=dry_run)


async def update_card(
    url_path: Optional[str] = None,
    view: ViewSelector = 0,
    card_index: int = 0,
    card: Optional[Dict[str, Any]] = None,
    section: Optional[SectionSelector] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Replace the card at `card_index` in `view` (or its `section`) with `card`."""
    if card is None:
        raise LovelaceError("card is required.")
    _validate_card(card, "card")
    async with _lock_for(url_path):
        cfg = await _load_for_edit(url_path)
        vi = _resolve_view(cfg, view)
        cards = _resolve_card_list(cfg["views"][vi], section, vi)
        card_index = _coerce_index(card_index, len(cards), "card_index")
        cards[card_index] = card
        return await _set_dashboard_config_locked(url_path, cfg, dry_run=dry_run)


async def remove_card(
    url_path: Optional[str] = None,
    view: ViewSelector = 0,
    card_index: int = 0,
    section: Optional[SectionSelector] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Remove the card at `card_index` from `view` (or its `section`)."""
    async with _lock_for(url_path):
        cfg = await _load_for_edit(url_path)
        vi = _resolve_view(cfg, view)
        cards = _resolve_card_list(cfg["views"][vi], section, vi)
        card_index = _coerce_index(card_index, len(cards), "card_index")
        cards.pop(card_index)
        return await _set_dashboard_config_locked(url_path, cfg, dry_run=dry_run)


async def move_card(
    url_path: Optional[str] = None,
    view: ViewSelector = 0,
    card_index: int = 0,
    new_index: int = 0,
    section: Optional[SectionSelector] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Reorder a card within a view (or its `section`): `card_index` -> `new_index`."""
    async with _lock_for(url_path):
        cfg = await _load_for_edit(url_path)
        vi = _resolve_view(cfg, view)
        cards = _resolve_card_list(cfg["views"][vi], section, vi)
        card_index = _coerce_index(card_index, len(cards), "card_index")
        new_index = _coerce_index(new_index, len(cards), "new_index")
        card = cards.pop(card_index)
        cards.insert(new_index, card)
        return await _set_dashboard_config_locked(url_path, cfg, dry_run=dry_run)


async def list_view_sections(
    url_path: Optional[str] = None,
    view: ViewSelector = 0,
) -> List[Dict[str, Any]]:
    """List the sections of a "sections"-type view, so card ops can target one.

    Returns one entry per section with its `index`, `title`, first `heading`,
    and `card_count`. Raises if the view isn't a sections view."""
    cfg = await get_dashboard_config(url_path)
    vi = _resolve_view(cfg, view)
    view_obj = cfg["views"][vi]
    if not _is_sections_view(view_obj):
        raise LovelaceError(
            f"View {vi} is not a 'sections' view — it has no sections to list."
        )
    sections = view_obj.get("sections", []) or []
    return [
        {
            "index": i,
            "title": s.get("title"),
            "heading": _section_heading(s),
            "card_count": len(s.get("cards", []) or []),
        }
        for i, s in enumerate(sections)
    ]


async def add_view(
    url_path: Optional[str] = None,
    view_config: Optional[Dict[str, Any]] = None,
    position: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Add a new view. `view_config` is the view dict (e.g. {'title': 'Garage'})."""
    if not isinstance(view_config, dict):
        raise LovelaceError(
            "view_config must be a dict describing the view (e.g. {'title': 'Garage'})."
        )
    async with _lock_for(url_path):
        cfg = await _load_for_edit(url_path)
        views = cfg["views"]
        idx = len(views) if position is None else _coerce_position(position, len(views))
        views.insert(idx, view_config)
        return await _set_dashboard_config_locked(url_path, cfg, dry_run=dry_run)


async def remove_view(
    url_path: Optional[str] = None,
    view: ViewSelector = 0,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Remove the view selected by `view` (index, path, or title)."""
    async with _lock_for(url_path):
        cfg = await _load_for_edit(url_path)
        vi = _resolve_view(cfg, view)
        cfg["views"].pop(vi)
        return await _set_dashboard_config_locked(url_path, cfg, dry_run=dry_run)


async def update_view(
    url_path: Optional[str] = None,
    view: ViewSelector = 0,
    changes: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Shallow-merge `changes` into a view's properties (title, path, icon, …).

    Cards are preserved unless `changes` explicitly includes a `cards` key."""
    if not isinstance(changes, dict):
        raise LovelaceError(
            "changes must be a dict of view properties to update "
            "(e.g. {'title': 'New Title'})."
        )
    async with _lock_for(url_path):
        cfg = await _load_for_edit(url_path)
        vi = _resolve_view(cfg, view)
        cfg["views"][vi].update(changes)
        return await _set_dashboard_config_locked(url_path, cfg, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Backups: list + restore
# ---------------------------------------------------------------------------

def list_dashboard_backups(url_path: Optional[str] = None) -> List[Dict[str, str]]:
    """List on-disk backups for a dashboard, oldest first (newest last)."""
    backups_dir = config.HASS_MCP_BACKUP_DIR
    if not os.path.isdir(backups_dir):
        return []
    slug = url_path if url_path else "default"
    prefix = f"lovelace_{slug}_"
    out = []
    for name in sorted(os.listdir(backups_dir)):
        if name.startswith(prefix) and name.endswith(".json"):
            out.append({"backup_id": name, "path": os.path.join(backups_dir, name)})
    return out


async def restore_dashboard(
    url_path: Optional[str] = None,
    backup_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Restore a dashboard from a backup (newest if `backup_id` omitted).

    Goes through `set_dashboard_config`, so the current (pre-restore) config
    is itself backed up first — you can undo a restore."""
    backups = list_dashboard_backups(url_path)
    if not backups:
        raise LovelaceError(f"No backups found for dashboard {_label(url_path)}.")
    if backup_id is None:
        chosen = backups[-1]
    else:
        chosen = next((b for b in backups if b["backup_id"] == backup_id), None)
        if chosen is None:
            raise LovelaceError(
                f"Backup {backup_id!r} not found for dashboard {_label(url_path)}."
            )
    with open(chosen["path"]) as f:
        cfg = json.load(f)
    # Backup files are immutable, so the read is safe outside the lock; the
    # save itself must serialize against concurrent edits.
    async with _lock_for(url_path):
        result = await _set_dashboard_config_locked(url_path, cfg, dry_run=dry_run)
    result["restored_from"] = chosen["backup_id"]
    return result
