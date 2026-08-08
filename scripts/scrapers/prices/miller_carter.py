"""Miller & Carter UK — REAL per-branch prices from its Just Eat storefront.

WHICH BUSINESS
    `millerandcarter.co.uk` (a Mitchells & Butlers brand) is reservation-
    only — its homepage and every branch page checked carry zero menu or
    ordering links at all, only a table-booking flow. Third-party listings
    (Uber Eats' "The Grapes Beefeater", pricelisto-style aggregators) hinted
    a marketplace presence exists for M&B brands even without a link from
    the brand's own site, so Just Eat's discovery API was queried directly
    instead of assuming "no online pricing" from the homepage alone — it
    lists Miller & Carter branches, several of them collection-eligible.
    Same shape as `costa.py`/`wimpy.py`: the priced per-branch menu here is
    read from Miller & Carter's Just Eat storefront, never implied to be a
    price Miller & Carter publishes itself.

COLLECTION-ELIGIBLE — checked, not assumed
    Miller & Carter - Manchester reports `"isCollection": true,
    "isDelivery": true` on Just Eat's discovery API — unlike most sit-down
    chains checked for this project, at least one branch does sell
    anonymous online collection pricing.

Handshake
---------
Identical three-step shape to `costa.py`/`wimpy.py`/`gdk.py`; see those
modules for the full trace. Every request goes through
`scripts.scrapers.base.fetch_protected`.

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Miller & Carter" / "Miller and
   Carter" (Just Eat's own `uniqueName` slugs spell it both ways).
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__` for the menu-CDN base and `itemsUrl`.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue: 86 items at
   Manchester, all non-`DealOnly`.

DIETARY-TAG SUFFIX — stripped, since it's marketing not product identity
    Nearly every item on both sides carries "(V)"/"(VE)"/"(GF)" and a
    trailing "*" allergen marker — but the two feeds don't always agree
    which tags a given dish carries (e.g. one side's "*" survives, the
    other's doesn't), so an exact-string join misses real matches over a
    difference that isn't the dish. `_strip_diet_tags` emits both the raw
    JE name and a tag-stripped alias, matching `frankie_bennys.py`'s
    approach to the same problem on the same underlying platform shape.

STORE — Miller & Carter - Manchester
    The nearest Miller & Carter to Wimbledon on Just Eat (Worcester Park)
    is neither collection- nor delivery-eligible there
    (`"isCollection": false, "isDelivery": false` — effectively delisted);
    Manchester is the first collection-eligible branch found checking
    outward from London.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "miller_carter"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Miller & Carter - Manchester — see STORE in the module docstring.
DEFAULT_STORE_SLUG = "miller-and-carter---manchester-manchester"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_KCAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kcal", re.I)
#: Trailing dietary-tag markers and allergen asterisks — see the module
#: docstring's DIETARY-TAG SUFFIX section.
_DIET_TAG_RE = re.compile(
    r"[\*]*\s*(\((?:v|ve|vg|vegan|gf|gluten-free)\)\s*)+\**\s*$", re.I)


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"miller_carter: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Miller & Carter branches Just Eat lists for a UK postcode."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"miller_carter: postcode {postcode!r} rejected "
                           f"by the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"miller_carter: discovery API HTTP "
                           f"{r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower()
            .startswith(("miller & carter", "miller and carter"))]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"miller_carter: no restaurant page for slug "
                           f"{slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"miller_carter: menu page HTTP {r.status_code} "
                           f"for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"miller_carter: __NEXT_DATA__ not found for "
                           f"{slug!r} — the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"miller_carter: __NEXT_DATA__ was not valid "
                           f"JSON ({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("miller_carter: no UK menu-CDN base in "
                           "__NEXT_DATA__ — clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "miller_carter: preloadedState.menu.restaurant.cdn.restaurant "
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
    """Priced Just Eat menu for one Miller & Carter branch.

    Give a `store_id` (the Just Eat slug), or a `postcode` to use the
    nearest listed branch — check its `isCollection`/`isDelivery` flags via
    `find_stores` first, since most branches carry neither on this platform.
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"miller_carter: unknown basis {basis!r}")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"miller_carter: no Miller & Carter listed "
                               f"on Just Eat for {postcode!r}")
        record = found[0]
        slug = record["uniqueName"]
    else:
        slug = store_id or DEFAULT_STORE_SLUG

    next_data = _menu_page(slug)
    cdn_base = _cdn_base(next_data)
    restaurant = _restaurant_node(next_data)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"miller_carter: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"miller_carter: items JSON HTTP "
                           f"{r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"miller_carter: items JSON for {slug!r} was "
                           f"not JSON ({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"miller_carter: items JSON for {slug!r} came "
                           f"back empty — the handshake broke, not that "
                           f"the shop is bare")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Miller & Carter ({slug})").strip()
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
            f"miller_carter: {len(raw_items)} items for {label} but none "
            f"survived the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:30]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
