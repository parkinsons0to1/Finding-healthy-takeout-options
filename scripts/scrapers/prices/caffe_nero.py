"""Caffè Nero UK — REAL per-branch prices from Caffè Nero's Just Eat storefront.

WHICH BUSINESS
    `caffenero.com` runs no ordering of its own — its own `/uk/delivery`
    page (checked directly) points to exactly three marketplaces: Deliveroo,
    Just Eat, Uber Eats. `onlineshop.caffenero.com` is a separate Shopify
    business selling bagged beans/capsules for home brewing, not the café
    menu this project's nutrition table (`data/db/caffe_nero.json`) covers.
    Same shape as `costa.py`/`wimpy.py`/`gdk.py`: the priced per-branch menu
    here is read from Caffè Nero's Just Eat storefront, never implied to be
    a price Caffè Nero publishes itself.

DELIVERY-ONLY on this platform (like Costa, unlike Wimpy/GDK)
    Every Wimbledon-area branch checked on Just Eat's discovery API reports
    `"isCollection": false, "isDelivery": true`, and the restaurant record's
    own `restaurantOpeningTimes` confirms it — the `collection` service type
    has an empty `timesPerDay` for every single day of the week, `delivery`
    has real hours. So unlike `wimpy.py`/`gdk.py` (verified collection-
    eligible) this module labels every row "delivery", matching `costa.py`'s
    convention for the same platform state.

Handshake
---------
Identical three-step shape to `costa.py`/`wimpy.py`/`gdk.py`; see those
modules for the full trace of how each URL was found. Every request goes
through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of
both the site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Caffè Nero" (also matches the
   plain-ASCII "Caffe Nero" spelling Just Eat's own search uses in some
   records, by lower-casing before the accent-insensitive compare).
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN
   base, `...cdn.restaurant.itemsUrl` the catalogue filename.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue. 69 of 226 items are
   `DealOnly: true` meal-deal-builder stubs (own-brand bean bags, add-on
   modifier choices) — skipped, same convention as every other Just-Eat-
   backed adapter here.

NAME DRIFT — `data/db/caffe_nero.json` (nutrition) vs. Just Eat's till
    Just Eat's product names and this project's nutrition table are both
    genuinely Caffè Nero's own copy, from two different internal feeds that
    don't always agree word-for-word. `_KCAL_VERIFIED_ALIASES` below pairs
    13 of them up — every single pair confirmed by an **exact kcal match**
    between the two sides (not a fuzzy name guess): e.g. Just Eat's "Chicken
    Caesar Wrap" (519 kcal) is this project's "Chicken & Bacon Caesar Wrap"
    (519 kcal) — same dish, Just Eat's copy just drops "Bacon". Two
    look-alike pairs were checked and *rejected* specifically because the
    kcal didn't match: "Free Range Egg Mayo Wedge" (449 kcal) is not
    "Free Range Egg Mayo Sandwich" (494 kcal), and "Pole & Line Tuna Melt
    Panini" (513 kcal) is not "Tuna Melt Panini" (488 kcal) — both are left
    unaliased, genuinely different portions/products rather than a spelling
    difference.

NOT MATCHED, HONESTLY — real gaps, not scraping failures
    A meaningful share of the nutrition table has no Just Eat counterpart at
    all: standalone porridge toppings/condiments this platform never sells
    on their own (jam, butter, clotted cream, cinnamon, "Dates & Pecan
    Nuts"), the seven milk-specific "Porridge made with X" nutrition rows
    against Just Eat's single undifferentiated "Porridge" listing (the same
    granularity gap `gdk.py` documents for its meat/sauce split), "Loacker
    Napolitaner"/"Loacker Vanille" against a single ambiguous "Loacker" JE
    listing with no flavour split to key off (left unaliased rather than
    guessing which flavour it is), and three rows
    (`White Diglycerides NEW Chicken...`, `White Mono- NEW Four Cheese...`,
    `White Mono- Treatment Chicken...`) that are visibly a nutrition-table
    parsing artefact — allergen/ingredient text merged into the name field
    upstream of this module — not something a price-side alias can fix.

STORE — Caffè Nero - Wimbledon Broadway, SW19 1RF
    Nearest Caffè Nero Just Eat lists to Wimbledon (checked from SW19 1RF).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "caffe_nero"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Caffè Nero - Wimbledon Broadway, SW19 1RF.
DEFAULT_STORE_SLUG = "caffe-nero---wimbledon-broadway-wimbledon"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_KCAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kcal", re.I)

#: Just Eat product name -> the nutrition table's spelling of the same
#: dish (`data/db/caffe_nero.json`). Every pairing here confirmed by an
#: exact kcal match — see the module docstring's NAME DRIFT section.
_KCAL_VERIFIED_ALIASES = {
    "apple and custard tart": "Apple Crumble & Custard Tart",
    "chocolate fudge cake": "Belgian Chocolate Fudge Cake",
    "cheese & tomato tostati small": "Cheese and Tomato Tostati",
    "chicken & grain salad": "Chicken & Mixed Grain Salad",
    "chicken caesar wrap": "Chicken & Bacon Caesar Wrap",
    "italian mozzarella, pesto and tomato pizzetta":
        "Italian Mozzarella, Pesto & Tomato Pizzetta",
    "seasonal fruit salad": "Fruit Salad",
    "proper corn sea salt popcorn": "Proper Corn Sea Salted Popcorn (Vg, GF)",
    "proper corn sweet & salty popcorn":
        "Proper Corn Sweet & Salty Popcorn (Vg, GF)",
    "italian cream bun 'maritozzi'": "Italian Cream Bun 'Maritozzo'",
    "mango & passionfruit cheesecake":
        "Mango & Passionfruit Plant Based Cheesecake",
    "plant based mushroom & tomato ragu panini":
        "Mushroom & Tomato Ragu Panini",
    "sicilian lemon muffin": "Sicilian Lemon Curd Muffin Fruit Scone",
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"caffe_nero: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Caffè Nero branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"caffe_nero: postcode {postcode!r} rejected by "
                           f"the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"caffe_nero: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().replace("è", "e")
            .startswith("caffe nero")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"caffe_nero: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"caffe_nero: menu page HTTP {r.status_code} for "
                           f"{slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"caffe_nero: __NEXT_DATA__ not found for "
                           f"{slug!r} — the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"caffe_nero: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("caffe_nero: no UK menu-CDN base in "
                           "__NEXT_DATA__ — clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "caffe_nero: preloadedState.menu.restaurant.cdn.restaurant "
            "missing — the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, unioned across every day-part menu."""
    out: dict[str, str] = {}
    for menu in restaurant.get("menus") or []:
        for cat in menu.get("categories") or []:
            name = cat.get("name")
            for item_id in cat.get("itemIds") or []:
                out.setdefault(item_id, name)
    return out


def _kcal(variation: dict) -> float | None:
    text = (variation.get("NutritionalInfo") or {}).get("EnergyDisplay") or ""
    m = _KCAL_RE.search(text)
    return float(m.group(1)) if m else None


def fetch_prices(store_id: str | None = None, basis: str = "delivery",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Caffè Nero branch.

    Give a `store_id` (the Just Eat slug), or a `postcode` to use the
    nearest listed branch. Every Wimbledon-area branch is delivery-only on
    this platform (see module docstring) — `basis="collection"` will raise
    unless a future re-check finds a collection-eligible branch.
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"caffe_nero: unknown basis {basis!r}")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"caffe_nero: no Caffè Nero listed on Just "
                               f"Eat for {postcode!r}")
        record = found[0]
        slug = record["uniqueName"]
    else:
        slug = store_id or DEFAULT_STORE_SLUG

    next_data = _menu_page(slug)
    cdn_base = _cdn_base(next_data)
    restaurant = _restaurant_node(next_data)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"caffe_nero: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"caffe_nero: items JSON HTTP {r.status_code} "
                           f"for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"caffe_nero: items JSON for {slug!r} was not "
                           f"JSON ({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"caffe_nero: items JSON for {slug!r} came back "
                           f"empty — the handshake broke, not that the shop "
                           f"is bare")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Caffè Nero ({slug})").strip()
    addr = (record or {}).get("address") or (info.get("location") or {})
    town = addr.get("postalCode") or addr.get("postCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item_id = raw_item.get("Id")
        category = categories.get(item_id)
        product_name = re.sub(r"\s+", " ", (raw_item.get("Name") or "").strip())
        for variation in raw_item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue           # meal-deal-builder component, not a price
            price = variation.get("BasePrice")
            if price is None:
                continue
            vname = (variation.get("Name") or "").strip()
            full_name = f"{product_name} {vname}" if vname else product_name
            kcal = _kcal(variation)

            names = [full_name]
            alias = _KCAL_VERIFIED_ALIASES.get(full_name.lower())
            if alias:
                names.append(alias)

            for row_name in names:
                key = row_name.lower()
                if not row_name or key in seen:
                    continue
                seen.add(key)
                out.append({
                    "name": row_name,
                    "price_gbp": round(float(price), 2),
                    "basis": basis,
                    "store": label,
                    "category": category,
                    "kcal": kcal,
                })

    if not out:
        raise RuntimeError(
            f"caffe_nero: {len(raw_items)} items for {label} but none "
            f"survived the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
