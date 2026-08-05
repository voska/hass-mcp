"""Unit tests for app.lovelace — live Lovelace dashboard editing.

All Home Assistant interaction goes through `app.ws.call_ws`. These tests
replace it with `FakeWS`, an in-memory dispatcher keyed by WS message type
that models a small HA instance (a config store + a dashboards list). This
lets us assert real read-modify-write behaviour and exactly what got saved,
without any sockets.

Backups are redirected to a pytest tmp_path so the real ~/.hass-mcp dir is
never touched.
"""
import copy
import asyncio
import json
import os

import pytest

from app.ws import HassWebSocketError
from app import config as app_config
import app.lovelace as lovelace
from app.lovelace import LovelaceError


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeWS:
    """In-memory stand-in for app.ws.call_ws, routing by message type."""

    def __init__(self):
        # url_path (None == default) -> config dict
        self.config_store = {None: {"views": [{"title": "Home", "cards": []}]}}
        self.dashboards = [
            {"id": "abc", "url_path": "test-dash", "title": "Test", "mode": "storage"},
            {"id": "def", "url_path": "yaml-dash", "title": "YAML", "mode": "yaml"},
        ]
        self.saved = []  # list of (url_path, config) in call order

    async def __call__(self, message_type, **payload):
        if message_type == "lovelace/dashboards/list":
            return self.dashboards
        if message_type == "lovelace/config":
            url_path = self._resolve(payload.get("url_path"))
            if url_path in self.config_store:
                # HA returns freshly-deserialized JSON each call — never an
                # alias of caller-held state. Deep-copy to model that.
                return copy.deepcopy(self.config_store[url_path])
            raise HassWebSocketError(
                "WS request 'lovelace/config' failed: "
                "{'code': 'config_not_found', 'message': 'No config found.'}"
            )
        if message_type == "lovelace/config/save":
            url_path = self._resolve(payload.get("url_path"))
            self.saved.append((url_path, copy.deepcopy(payload["config"])))
            self.config_store[url_path] = copy.deepcopy(payload["config"])
            return None
        raise AssertionError(f"unexpected WS message type: {message_type}")

    def _resolve(self, url_path):
        """HA resolves an omitted url_path to the 'lovelace' dashboard when one
        exists (lovelace/websocket.py) — model that so alias interleavings
        are tested faithfully."""
        if url_path is not None:
            return url_path
        for d in self.dashboards:
            if d.get("url_path") == "lovelace":
                return "lovelace"
        return url_path


@pytest.fixture
def fake_ws(monkeypatch, tmp_path):
    fake = FakeWS()
    monkeypatch.setattr("app.lovelace.call_ws", fake)
    monkeypatch.setattr("app.config.HASS_MCP_BACKUP_DIR", str(tmp_path))
    return fake


@pytest.fixture(autouse=True)
def _fresh_locks():
    """Each test gets a fresh per-dashboard lock registry. The module-level
    dict would otherwise hand out locks bound to a previous test's event
    loop (a contended acquire binds the loop)."""
    lovelace._locks.clear()
    yield
    lovelace._locks.clear()


# --------------------------------------------------------------------------
# Raw layer
# --------------------------------------------------------------------------

async def test_list_dashboards_includes_default_and_named(fake_ws):
    dashboards = await lovelace.list_dashboards()
    by_path = {d["url_path"]: d for d in dashboards}
    assert None in by_path  # default dashboard present
    assert by_path[None]["mode"] == "storage"
    assert by_path["test-dash"]["mode"] == "storage"
    assert by_path["yaml-dash"]["mode"] == "yaml"


async def test_get_dashboard_config_returns_stored(fake_ws):
    cfg = await lovelace.get_dashboard_config("test-dash")
    fake_ws.config_store["test-dash"] = {"views": [{"title": "X"}]}
    cfg = await lovelace.get_dashboard_config("test-dash")
    assert cfg["views"][0]["title"] == "X"


async def test_get_dashboard_config_scaffolds_when_missing(fake_ws):
    # "new-dash" isn't in the store -> HA raises config_not_found.
    cfg = await lovelace.get_dashboard_config("new-dash")
    assert cfg["views"] == []
    assert "note" in cfg


async def test_set_dashboard_config_backs_up_then_saves(fake_ws):
    new_cfg = {"views": [{"title": "Home", "cards": [{"type": "markdown", "content": "hi"}]}]}
    result = await lovelace.set_dashboard_config(None, new_cfg)

    assert result["success"] is True
    assert fake_ws.saved == [(None, new_cfg)]
    # A backup file for the prior config was written.
    backup_dir = app_config.HASS_MCP_BACKUP_DIR
    files = os.listdir(backup_dir)
    assert len(files) == 1 and files[0].startswith("lovelace_default_")
    assert result["backup_id"] == files[0]
    # Backup holds the ORIGINAL config (one empty-card view), not the new one.
    with open(os.path.join(backup_dir, files[0])) as f:
        backed_up = json.load(f)
    assert backed_up == {"views": [{"title": "Home", "cards": []}]}


async def test_dry_run_does_not_save(fake_ws):
    new_cfg = {"views": [{"title": "Home", "cards": []}]}
    result = await lovelace.set_dashboard_config(None, new_cfg, dry_run=True)
    assert result["dry_run"] is True
    assert "summary" in result
    assert fake_ws.saved == []


async def test_yaml_mode_dashboard_rejected(fake_ws):
    with pytest.raises(LovelaceError, match="YAML"):
        await lovelace.set_dashboard_config("yaml-dash", {"views": []})
    assert fake_ws.saved == []


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

async def test_validation_requires_views_list(fake_ws):
    with pytest.raises(LovelaceError, match="views"):
        await lovelace.set_dashboard_config(None, {"not_views": 1})


async def test_validation_requires_card_type(fake_ws):
    bad = {"views": [{"cards": [{"content": "no type"}]}]}
    with pytest.raises(LovelaceError, match="type"):
        await lovelace.set_dashboard_config(None, bad)


# --------------------------------------------------------------------------
# Card ops
# --------------------------------------------------------------------------

async def test_add_card_appends(fake_ws):
    card = {"type": "markdown", "content": "hello"}
    await lovelace.add_card(None, view=0, card=card)
    _, saved = fake_ws.saved[-1]
    assert saved["views"][0]["cards"][-1] == card


async def test_add_card_at_position(fake_ws):
    fake_ws.config_store[None] = {
        "views": [{"title": "Home", "cards": [{"type": "a"}, {"type": "b"}]}]
    }
    await lovelace.add_card(None, view=0, card={"type": "x"}, position=1)
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["cards"]] == ["a", "x", "b"]


async def test_add_card_requires_type(fake_ws):
    with pytest.raises(LovelaceError, match="type"):
        await lovelace.add_card(None, view=0, card={"content": "x"})


async def test_update_card_replaces(fake_ws):
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "a"}, {"type": "b"}]}]}
    await lovelace.update_card(None, view=0, card_index=1, card={"type": "c"})
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["cards"]] == ["a", "c"]


async def test_remove_card(fake_ws):
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "a"}, {"type": "b"}]}]}
    await lovelace.remove_card(None, view=0, card_index=0)
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["cards"]] == ["b"]


async def test_move_card_reorders(fake_ws):
    fake_ws.config_store[None] = {
        "views": [{"cards": [{"type": "a"}, {"type": "b"}, {"type": "c"}]}]
    }
    await lovelace.move_card(None, view=0, card_index=0, new_index=2)
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["cards"]] == ["b", "c", "a"]


async def test_card_index_out_of_range(fake_ws):
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "a"}]}]}
    with pytest.raises(LovelaceError, match="out of range"):
        await lovelace.remove_card(None, view=0, card_index=5)


# --------------------------------------------------------------------------
# View ops + resolution
# --------------------------------------------------------------------------

async def test_resolve_view_by_title_and_path(fake_ws):
    fake_ws.config_store[None] = {
        "views": [
            {"title": "Living Room", "path": "living"},
            {"title": "Kitchen", "path": "kitchen"},
        ]
    }
    await lovelace.add_card(None, view="Kitchen", card={"type": "x"})
    _, saved = fake_ws.saved[-1]
    assert saved["views"][1]["cards"][-1]["type"] == "x"

    await lovelace.add_card(None, view="living", card={"type": "y"})
    _, saved = fake_ws.saved[-1]
    assert saved["views"][0]["cards"][-1]["type"] == "y"


async def test_resolve_view_not_found(fake_ws):
    with pytest.raises(LovelaceError, match="not found"):
        await lovelace.add_card(None, view="Nonexistent", card={"type": "x"})


async def test_add_view(fake_ws):
    await lovelace.add_view(None, view_config={"title": "New View"})
    _, saved = fake_ws.saved[-1]
    assert saved["views"][-1]["title"] == "New View"


async def test_remove_view(fake_ws):
    fake_ws.config_store[None] = {"views": [{"title": "A"}, {"title": "B"}]}
    await lovelace.remove_view(None, view="A")
    _, saved = fake_ws.saved[-1]
    assert [v["title"] for v in saved["views"]] == ["B"]


async def test_update_view_retitle_preserves_cards(fake_ws):
    fake_ws.config_store[None] = {
        "views": [{"title": "Old", "cards": [{"type": "a"}]}]
    }
    await lovelace.update_view(None, view=0, changes={"title": "New"})
    _, saved = fake_ws.saved[-1]
    assert saved["views"][0]["title"] == "New"
    assert saved["views"][0]["cards"] == [{"type": "a"}]  # cards untouched


# --------------------------------------------------------------------------
# Sections-type views
# --------------------------------------------------------------------------

def _sections_view_config():
    """A 'sections'-type view with one section containing a heading."""
    return {
        "views": [
            {
                "type": "sections",
                "title": "Air Quality",
                "path": "air-quality",
                "sections": [
                    {"type": "grid", "cards": [
                        {"type": "heading", "heading": "Temperature"},
                        {"type": "history-graph", "entities": ["sensor.temp"]},
                    ]},
                    {"type": "grid", "cards": [
                        {"type": "heading", "heading": "Controls"},
                    ]},
                ],
            }
        ]
    }


async def test_add_card_to_section_by_index(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    card = {"type": "history-graph", "entities": ["sensor.humidity"]}
    await lovelace.add_card(None, view=0, card=card, section=0)
    _, saved = fake_ws.saved[-1]
    # Went into sections[0].cards, NOT a top-level cards[] array.
    assert saved["views"][0]["sections"][0]["cards"][-1] == card
    assert "cards" not in saved["views"][0]


async def test_add_card_to_section_by_heading(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    await lovelace.add_card(None, view=0, card={"type": "button"}, section="Controls")
    _, saved = fake_ws.saved[-1]
    assert saved["views"][0]["sections"][1]["cards"][-1]["type"] == "button"


async def test_add_card_section_at_position(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    await lovelace.add_card(None, view=0, card={"type": "x"}, section=0, position=1)
    _, saved = fake_ws.saved[-1]
    types = [c.get("type") for c in saved["views"][0]["sections"][0]["cards"]]
    assert types == ["heading", "x", "history-graph"]


async def test_sections_view_without_section_is_rejected(fake_ws):
    """The silent-failure guard: editing a sections view needs a section."""
    fake_ws.config_store[None] = _sections_view_config()
    with pytest.raises(LovelaceError, match="sections' view"):
        await lovelace.add_card(None, view=0, card={"type": "x"})
    assert fake_ws.saved == []


async def test_section_index_out_of_range(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    with pytest.raises(LovelaceError, match="section index .* out of range"):
        await lovelace.add_card(None, view=0, card={"type": "x"}, section=9)


async def test_section_as_numeric_string_is_index(fake_ws):
    """MCP clients may stringify a numeric section arg — "0" must mean index 0."""
    fake_ws.config_store[None] = _sections_view_config()
    await lovelace.add_card(None, view=0, card={"type": "x"}, section="0")
    _, saved = fake_ws.saved[-1]
    assert saved["views"][0]["sections"][0]["cards"][-1]["type"] == "x"


async def test_section_numeric_string_out_of_range(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    with pytest.raises(LovelaceError, match="section index .* out of range"):
        await lovelace.add_card(None, view=0, card={"type": "x"}, section="9")


async def test_view_as_numeric_string_is_index(fake_ws):
    """Same coercion for the `view` selector: "1" means index 1."""
    fake_ws.config_store[None] = {"views": [{"title": "A"}, {"title": "B", "cards": []}]}
    await lovelace.add_card(None, view="1", card={"type": "x"})
    _, saved = fake_ws.saved[-1]
    assert saved["views"][1]["cards"][-1]["type"] == "x"


async def test_card_index_as_numeric_string(fake_ws):
    """card_index/position/new_index accept stringified numbers too."""
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "a"}, {"type": "b"}]}]}
    await lovelace.remove_card(None, view=0, card_index="0")
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["cards"]] == ["b"]


async def test_position_and_new_index_as_numeric_strings(fake_ws):
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "a"}, {"type": "b"}]}]}
    await lovelace.add_card(None, view=0, card={"type": "x"}, position="1")
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["cards"]] == ["a", "x", "b"]

    await lovelace.move_card(None, view=0, card_index="0", new_index="2")
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["cards"]] == ["x", "b", "a"]


async def test_add_card_when_cards_is_null(fake_ws):
    """A view with explicit cards: null must not crash the card ops."""
    fake_ws.config_store[None] = {"views": [{"title": "Home", "cards": None}]}
    await lovelace.add_card(None, view=0, card={"type": "markdown"})
    _, saved = fake_ws.saved[-1]
    assert saved["views"][0]["cards"] == [{"type": "markdown"}]


async def test_summary_counts_section_cards(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    result = await lovelace.add_card(
        None, view=0, section=0, card={"type": "x"}, dry_run=True
    )
    # Section 0 had 2 cards, section 1 had 1 -> dry-run summary should reflect
    # the added card in section 0 (3), not report 0 for the sections view.
    assert result["summary"]["total_cards"] == 4
    assert result["summary"]["cards_per_view"] == [4]


async def test_save_error_not_misclassified_as_yaml(fake_ws, monkeypatch):
    """A generic save failure must surface raw, not be relabeled YAML-mode."""
    async def boom(message_type, **payload):
        if message_type == "lovelace/config/save":
            raise HassWebSocketError(
                "WS request 'lovelace/config/save' failed: "
                "{'code': 'unknown_error', 'message': 'boom'}"
            )
        return await FakeWS.__call__(fake_ws, message_type, **payload)

    monkeypatch.setattr("app.lovelace.call_ws", boom)
    with pytest.raises(HassWebSocketError, match="boom"):
        await lovelace.set_dashboard_config(None, {"views": [{"cards": []}]})


async def test_section_on_classic_view_is_rejected(fake_ws):
    """Passing section to a non-sections view is an error, not silently ignored."""
    fake_ws.config_store[None] = {"views": [{"title": "Home", "cards": []}]}
    with pytest.raises(LovelaceError, match="not a 'sections' view"):
        await lovelace.add_card(None, view=0, card={"type": "x"}, section=0)


async def test_update_and_remove_card_in_section(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    await lovelace.update_card(None, view=0, section=0, card_index=1,
                               card={"type": "gauge"})
    _, saved = fake_ws.saved[-1]
    assert saved["views"][0]["sections"][0]["cards"][1]["type"] == "gauge"

    await lovelace.remove_card(None, view=0, section=0, card_index=0)
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["sections"][0]["cards"]] == ["gauge"]


async def test_move_card_in_section(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    await lovelace.move_card(None, view=0, section=0, card_index=0, new_index=1)
    _, saved = fake_ws.saved[-1]
    assert [c["type"] for c in saved["views"][0]["sections"][0]["cards"]] == [
        "history-graph", "heading",
    ]


async def test_list_view_sections(fake_ws):
    fake_ws.config_store[None] = _sections_view_config()
    sections = await lovelace.list_view_sections(None, view=0)
    assert sections == [
        {"index": 0, "title": None, "heading": "Temperature", "card_count": 2},
        {"index": 1, "title": None, "heading": "Controls", "card_count": 1},
    ]


async def test_list_view_sections_on_classic_view_errors(fake_ws):
    fake_ws.config_store[None] = {"views": [{"title": "Home", "cards": []}]}
    with pytest.raises(LovelaceError, match="not a 'sections' view"):
        await lovelace.list_view_sections(None, view=0)


async def test_validation_rejects_bad_card_in_section(fake_ws):
    bad = {"views": [{"type": "sections", "sections": [
        {"cards": [{"content": "no type"}]}
    ]}]}
    with pytest.raises(LovelaceError, match="type"):
        await lovelace.set_dashboard_config(None, bad)


# --------------------------------------------------------------------------
# Backups: list + restore
# --------------------------------------------------------------------------

async def test_restore_dashboard_round_trip(fake_ws):
    original = {"views": [{"title": "Home", "cards": []}]}
    assert fake_ws.config_store[None] == original

    # Mutate (creates a backup of the original), then change again.
    await lovelace.add_card(None, view=0, card={"type": "markdown", "content": "1"})
    backups = lovelace.list_dashboard_backups(None)
    assert len(backups) == 1

    # Restore newest backup -> dashboard goes back to original.
    result = await lovelace.restore_dashboard(None)
    assert result["restored_from"] == backups[0]["backup_id"]
    assert fake_ws.config_store[None] == original


async def test_restore_no_backups_errors(fake_ws):
    with pytest.raises(LovelaceError, match="[Nn]o backups"):
        await lovelace.restore_dashboard("test-dash")


# --------------------------------------------------------------------------
# Strategy configs
# --------------------------------------------------------------------------

STRATEGY_CONFIG = {"strategy": {"type": "map"}}


async def test_set_dashboard_config_accepts_strategy(fake_ws):
    """Raw set must accept strategy configs (no 'views' key)."""
    result = await lovelace.set_dashboard_config(None, STRATEGY_CONFIG)
    assert result["success"] is True
    assert fake_ws.config_store[None] == STRATEGY_CONFIG


async def test_restore_round_trips_strategy(fake_ws):
    """Save strategy → mutate (triggers backup of strategy) → restore → back to strategy."""
    await lovelace.set_dashboard_config(None, STRATEGY_CONFIG)
    # Mutating triggers _backup_current which backs up the current (strategy) config.
    await lovelace.set_dashboard_config(
        None, {"views": [{"cards": []}]}
    )
    # The newest backup is the pre-mutation strategy config.
    backups = lovelace.list_dashboard_backups(None)
    strategy_backup_id = backups[-1]["backup_id"]
    result = await lovelace.restore_dashboard(
        None, backup_id=strategy_backup_id
    )
    assert result["restored_from"] == strategy_backup_id
    assert fake_ws.config_store[None] == STRATEGY_CONFIG


async def test_add_card_rejects_strategy_dashboard(fake_ws):
    """High-level helpers must reject strategy configs with clear message."""
    fake_ws.config_store[None] = STRATEGY_CONFIG
    with pytest.raises(LovelaceError, match="strategy"):
        await lovelace.add_card(None, view=0, card={"type": "markdown"})


async def test_validation_allows_strategy_without_views(fake_ws):
    """_validate_config must not require 'views' for strategy configs."""
    result = await lovelace.set_dashboard_config(
        None, STRATEGY_CONFIG, dry_run=True
    )
    assert result["dry_run"] is True


async def test_set_dashboard_config_strategy_backup_works(fake_ws):
    """Backup of a strategy config before overwrite succeeds."""
    fake_ws.config_store[None] = STRATEGY_CONFIG
    result = await lovelace.set_dashboard_config(
        None, {"views": [{"cards": []}]}
    )
    assert result["success"] is True
    # Backup of the strategy config was written.
    backup_dir = app_config.HASS_MCP_BACKUP_DIR
    files = os.listdir(backup_dir)
    assert len(files) >= 1
    backups = [f for f in files if f.startswith("lovelace_default_")]
    with open(os.path.join(backup_dir, backups[-1])) as f:
        backed_up = json.load(f)
    assert backed_up == STRATEGY_CONFIG


# --------------------------------------------------------------------------
# Default dashboard mode detection via dashboards/list
# --------------------------------------------------------------------------


async def test_default_dashboard_storage_when_no_lovelace_entry(fake_ws):
    """No 'lovelace' entry in dashboards/list → default is storage-backed."""
    # No "lovelace" dashboard → dashboards[None] = LovelaceStorage.
    result = await lovelace.set_dashboard_config(
        None, {"views": [{"cards": []}]}
    )
    assert result["success"] is True


async def test_default_dashboard_yaml_when_lovelace_entry_is_yaml(fake_ws):
    """'lovelace' entry with mode 'yaml' → default is YAML-backed."""
    fake_ws.dashboards.append(
        {"id": "y", "url_path": "lovelace", "title": "Default", "mode": "yaml"}
    )
    with pytest.raises(LovelaceError, match="YAML"):
        await lovelace.set_dashboard_config(None, {"views": []})


async def test_default_dashboard_storage_when_lovelace_entry_is_storage(fake_ws):
    """'lovelace' entry with mode 'storage' → default is storage-backed."""
    fake_ws.dashboards.append(
        {"id": "s", "url_path": "lovelace", "title": "Default", "mode": "storage"}
    )
    result = await lovelace.set_dashboard_config(
        None, {"views": [{"cards": []}]}
    )
    assert result["success"] is True


async def test_named_yaml_dashboard_still_rejected(fake_ws):
    """Named YAML dashboards should still be detected and rejected."""
    with pytest.raises(LovelaceError, match="YAML"):
        await lovelace.set_dashboard_config("yaml-dash", {"views": []})


# --------------------------------------------------------------------------
# Concurrent edits and stale snapshot detection
# --------------------------------------------------------------------------


async def test_concurrent_adds_both_succeed(fake_ws):
    """Two concurrent add_card calls must not silently lose one."""
    fake_ws.config_store[None] = {"views": [{"cards": []}]}
    await asyncio.gather(
        lovelace.add_card(None, view=0, card={"type": "a"}),
        lovelace.add_card(None, view=0, card={"type": "b"}),
    )
    cfg = fake_ws.config_store[None]
    types = [c["type"] for c in cfg["views"][0]["cards"]]
    assert "a" in types
    assert "b" in types
    assert len(types) == 2


async def test_stale_snapshot_detected_external_modification(fake_ws):
    """If config changes externally between read and write, detect it."""
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "a"}]}]}

    # Read produces a snapshot hash.
    cfg = await lovelace._load_for_edit(None)
    # Simulate external modification.
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "b"}]}]}

    with pytest.raises(LovelaceError, match="modified"):
        await lovelace.set_dashboard_config(None, cfg)


async def test_direct_set_dashboard_no_stale_check(fake_ws):
    """Direct set_dashboard_config (no _snapshot_hash) skips stale check."""
    # A config from the user (MCP tool) has no _snapshot_hash stamp.
    cfg = {"views": [{"cards": [{"type": "x"}]}]}
    # External modification should NOT block a direct set.
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "y"}]}]}
    result = await lovelace.set_dashboard_config(None, cfg)
    assert result["success"] is True
    assert fake_ws.config_store[None] == cfg


async def test_remove_view_locked_against_concurrent_card_op(fake_ws):
    """Lock serializes view mutations and card ops on same dashboard."""
    fake_ws.config_store[None] = {
        "views": [
            {"title": "A", "cards": [{"type": "a"}]},
            {"title": "B", "cards": [{"type": "b"}]},
        ]
    }
    await asyncio.gather(
        lovelace.remove_view(None, view="B"),
        lovelace.add_card(None, view="A", card={"type": "c"}),
    )
    cfg = fake_ws.config_store[None]
    assert len(cfg["views"]) == 1
    types = [c["type"] for c in cfg["views"][0]["cards"]]
    assert "a" in types
    assert "c" in types


async def test_stale_snapshot_reported_on_identical_content_from_lovelace_info(fake_ws):
    """Regression: the stale check re-reads via get_dashboard_config (which
    pops 'note'), so the hash comparison must be consistent with how
    _load_for_edit stamps it."""
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "a"}]}]}
    cfg = await lovelace._load_for_edit(None)
    # No external change → snapshot should NOT be stale.
    result = await lovelace.set_dashboard_config(None, cfg)
    assert result["success"] is True


# --------------------------------------------------------------------------
# Lock canonicalization: None (default) ≡ "lovelace" dashboard
# --------------------------------------------------------------------------


async def test_default_alias_lovelace_shares_lock_key(fake_ws):
    """HA resolves an omitted url_path to the 'lovelace' dashboard when one
    exists — None and 'lovelace' must resolve to the SAME lock, or
    interleaved edits on the default dashboard could silently overwrite."""
    fake_ws.dashboards.append(
        {"id": "lov", "url_path": "lovelace", "title": "Default", "mode": "storage"}
    )
    assert lovelace._lock_for(None) is lovelace._lock_for("lovelace")


async def test_default_lock_key_is_stable_when_dashboard_list_fails(
    fake_ws, monkeypatch
):
    """A transient mode lookup failure must not split the default dashboard
    across two locks and reintroduce lost updates."""
    first = lovelace._lock_for(None)

    async def fail_dashboard_list(message_type, **payload):
        if message_type == "lovelace/dashboards/list":
            raise HassWebSocketError("transient dashboard list failure")
        return await fake_ws(message_type, **payload)

    monkeypatch.setattr("app.lovelace.call_ws", fail_dashboard_list)
    second = lovelace._lock_for(None)

    assert first is second


async def test_interleaved_alias_edits_both_succeed(fake_ws):
    """Regression: add_card(None) racing add_card('lovelace') on the same
    (default) dashboard must both succeed — a torn read-modify-write
    previously returned success twice while losing one card."""
    fake_ws.dashboards.append(
        {"id": "lov", "url_path": "lovelace", "title": "Default", "mode": "storage"}
    )
    fake_ws.config_store["lovelace"] = {"views": [{"cards": []}]}
    await asyncio.gather(
        lovelace.add_card(None, view=0, card={"type": "a"}),
        lovelace.add_card("lovelace", view=0, card={"type": "b"}),
    )
    cfg = fake_ws.config_store["lovelace"]
    types = [c["type"] for c in cfg["views"][0]["cards"]]
    assert "a" in types
    assert "b" in types
    assert len(types) == 2


async def test_raw_set_dashboard_config_takes_the_lock(fake_ws):
    """Regression: raw set_dashboard_config must take the same per-dashboard
    lock as the high-level helpers — a raw write between a helper's read and
    save would otherwise be silently overwritten."""
    fake_ws.config_store[None] = {"views": [{"cards": [{"type": "orig"}]}]}
    raw_cfg = {"views": [{"cards": [{"type": "raw"}]}]}
    lock = lovelace._lock_for(None)
    async with lock:  # a concurrent high-level edit holds the lock...
        task = asyncio.create_task(lovelace.set_dashboard_config(None, raw_cfg))
        for _ in range(200):
            if task.done():
                break
            await asyncio.sleep(0)
        assert not task.done(), "raw set completed while the lock was held"
    # ...once released, the raw write lands.
    await task
    assert fake_ws.config_store[None] == raw_cfg


async def test_restore_dashboard_takes_the_lock(fake_ws):
    """Regression: restore_dashboard saves through the same per-dashboard
    lock — it must not interleave between a helper's read and save."""
    original = {"views": [{"title": "Home", "cards": []}]}
    assert fake_ws.config_store[None] == original
    await lovelace.add_card(None, view=0, card={"type": "markdown", "content": "1"})
    assert lovelace.list_dashboard_backups(None)

    lock = lovelace._lock_for(None)
    async with lock:
        task = asyncio.create_task(lovelace.restore_dashboard(None))
        for _ in range(200):
            if task.done():
                break
            await asyncio.sleep(0)
        assert not task.done(), "restore completed while the lock was held"
    await task
    assert fake_ws.config_store[None] == original
