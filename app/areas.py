"""
Per-entity area enrichment for Home Assistant.

Home Assistant's REST `/api/states` endpoint does not include area data;
area information lives in HA's area registry which is only directly
exposed over WebSocket. To stay REST-only and keep the existing httpx
client + long-lived token contract, this module uses HA's `/api/template`
endpoint to render a single Jinja that emits `entity_id<US>area_name`
for every entity. Server-side, `area_name(entity_id)` walks the
entity → device → area chain automatically (matches HA's own behavior).

The mapping is cached in memory with a short TTL (the area registry
rarely changes; users tolerate a few minutes of staleness).
"""

import asyncio
import logging
import time
from typing import Dict, Optional

import httpx

from app.config import HA_URL, get_ha_headers

logger = logging.getLogger(__name__)

# Default cache duration. Area registry changes very rarely (a user
# adding/renaming a room), so this can be aggressive.
_DEFAULT_TTL_SECONDS = 300

# ASCII unit separator — used to delimit entity_id from area name in the
# template output. Won't appear in entity IDs (they're [a-z0-9_.] only) or
# in any sensible area name.
_US = "\x1f"

# Single Jinja that emits one line per entity. We embed the entity loop
# in the template so HA does the work server-side; one REST call returns
# the entire entity→area map regardless of how many entities are defined.
_AREA_TEMPLATE = (
    "{%- set ns = namespace(items=[]) -%}\n"
    "{%- for s in states -%}\n"
    "  {%- set a = area_name(s.entity_id) -%}\n"
    f"  {{%- set ns.items = ns.items + [(s.entity_id ~ '{_US}' ~ (a or ''))] -%}}\n"
    "{%- endfor -%}\n"
    "{{ ns.items | join('\\n') }}\n"
)


class AreaCache:
    """In-memory TTL cache of {entity_id: area_name | None}.

    Single-flight: concurrent get/all calls during a refresh share one
    HTTP request rather than stampeding the HA API.
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS):
        self._cache: Dict[str, Optional[str]] = {}
        self._expires_at: float = 0.0
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def get_all(self, client: httpx.AsyncClient) -> Dict[str, Optional[str]]:
        """Return the full entity→area map, refreshing if expired."""
        if time.monotonic() < self._expires_at:
            return self._cache
        async with self._lock:
            # Double-check inside the lock — another coroutine may have
            # refreshed while we were waiting.
            if time.monotonic() < self._expires_at:
                return self._cache
            await self._refresh(client)
        return self._cache

    async def get(self, client: httpx.AsyncClient, entity_id: str) -> Optional[str]:
        """Return the area name for one entity, or None if no area assigned."""
        all_areas = await self.get_all(client)
        return all_areas.get(entity_id)

    def invalidate(self) -> None:
        """Discard the cache. Next get/get_all refreshes from HA. If that
        refresh fails, callers see None rather than stale data."""
        self._cache = {}
        self._expires_at = 0.0

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        """Re-fetch the area map via /api/template."""
        try:
            response = await client.post(
                f"{HA_URL}/api/template",
                headers=get_ha_headers(),
                json={"template": _AREA_TEMPLATE},
                timeout=30,
            )
            response.raise_for_status()
        except Exception as e:
            # Don't crash callers; serve stale cache and back off retry for
            # a minute to avoid hammering a flaky HA.
            logger.warning("area cache refresh failed: %s", e)
            self._expires_at = time.monotonic() + 60
            return

        cache: Dict[str, Optional[str]] = {}
        for line in response.text.splitlines():
            # Defensive: skip blank lines and entries the template produced
            # without our separator.
            if _US not in line:
                continue
            entity_id, area = line.split(_US, 1)
            entity_id = entity_id.strip()
            if not entity_id:
                continue
            cache[entity_id] = area.strip() or None

        self._cache = cache
        self._expires_at = time.monotonic() + self._ttl
        logger.debug("area cache refreshed: %d entities, %d with areas",
                     len(cache), sum(1 for a in cache.values() if a))


# Module-level singleton. Tests can reset via .invalidate() / monkeypatch.
_cache = AreaCache()


async def get_area(client: httpx.AsyncClient, entity_id: str) -> Optional[str]:
    return await _cache.get(client, entity_id)


async def get_all_areas(client: httpx.AsyncClient) -> Dict[str, Optional[str]]:
    return await _cache.get_all(client)


def invalidate_cache() -> None:
    _cache.invalidate()
