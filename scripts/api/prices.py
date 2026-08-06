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
    "wingstop": {
        "wings (10 pieces) 462g": 12.95, "wings (8 pieces) 370g": 10.95,
        "wings (12 pieces) 555g": 14.95, "boneless (10 pieces) 220g": 11.45,
        "boneless (8 pieces) 176g": 9.45, "tenders (5 pieces) 225g": 11.95,
        "tenders (3 pieces) 135g": 8.95,
    },
    "slim_chickens": {
        "3 tenders": 6.95, "4 tenders": 8.45, "5 tenders": 9.95,
        "7 tenders": 12.95, "chicken sandwich": 8.95,
        "buffalo chicken sandwich": 9.45,
    },
    "pepes_piri_piri": {
        "1/4 chicken": 5.95, "1/2 chicken": 9.45, "whole chicken": 16.95,
        "chicken wrap": 6.45, "peri peri wings": 6.95,
    },
    "wimpy": {
        "wimpy cheeseburger": 5.75, "original halfpounder": 9.25,
        "quarterpounder": 7.25, "bacon cheeseburger": 6.95,
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
    "burger_king": {
        "whopper": 6.49, "double whopper": 8.29, "bacon double xl": 8.99,
        "chicken royale": 6.29, "double chicken royale": 8.49,
        "bacon double cheeseburger": 3.99, "double cheeseburger": 3.49,
        "cheeseburger": 2.19, "hamburger": 1.99,
        "royale with cheese": 6.99, "steakhouse angus": 8.49,
    },
    "nandos": {
        "1/4 chicken": 6.20, "1/2 chicken": 10.75, "whole chicken": 17.50,
        "chicken butterfly": 9.95, "5 chicken wings": 8.95,
        "3 chicken thighs": 8.20, "chicken breast fillet": 9.50,
        "double chicken breast burger": 11.95,
    },
    "taco_bell": {
        "crispy chicken burrito": 5.49, "bbq habanero burrito": 5.49,
        "crunchwrap supreme": 5.79, "quesadilla chicken": 5.49,
        "crunchy taco": 2.49, "soft taco": 2.49, "burrito supreme": 5.99,
    },
    "wetherspoons": {
        "8oz sirloin steak": 12.49, "gammon steak": 8.99,
        "chicken breast burger": 7.99, "mixed grill": 13.99,
        "beef burger": 7.49, "chicken tikka masala": 9.49,
        "small mixed grill": 10.99, "8oz rump steak": 10.99,
    },
    "harvester": {
        "half rotisserie chicken": 13.99, "rotisserie chicken": 13.99,
        "gammon steak": 13.49, "8oz rump steak": 16.99,
        "chicken skewer": 12.99, "ultimate combo": 18.99,
    },
    "toby_carvery": {
        "large carvery": 12.99, "regular carvery": 10.99,
        "small carvery": 8.99, "turkey": 10.99, "gammon": 10.99, "beef": 11.99,
    },
    "wagamama": {
        "chicken katsu curry": 14.50, "chicken ramen": 14.95,
        "yaki soba chicken": 13.95, "grilled chicken": 13.50,
        "teriyaki chicken donburi": 14.95, "shirodashi chicken ramen": 15.25,
    },
    "pret": {
        "chicken caesar & bacon baguette": 6.25,
        "chicken & avocado salad": 6.75, "posh cheddar & pickle": 4.95,
        "egg protein pot": 2.75, "chicken protein pot": 3.50,
        "tuna baguette": 5.75, "chicken avo baguette": 6.25,
    },
    "itsu": {
        "chicken teriyaki rice'bowl": 8.49, "chicken katsu curry": 8.99,
        "salmon sashimi": 7.99, "chicken gyoza": 5.99,
        "tuna sashimi": 7.99, "chicken noodle soup": 6.49,
    },
    "leon": {
        "love burger": 8.45, "grilled chicken box": 9.45,
        "chicken shawarma wrap": 8.25, "chipotle chicken burrito": 8.95,
    },
    "tortilla": {
        "burrito chicken": 9.45, "burrito steak": 10.25,
        "naked burrito chicken": 9.45, "tacos chicken": 9.25,
        "quesadilla chicken": 9.45,
    },
    "dominos": {
        "pepperoni passion medium": 18.99, "pepperoni passion large": 21.99,
        "mighty meaty medium": 18.99, "mighty meaty large": 21.99,
        "chicken feast medium": 18.99, "chicken feast large": 21.99,
        "margherita medium": 15.99, "margherita large": 18.99,
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
