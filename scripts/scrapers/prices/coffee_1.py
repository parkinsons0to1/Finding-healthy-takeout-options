"""Coffee #1 UK — REAL per-branch prices from Coffee #1's Just Eat storefront.

WHICH BUSINESS
    `coffee1.co.uk` runs no ordering of its own — the homepage carries no
    delivery-partner links, no "order online", nothing beyond an app-store
    link for its loyalty app. Just Eat's discovery API lists real Coffee #1
    branches independently of anything linked from Coffee #1's own site
    (found by querying the discovery API directly for Birmingham postcodes
    after the homepage turned up nothing) — same shape as
    `caffe_nero.py`/`costa.py`: the priced per-branch menu here is read
    from Coffee #1's Just Eat storefront, never implied to be a price
    Coffee #1 publishes itself.

DELIVERY-ONLY on this platform
    Both Birmingham branches checked (Moseley, Kings Heath) report
    `"isCollection": false, "isDelivery": true`.

Handshake
---------
Identical three-step shape to `caffe_nero.py`/`costa.py`/`wimpy.py`; see
those modules for the full trace. Every request goes through
`scripts.scrapers.base.fetch_protected`.

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Coffee #1" (also accepts "Coffee
   1"/"Coffee No 1" spelling variants).
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__` for the menu-CDN base and `itemsUrl`.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue: 163 items at
   Moseley, 103 non-`DealOnly`.

SCOPE — this Just Eat storefront is a smaller subset of the full café range
    `data/db/coffee_1.json` (a brand-published allergen/nutrition PDF) is
    considerably larger than this branch's Just Eat catalogue (387 nutrition
    rows vs. 103 priced items) — a real, sizeable portion of the PDF's range
    (seasonal items, some bakery lines, most hot-drink milk variants) simply
    isn't sold on this platform at this branch. No aliasing was attempted
    beyond plain name matching — reported honestly via the resulting
    nutrition-join hit rate rather than papered over with speculative
    aliases.

STORE — Coffee #1 - Moseley, Birmingham
    No Coffee #1 branch is listed on Just Eat near Wimbledon or central
    London in the postcodes checked; Moseley is the first found checking
    outward (Birmingham).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "coffee_1"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Coffee #1 - Moseley, Birmingham — see STORE in the module docstring.
DEFAULT_STORE_SLUG = "coffee-1---mosely-birmingham"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_KCAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kcal", re.I)


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"coffee_1: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Coffee #1 branches Just Eat lists for a UK postcode."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"coffee_1: postcode {postcode!r} rejected by "
                           f"the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"coffee_1: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    out = []
    for x in restaurants:
        n = str(x.get("name") or "").strip().lower()
        if n.startswith("coffee #1") or n.startswith("coffee 1") \
                or n.startswith("coffee no 1") or n.startswith("coffee no. 1"):
            out.append(x)
    return out


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"coffee_1: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"coffee_1: menu page HTTP {r.status_code} for "
                           f"{slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"coffee_1: __NEXT_DATA__ not found for "
                           f"{slug!r} — the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"coffee_1: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("coffee_1: no UK menu-CDN base in "
                           "__NEXT_DATA__ — clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "coffee_1: preloadedState.menu.restaurant.cdn.restaurant "
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


def fetch_prices(store_id: str | None = None, basis: str = "delivery",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Coffee #1 branch.

    Give a `store_id` (the Just Eat slug), or a `postcode` to use the
    nearest listed branch. Every branch found so far is delivery-only on
    this platform.
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"coffee_1: unknown basis {basis!r}")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"coffee_1: no Coffee #1 listed on Just Eat "
                               f"for {postcode!r}")
        record = found[0]
        slug = record["uniqueName"]
    else:
        slug = store_id or DEFAULT_STORE_SLUG

    next_data = _menu_page(slug)
    cdn_base = _cdn_base(next_data)
    restaurant = _restaurant_node(next_data)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"coffee_1: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"coffee_1: items JSON HTTP {r.status_code} for "
                           f"{slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"coffee_1: items JSON for {slug!r} was not "
                           f"JSON ({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"coffee_1: items JSON for {slug!r} came back "
                           f"empty — the handshake broke, not that the shop "
                           f"is bare")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Coffee #1 ({slug})").strip()
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
            key = full_name.lower()
            if not full_name or key in seen:
                continue
            seen.add(key)
            out.append({
                "name": full_name,
                "price_gbp": round(float(price), 2),
                "basis": basis,
                "store": label,
                "category": category,
                "kcal": kcal,
            })

    if not out:
        raise RuntimeError(
            f"coffee_1: {len(raw_items)} items for {label} but none "
            f"survived the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:30]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
