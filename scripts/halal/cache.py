"""Persistent cache for halal resolutions.

Resolving an outlet means fetching that chain's store page — so an uncached
search crawls one page per chain outlet nearby, and a fresh process starts
from nothing. That's slow for the user and rude to the chains' servers.

Two properties matter more than speed, though:

* **A TTL, not permanent storage.** Halal status genuinely changes — KFC
  Mitcham dropped it in February 2025 — so a cached verdict has to expire.
  Fourteen days is short enough that a change surfaces quickly and long
  enough that repeat searches are cheap.
* **`unverified` gets a much shorter TTL, not zero.** It usually means a
  fetch failed or a source had nothing to say, and freezing that for a
  fortnight would be wrong — but never caching it at all has its own real
  cost: most chain outlets in a dense area resolve to unverified (no HMC/HFA
  listing, no per-outlet source), and every one of them re-runs its full
  live network cascade on every single search, forever, with zero benefit
  from ever having searched that location before. Measured at Wimbledon
  station: 8 of 13 nearby chains resolved unverified, each costing 1.2-2.4s
  of live requests, on a search meant to feel instantaneous. A short TTL
  (a few hours) gets the caching win for repeat searches at a popular
  location without freezing a transient failure for two weeks.
"""
from __future__ import annotations

import json
import pathlib
import time

CACHE_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "db" / "halal_cache.json"
TTL_SECONDS = 14 * 24 * 3600
#: Short on purpose — see "unverified gets a much shorter TTL" above. Long
#: enough that a burst of searches at the same busy location (a train
#: station, a high street) only pays the live-resolution cost once; short
#: enough that a source coming back online, or a chain newly gaining
#: certification, surfaces the same day rather than two weeks later.
UNVERIFIED_TTL_SECONDS = 6 * 3600


def _key(chain_id: str, postcode: str | None, name: str) -> str:
    return f"{chain_id}|{(postcode or '').replace(' ', '').upper()}|{name.strip().lower()}"


class HalalCache:
    def __init__(self, path: pathlib.Path = CACHE_PATH, ttl: int = TTL_SECONDS,
                 unverified_ttl: int = UNVERIFIED_TTL_SECONDS):
        self.path, self.ttl, self.unverified_ttl = path, ttl, unverified_ttl
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
        ttl = self.unverified_ttl if entry["status"] == "unverified" else self.ttl
        if time.time() - entry.get("stored_at", 0) > ttl:
            return None
        return entry["status"], entry["tier"]

    def put(self, chain_id: str, postcode: str | None, name: str,
            status: str, tier: str) -> None:
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
