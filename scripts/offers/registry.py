"""All current offers: scraped, curated, and community-reported.

Three tiers, in descending confidence:

* **scraped** — parsed from the chain's own deals page. Self-refreshing.
* **curated** — entered by hand from a chain's app or advertising, where no
  scrapeable page exists (app-only deals are the common case).
* **community** — reported by users. Cheapest way to cover app-only and
  regional offers, and the only realistic route to the long tail — but
  unaudited, so it is labelled as such and expires fastest.

`live_offers()` is the only entry point the app should use: it merges the
tiers, drops anything expired or stale, and drops anything whose composition
can't be resolved against real scraped nutrition.
"""
from __future__ import annotations

import datetime
import json
import pathlib

from .model import Component, Offer, expand
from .sources import kfc_deals

DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "db"
COMMUNITY_PATH = DB / "offers_community.json"
CACHE_PATH = DB / "offers_scraped.json"

SCRAPERS = {"kfc": kfc_deals}

#: Hand-entered offers, mostly app-only deals with no scrapeable page.
#: `last_verified` is load-bearing — see model.MAX_VERIFICATION_AGE_DAYS.
CURATED: list[Offer] = [
    Offer(
        offer_id="gdk_og_first_app",
        chain_id="gdk",
        title="Original Doner Kebab — 50% off first app order",
        price_gbp=4.25,
        components=(Component("Original German Doner Kebab", 1),),
        source="GDK app promotion (user-reported)",
        source_url="https://www.gdk.com/",
        last_verified="2026-07-28",
        availability="app_only",
        basis="curated",
        notes="first app order only",
    ),
]


def _offer_from_dict(d: dict) -> Offer:
    return Offer(
        offer_id=d["offer_id"], chain_id=d["chain_id"], title=d["title"],
        price_gbp=float(d["price_gbp"]),
        components=tuple(Component(c["item_matcher"], int(c["quantity"]))
                         for c in d["components"]),
        source=d.get("source", "community report"),
        source_url=d.get("source_url", ""),
        last_verified=d.get("last_verified", ""),
        valid_to=d.get("valid_to"),
        availability=d.get("availability", "national"),
        basis=d.get("basis", "community"),
        notes=d.get("notes", ""))


def load_community() -> list[Offer]:
    if not COMMUNITY_PATH.exists():
        return []
    try:
        raw = json.loads(COMMUNITY_PATH.read_text()).get("offers", [])
        return [_offer_from_dict(d) for d in raw]
    except Exception:
        return []


def add_community_offer(offer: Offer) -> None:
    existing = load_community()
    kept = [o for o in existing if o.offer_id != offer.offer_id]
    kept.append(offer)
    COMMUNITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMMUNITY_PATH.write_text(json.dumps({"offers": [
        {"offer_id": o.offer_id, "chain_id": o.chain_id, "title": o.title,
         "price_gbp": o.price_gbp,
         "components": [{"item_matcher": c.item_matcher, "quantity": c.quantity}
                        for c in o.components],
         "source": o.source, "source_url": o.source_url,
         "last_verified": o.last_verified, "valid_to": o.valid_to,
         "availability": o.availability, "basis": o.basis, "notes": o.notes}
        for o in kept]}, indent=1))


def refresh_scraped(s=None) -> list[Offer]:
    """Re-scrape every chain that publishes a deals page, and cache."""
    found: list[Offer] = []
    for module in SCRAPERS.values():
        try:
            found.extend(module.fetch(s))
        except Exception:
            continue
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({
        "refreshed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "offers": [{"offer_id": o.offer_id, "chain_id": o.chain_id,
                    "title": o.title, "price_gbp": o.price_gbp,
                    "components": [{"item_matcher": c.item_matcher,
                                    "quantity": c.quantity} for c in o.components],
                    "source": o.source, "source_url": o.source_url,
                    "last_verified": o.last_verified, "valid_to": o.valid_to,
                    "availability": o.availability, "basis": o.basis,
                    "notes": o.notes} for o in found]}, indent=1))
    return found


def load_scraped() -> list[Offer]:
    if not CACHE_PATH.exists():
        return []
    try:
        return [_offer_from_dict(d)
                for d in json.loads(CACHE_PATH.read_text()).get("offers", [])]
    except Exception:
        return []


def all_offers() -> list[Offer]:
    return load_scraped() + CURATED + load_community()


def live_offers(chain_id: str | None = None,
                today: datetime.date | None = None) -> list[Offer]:
    """Offers that are in date and recently verified."""
    offers = [o for o in all_offers() if o.is_live(today)]
    if chain_id:
        offers = [o for o in offers if o.chain_id == chain_id]
    return offers


def expanded_for_chain(chain_id: str, menu: list[dict]) -> list[dict]:
    """Synthetic menu rows for a chain's live offers, macros derived from
    `menu`. Offers whose composition doesn't resolve are silently dropped —
    see model.expand."""
    rows = []
    for offer in live_offers(chain_id):
        row = expand(offer, menu)
        if row:
            rows.append(row)
    return rows
