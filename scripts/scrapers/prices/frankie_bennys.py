"""Frankie & Benny's UK — REAL per-branch prices from its Just Eat storefront.

WHICH BUSINESS
    `frankieandbennys.com`'s own `/delivery` page (checked directly) links
    only to three marketplaces: Deliveroo, Just Eat, Uber Eats — no
    first-party ordering. Same shape as `costa.py`/`wimpy.py`: the priced
    per-branch menu here is read from Frankie & Benny's Just Eat storefront,
    never implied to be a price Frankie & Benny's publishes itself.

TRAP — the nearest branch to London serves a BREAKFAST-ONLY menu (29 items,
       zero overlap with the nutrition table's dinner menu); a full-menu
       branch had to be found elsewhere
    Frankie & Benny's - Covent Garden (the only Frankie & Benny's Just Eat
    lists near Wimbledon/central London) sells nothing but a breakfast
    catalogue — pancakes, bagels, breakfast combos — on this platform. Every
    one of the 99 nutrition rows in `data/db/frankie_bennys.json` (starters,
    burgers, pasta, pizza, ribs — the dinner menu) has zero possible match
    there, which would read as "chain barely covered" if left as the
    default store. Checked six more regional postcodes instead: Frankie &
    Benny's - Glasgow The Fort carries the full 74-item dinner catalogue
    (burgers, pizza, pasta, ribs, calzones, desserts) this project's
    nutrition table actually covers, and is collection-eligible
    (`isCollection: true`) — used as the default here instead.

Handshake
---------
Identical three-step shape to `costa.py`/`wimpy.py`/`gdk.py`; see those
modules for the full trace. Every request goes through
`scripts.scrapers.base.fetch_protected`.

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Frankie & Benny's" / "Frankie
   and Benny's" (Just Eat's own `uniqueName` slugs spell it both ways).
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__` for the menu-CDN base and `itemsUrl`.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue: 74 items at Glasgow
   The Fort, all non-`DealOnly`.

SCOPE — a whole-dish JE catalogue vs. an ingredient-level nutrition table
    `data/db/frankie_bennys.json` breaks pizzas and burgers down to their
    individual toppings/patties as separate rows ("Pepperoni", "Ham",
    "Beef Patty", "Crispy Chicken", "Plant Patty") — JE only prices the
    assembled dish ("Pepperoni Pizza", "Classic Beef Burger"). This is the
    same granularity gap `gdk.py` documents for its meat/sauce split: real,
    not fixable by aliasing a component ingredient to a whole-dish price
    without inventing a join this project's house style avoids.

DIETARY-TAG SUFFIX — stripped, since it's marketing not product identity
    JE appends "(V)"/"(VG)"/"(Vegan)"/"(Gluten-Free)"/standalone "PB" to
    many names that the nutrition table's matching row doesn't carry (e.g.
    JE "Garlic Pizza Bread Sharer (VG)" vs nutrition "Garlic Pizza Bread
    Sharer") — `_strip_diet_tags` emits both the raw JE name and a
    tag-stripped alias.

STORE — Frankie & Benny's - Glasgow The Fort
    See the TRAP section above for why this, not the nearest-to-Wimbledon
    branch, is the default.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "frankie_bennys"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Frankie & Benny's - Glasgow The Fort — see STORE in the module docstring.
DEFAULT_STORE_SLUG = "frankieandbennys-glasgowfortshandwicksquare"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_KCAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kcal", re.I)
#: Trailing dietary-tag markers to strip for the alias — parenthesised
#: ("(V)", "(VG)", "(Vegan)", "(Gluten-Free)"...) or a bare trailing "PB".
_DIET_TAG_RE = re.compile(
    r"\s*(\((?:v|vg|ve|vegan|gluten-free|pb)\)|(?<=\s)pb)\s*$", re.I)


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"frankie_bennys: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Frankie & Benny's branches Just Eat lists for a UK postcode."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"frankie_bennys: postcode {postcode!r} rejected "
                           f"by the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"frankie_bennys: discovery API HTTP "
                           f"{r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower()
            .startswith(("frankie & benny's", "frankie and benny's"))]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"frankie_bennys: no restaurant page for slug "
                           f"{slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"frankie_bennys: menu page HTTP {r.status_code} "
                           f"for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"frankie_bennys: __NEXT_DATA__ not found for "
                           f"{slug!r} — the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"frankie_bennys: __NEXT_DATA__ was not valid "
                           f"JSON ({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("frankie_bennys: no UK menu-CDN base in "
                           "__NEXT_DATA__ — clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "frankie_bennys: preloadedState.menu.restaurant.cdn.restaurant "
            "missing — the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
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


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Frankie & Benny's branch.

    Give a `store_id` (the Just Eat slug), or a `postcode` to use the
    nearest listed branch — but see the module docstring's TRAP section
    before relying on postcode lookup near London.
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"frankie_bennys: unknown basis {basis!r}")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"frankie_bennys: no Frankie & Benny's "
                               f"listed on Just Eat for {postcode!r}")
        record = found[0]
        slug = record["uniqueName"]
    else:
        slug = store_id or DEFAULT_STORE_SLUG

    next_data = _menu_page(slug)
    cdn_base = _cdn_base(next_data)
    restaurant = _restaurant_node(next_data)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"frankie_bennys: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"frankie_bennys: items JSON HTTP "
                           f"{r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"frankie_bennys: items JSON for {slug!r} was "
                           f"not JSON ({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"frankie_bennys: items JSON for {slug!r} came "
                           f"back empty — the handshake broke, not that the "
                           f"shop is bare")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Frankie & Benny's ({slug})").strip()
    addr = (record or {}).get("address") or (info.get("location") or {})
    town = addr.get("postalCode") or addr.get("postCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item_id = raw_item.get("Id")
        category = categories.get(item_id)
        product_name = re.sub(r"\s+", " ", (raw_item.get("Name") or "")).strip()
        for variation in raw_item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue
            price = variation.get("BasePrice")
            if price is None:
                continue
            vname = (variation.get("Name") or "").strip()
            full_name = f"{product_name} {vname}" if vname else product_name
            kcal = _kcal(variation)

            names = [full_name]
            stripped = _DIET_TAG_RE.sub("", full_name).strip()
            if stripped and stripped.lower() != full_name.lower():
                names.append(stripped)

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
            f"frankie_bennys: {len(raw_items)} items for {label} but none "
            f"survived the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:30]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
