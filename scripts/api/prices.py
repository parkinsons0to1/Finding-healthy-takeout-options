"""Prices — the weakest column in MacroMeter, handled honestly.

Chain prices in the UK are set per franchise and are not centrally published.
The chains' own click-and-collect APIs carry true per-store prices but sit
behind ordering sessions (Popeyes, Greggs) or app-client auth (KFC, Burger
King); Just Eat's menu endpoint exists but returns 401 without a token, and its
prices are delivery-inflated anyway. That work is the top of the Phase 1
backlog.

Until those adapters land, prices here are **typical UK walk-in estimates** and
every quote says so via `basis`. That matters because price drives the ranking
more than nutrition does: a wrong price moves an item further up or down the
board than a wrong macro would. The UI must never render an estimate the same
way it renders a scraped price, and `as_of` exists so a stale table is visible
rather than silently trusted.
"""
from __future__ import annotations

import dataclasses
import re

ESTIMATE_AS_OF = "2026-07-28"


def _normalise(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split())


@dataclasses.dataclass(frozen=True)
class PriceQuote:
    price_gbp: float
    basis: str          # 'collection' | 'delivery' | 'estimated' | 'community'
    as_of: str
    source: str = ""


#: chain_id -> {item name (lowercased) -> price in GBP}
ESTIMATED_PRICES: dict[str, dict[str, float]] = {
    "mcdonalds": {
        "hamburger": 1.49, "cheeseburger": 1.99, "mayo chicken": 1.59,
        "double cheeseburger": 3.19, "big mac": 4.99,
        "quarter pounder with cheese": 5.09,
        "double quarter pounder with cheese": 6.29,
        "mccrispy®": 5.69, "spicy mccrispy®": 5.79,
        "cheese & bacon mccrispy®": 6.19, "hot honey mccrispy®": 6.19,
        "big arch": 7.99, "big arch® with bacon": 8.79,
        "sausage & egg mcmuffin": 3.79, "double sausage & egg mcmuffin": 4.49,
        "filet-o-fish®": 4.29, "double filet-o-fish®": 5.49,
        "crispy chicken & bacon salad": 5.49, "vegan mcplant®": 4.99,
        "mcchicken sandwich": 4.89,
        "breakfast wrap with ketchup": 4.99,
        "breakfast wrap with brown sauce": 4.99,
    },
    "kfc": {
        "original recipe chicken (per piece, average)": 2.29,
        "tender (per piece, average)": 1.99,
        "fillet burger": 5.99, "zinger burger": 5.99,
        "fillet tower burger": 6.79, "large popcorn chicken": 5.49,
        "zinger stacker burger": 7.49, "mini fillet": 2.19,
    },
    "popeyes": {
        "the classic chicken sandwich": 6.49, "the spicy chicken sandwich": 6.49,
        "the deluxe chicken sandwich": 7.29, "6 hot wings": 6.49,
        "12 hot wings": 10.99, "8 hot wings": 8.49,
        "2 piece signature louisiana chicken": 6.99,
        "3 piece signature louisiana chicken": 8.49,
        "6 cajun citrus wings": 6.99, "8 cajun citrus wings": 8.99,
    },
    "greggs": {
        "sausage roll": 1.30, "vegan sausage roll": 1.30,
        "chicken bake": 2.10, "hot chicken bake": 2.10, "steak bake": 2.10,
        "bread pack tuna crunch": 3.60, "baguette chicken mayonnaise": 3.85,
        "baguette chicken club": 3.95, "hard boiled egg (2 pack)": 1.20,
        "overnight oats": 2.05,
    },
    # Papa John's prices vary hugely by size and by their near-permanent
    # promotions; these are typical medium/large collection prices.
    "papa_johns": {
        "cheese tomato authentic thin crust medium": 15.99,
        "cheese tomato authentic thin crust large": 18.99,
        "all the meats authentic thin crust medium": 19.99,
        "all the meats authentic thin crust large": 22.99,
        "chicken sweetcorn authentic thin crust medium": 19.99,
        "chicken sweetcorn authentic thin crust large": 22.99,
        "tandoori spice authentic thin crust medium": 19.99,
        "tandoori spice authentic thin crust large": 22.99,
        "double pepperoni authentic thin crust medium": 18.99,
        "double pepperoni authentic thin crust large": 21.99,
        "bbq chicken classic authentic thin crust medium": 19.99,
        "chicken club authentic thin crust medium": 19.99,
    },
    # Chipotle prices are per whole item; the PDF is per-ingredient, so these
    # cover the built items people actually buy.
    "chipotle": {
        "chicken": 9.45, "steak": 10.45, "barbacoa": 10.45,
        "carnitas": 9.95, "sofritas (braised tofu)": 8.95,
    },
    "five_guys": {
        "hamburger": 9.75, "cheeseburger": 10.75, "bacon burger": 11.25,
        "bacon cheeseburger": 12.25, "little hamburger": 7.75,
        "little cheeseburger": 8.50, "little bacon burger": 8.75,
        "little bacon cheeseburger": 9.50, "hot dog": 7.75,
        "cheese dog": 8.50, "bacon dog": 8.75, "blt": 7.25,
        "veggie sandwich": 6.75, "grilled cheese": 6.25,
    },
    "starbucks": {
        "egg bites": 4.45, "protein box": 6.25,
        "chicken & bacon panini": 5.95, "tuna melt panini": 5.75,
        "ham & cheese toastie": 5.25, "bacon roll": 4.45,
    },
    "krispy_kreme": {
        "original glazed": 2.30, "chocolate dreamcake": 3.10,
        "strawberries & kreme": 3.10, "black americano 12oz": 2.75,
    },
    "subway": {
        "chicken breast": 4.99, "chicken tikka": 4.79,
        "rotisserie style chicken": 4.99, "steak & cheese": 5.29,
        "tuna": 4.99, "meatball marinara (pork & beef)": 4.79,
        "big breakwich": 4.49, "ham": 4.29,
    },
}


def price_for(chain_id: str, item_name: str) -> PriceQuote | None:
    table = ESTIMATED_PRICES.get(chain_id)
    if not table:
        return None
    key = _normalise(item_name)
    price = table.get(key) or {_normalise(n): p for n, p in table.items()}.get(key)
    if price is None:
        # Tolerate minor naming drift, but only on whole-word matches. A naive
        # substring test makes "2 hot wings" match "12 hot wings" and price a
        # 2-piece at the 12-piece price, which badly distorts the ranking.
        key_words = set(key.split())
        for name, p in table.items():
            name_words = set(_normalise(name).split())
            if key_words == name_words:
                price = p
                break
    if price is None:
        return None
    return PriceQuote(price, "estimated", ESTIMATE_AS_OF,
                      "typical UK walk-in price — verify in store")
