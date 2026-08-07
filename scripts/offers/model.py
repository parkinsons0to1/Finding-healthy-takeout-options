"""Limited-time offers and bundles — a different thing from a discount.

A **discount** is a percentage off a list price ("20% off your first app
order"), so it modifies an item we already know about. An **offer** is its own
priced product assembled from menu items ("10 Tenders Bucket, £7.99"). It has
no list price to discount, and its macros exist only as the sum of its parts.
Modelling offers as discounts loses this, which matters because bundles are
routinely the best protein-per-pound available: KFC's 10-tender bucket is
131 g of protein for £7.99 — 16.4 g/£ at 42% protein-kcal, better than any
standard menu item and competitive with a supermarket meal deal.

Two rules keep offers from doing damage:

* **Composition must resolve.** An offer's macros are derived from real menu
  rows (10 x the per-piece tender). If a component can't be matched to a
  scraped item, the offer is dropped rather than published with guessed
  numbers — an invented bundle would outrank everything precisely because it
  looks too good.
* **Expiry is enforced, not decorative.** Offers are limited-time by
  definition, and a price the user cannot actually get is worse than no
  price. An offer past `valid_to`, or unverified for too long, is withheld.
"""
from __future__ import annotations

import dataclasses
import datetime
import re

#: An offer whose last verification is older than this is treated as stale:
#: LTOs turn over fast, so silence beats a confidently expired price.
MAX_VERIFICATION_AGE_DAYS = 21


@dataclasses.dataclass(frozen=True)
class Component:
    """One line of a bundle: how many of which menu item."""
    item_matcher: str        # substring matched against scraped item names
    quantity: int


@dataclasses.dataclass(frozen=True)
class Offer:
    offer_id: str
    chain_id: str
    title: str
    price_gbp: float
    components: tuple[Component, ...]
    source: str
    source_url: str
    last_verified: str                  # ISO date
    valid_to: str | None = None         # ISO date, None = open-ended
    availability: str = "national"      # national | app_only | store_specific
    basis: str = "curated"              # scraped | curated | community
    notes: str = ""

    def is_live(self, today: datetime.date | None = None) -> bool:
        today = today or datetime.date.today()
        if self.valid_to:
            try:
                if datetime.date.fromisoformat(self.valid_to) < today:
                    return False
            except ValueError:
                return False
        try:
            age = (today - datetime.date.fromisoformat(self.last_verified)).days
        except ValueError:
            return False
        return age <= MAX_VERIFICATION_AGE_DAYS


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _find_item(menu: list[dict], matcher: str) -> dict | None:
    """Best menu row for a component matcher, preferring per-unit rows.

    Per-piece rows are what make a bundle computable: "Tender (per piece,
    average)" x 10 is exact, whereas matching a different multi-pack row would
    silently multiply an already-multiplied quantity.
    """
    want = _normalise(matcher)
    candidates = [i for i in menu
                  if i.get("kcal") and i.get("protein_g") is not None
                  and want in _normalise(i.get("name", ""))]
    if not candidates:
        return None
    per_unit = [i for i in candidates if "per piece" in i["name"].lower()]
    if per_unit:
        return per_unit[0]
    return min(candidates, key=lambda i: len(i["name"]))


def expand(offer: Offer, menu: list[dict]) -> dict | None:
    """Turn an offer into a synthetic menu item, or None if unresolvable."""
    kcal = protein = 0.0
    resolved: list[str] = []
    for component in offer.components:
        row = _find_item(menu, component.item_matcher)
        if row is None:
            return None          # never guess a bundle's macros
        kcal += float(row["kcal"]) * component.quantity
        protein += float(row["protein_g"]) * component.quantity
        resolved.append(f"{component.quantity}x {row['name']}")
    if kcal <= 0:
        return None

    return {
        "chain_id": offer.chain_id,
        "name": offer.title,
        "item_id": offer.offer_id,
        "category": "offer",
        "kcal": round(kcal, 1),
        "protein_g": round(protein, 1),
        "offer_price_gbp": offer.price_gbp,
        "is_offer": True,
        "offer_basis": offer.basis,
        "offer_availability": offer.availability,
        "offer_valid_to": offer.valid_to,
        "offer_components": resolved,
        "source": offer.source,
        "source_url": offer.source_url,
        "vegetarian": False,
        "vegan": False,
    }
