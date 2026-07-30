"""Persistent cache for halal resolutions.

Resolving an outlet means fetching that chain's store page — so an uncached
search crawls one page per chain outlet nearby, and a fresh process starts
from nothing. That's slow for the user and rude to the chains' servers.

Two properties matter more than speed, though:

* **A TTL, not permanent storage.** Halal status genuinely changes — KFC
  Mitcham dropped it in February 2025 — so a cached verdict has to expire.
  Fourteen days is short enough that a change surfaces quickly and long
  enough that repeat searches are cheap.
* **Never cache `unverified`.** It usually means a fetch failed or a source
  had nothing to say; caching it would freeze a transient failure into a
  fortnight of "we don't know" for every future user of that outlet.
"""
from __future__ import annotations

import json
import pathlib
import time

CACHE_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "db" / "halal_cache.json"
TTL_SECONDS = 14 * 24 * 3600


def _key(chain_id: str, postcode: str | None, name: str) -> str:
    return f"{chain_id}|{(postcode or '').replace(' ', '').upper()}|{name.strip().lower()}"


class HalalCache:
    def __init__(self, path: pathlib.Path = CACHE_PATH, ttl: int = TTL_SECONDS):
        self.path, self.ttl = path, ttl
        self._data: dict[str, dict] = {}
        self._dirty = False
        if path.exists():
            try:
                self._data = json.loads(path.read_text()).get("entries", {})
            except Exception:
                self._data = {}

    def get(self, chain_id: str, postcode: str | None, name: str) -> tuple[str, str] | None:
        entry = self._data.get(_key(chain_id, postcode, name))
        if not entry:
            return None
        if time.time() - entry.get("stored_at", 0) > self.ttl:
            return None
        return entry["status"], entry["tier"]

    def put(self, chain_id: str, postcode: str | None, name: str,
            status: str, tier: str) -> None:
        if status == "unverified":
            return          # see module docstring — don't freeze a failure
        self._data[_key(chain_id, postcode, name)] = {
            "status": status, "tier": tier, "stored_at": time.time(),
            "chain_id": chain_id, "postcode": postcode, "name": name}
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"ttl_seconds": self.ttl, "entries": self._data}, indent=1))
        self._dirty = False

    def __len__(self) -> int:
        return len(self._data)
