"""McDonald's UK — REAL per-store prices from McDonald's own Just Eat storefront.

WHICH BUSINESS
    `www.mcdonalds.com/gb` has no priced ordering of its own — its `dnaapp`
    nutrition widget (`/dnaapp/itemDetails`, the source of `data/db/
    mcdonalds.json`) returns full nutrition/allergen JSON with no `price`
    field anywhere in the schema, and the marketing menu pages carry zero £
    mentions. McDonald's own geolocation endpoint
    (`/googleappsv2/geolocation`) lists, per store, only third-party ordering
    links (Deliveroo, Just Eat, Uber Eats) plus `smart.link` deep links into
    "My McDonald's app" for in-app ordering — no web checkout exists.
    McDelivery is confirmed outsourced entirely to those three aggregators
    (`/gb/en-gb/latest/mcdelivery.html` says so explicitly). So, exactly like
    Subway/Costa/Chipotle/GDK in this project, the per-branch priced menu
    here is read from McDonald's own storefront on Just Eat
    (`www.just-eat.co.uk`) — public, no account — and is labelled as a Just
    Eat price throughout, never implied to be a price McDonald's publishes
    itself. McDonald's is a real, first-class Just Eat partner in the UK
    (unlike Domino's, which — see `dominos.py` — is not on any marketplace at
    all): the discovery API lists four branches within a couple of miles of
    this project's Sutton default alone, all `isDelivery: true`.

Handshake
---------
Identical three-step shape to `subway.py` / `costa.py` / `gdk.py`; see those
modules for the full trace of how each URL was found. Every request goes
through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of
both the site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "McDonald's" (curly apostrophe;
   `str.startswith("mcdonald")` is used, not an exact string, so the plain
   ASCII apostrophe some tooling substitutes still matches).
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN
   base (read live, not pinned), `...cdn.restaurant.itemsUrl` is the
   catalogue filename, `...cdn.restaurant.menus[]` the day-part menus.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

NOT A TRAP HERE, unlike Subway — no channel duplication, only day-parting
    Sutton's `menus[]` has exactly two entries, both `serviceTypes:
    ["delivery"]` (this branch is delivery-only — `isCollection: false` on
    the discovery API, the same shape Costa/Chipotle document). They are a
    breakfast menu (McMuffins, Porridge & Pancakes, Breakfast Saver Menu®)
    and the all-day menu (Burgers, Chicken, Happy Meal®, …), not two copies
    of one catalogue. 66 of 241 items legitimately appear in both (drinks,
    sauces, desserts sold all day) — checked exhaustively, every one of the
    66 is byte-identical in price between the two menus — so this module
    keeps the first occurrence of each item name and does not need a
    collection/delivery channel split the way Subway does.

TRAP — every item here already has `DealOnly: false` and a single
       no-variation `Variations` entry; the bundle/combo items are separate,
       full-price products, not `DealOnly: true` addons
    Unlike Subway/Costa/Chipotle/GDK, none of the 241 items at Sutton carry
    `DealOnly: true` or a £0 stub — checked exhaustively, zero exceptions.
    "Large Big Mac® Meal" (fries + drink) is its own fully-priced item next
    to the standalone "Big Mac®", not a modifier tacked onto it. So there is
    no DealOnly filter to apply here; every row this module reads is a real,
    directly-orderable price.

NAME DRIFT — the nutrition API and Just Eat spell some products differently
    `data/db/mcdonalds.json` (from the `dnaapp` API) and this Just Eat
    catalogue disagree on wording for eleven products — never guessed, each
    pairing confirmed by an EXACT kcal match between Just Eat's own
    `NutritionalInfo.EnergyDisplay` and the `dnaapp` figure, the same join
    method `subway.py` uses: "and" vs "&" across five McMuffins (e.g. "Bacon
    and Egg McMuffin®" = "Bacon & Egg McMuffin", both 336 kcal); "BBQ & Bacon
    Chicken Wrap" is "Crispy BBQ & Bacon Wrap" (477 kcal); "Sweet Chilli
    Chicken Wrap" is "Crispy Sweet Chilli Chicken Wrap" (453 kcal); "Tikka
    Chicken Wrap" is "The Tikka Chicken One - Crispy" (455 kcal); "McPlant®
    [VE]" is "McPlant" (426 kcal); "Melon Chunks [VE]" is "Melon Chunks" (17
    kcal); "Toasted Muffin with Jam" is "Muffin & Jam" (214 kcal). A
    same-named-looking pair that is NOT the same product was checked and
    rejected: "Hamburger Happy Meal®" (485 kcal, includes fries/drink) is not
    the nutrition table's bare "Hamburger" (255 kcal) — no alias made, since
    the plain hamburger-alone item is not sold on this branch's Just Eat
    listing at all.

MISSING FROM THIS STORE — five nutrition rows have no Just Eat match at all
    "Shaker Side Salad", "Flahavan's Quick Oats", "Crispy Chicken & Bacon
    Salad", "Crispy Chicken Salad" and the three flavoured "Porridge with
    ..." rows (plain "Porridge" too) are not on Sutton's Just Eat menu under
    any name or kcal match — a genuine miss (this branch's delivery
    catalogue is narrower than the full national menu the nutrition API
    covers), not a naming problem this module can paper over.

PRICE BASIS — delivery, from McDonald's Just Eat storefront
    Every row is labelled "delivery" — the only service type this branch
    lists on Just Eat (`isCollection: false`). This is a real per-branch
    price a customer pays today, but it is McDonald's price on a third-party
    marketplace with Just Eat's markup baked in, not necessarily the
    in-restaurant counter price; no channel for that comparison exists
    online (see `subway.py` for the identical caveat). It runs measurably
    above the old flat-rate guesses in `ESTIMATED_PRICES["mcdonalds"]`: a Big
    Mac was estimated at £4.99 and is £6.09 here.

PER STORE
    McDonald's® - Sutton (SM1 1NL) is the default, matching every other
    adapter's south-London default.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "mcdonalds"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: McDonald's® - Sutton, SM1 1NL — the branch this adapter was verified
#: against, matching the other adapters' south-London default.
DEFAULT_STORE_SLUG = "mcdonaldssutton-sutton"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)

#: Just Eat product name -> the `dnaapp` nutrition API's spelling(s) of the
#: same product (`data/db/mcdonalds.json`). Every pairing verified by an
#: exact kcal match — see the NAME DRIFT trap in the module docstring.
_NUTRITION_ALIASES = {
    "Bacon and Egg McMuffin®": ["Bacon & Egg McMuffin"],
    "Double Bacon and Egg McMuffin®": ["Double Bacon & Egg McMuffin"],
    "Double Sausage and Egg McMuffin®": ["Double Sausage & Egg McMuffin"],
    "Egg and Cheese McMuffin®": ["Egg & Cheese McMuffin"],
    "Sausage and Egg McMuffin®": ["Sausage & Egg McMuffin"],
    "BBQ & Bacon Chicken Wrap": ["Crispy BBQ & Bacon Wrap"],
    "Sweet Chilli Chicken Wrap": ["Crispy Sweet Chilli Chicken Wrap"],
    "Tikka Chicken Wrap": ["The Tikka Chicken One - Crispy"],
    "McPlant® [VE]": ["McPlant"],
    "Melon Chunks [VE]": ["Melon Chunks"],
    "Toasted Muffin with Jam": ["Muffin & Jam"],
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"mcdonalds: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """McDonald's branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"mcdonalds: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"mcdonalds: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("mcdonald")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"mcdonalds: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"mcdonalds: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"mcdonalds: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"mcdonalds: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("mcdonalds: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "mcdonalds: preloadedState.menu.restaurant.cdn.restaurant "
            "missing — the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, unioned across the breakfast/all-day menus."""
    out: dict[str, str] = {}
    for menu in restaurant.get("menus") or []:
        for cat in menu.get("categories") or []:
            name = cat.get("name")
            for item_id in cat.get("itemIds") or []:
                out.setdefault(item_id, name)
    return out


def _kcal(nutritional_info) -> float | None:
    text = (nutritional_info or {}).get("EnergyDisplay") or ""
    m = _ENERGY_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def fetch_prices(store_id: str | None = None, basis: str = "delivery",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one McDonald's branch.

    Give a `store_id` (the Just Eat slug, e.g. "mcdonaldssutton-sutton"), or
    a `postcode` to use the nearest listed branch. Only "delivery" is
    offered — Sutton (and every branch checked) lists `isCollection: false`
    on Just Eat.
    """
    if basis != "delivery":
        raise ValueError(f"mcdonalds: unknown basis {basis!r} (only "
                         f"'delivery' — McDonald's Just Eat storefront has "
                         f"no collection service type at any branch checked)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"mcdonalds: no McDonald's listed on Just Eat "
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
        raise RuntimeError(f"mcdonalds: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"mcdonalds: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"mcdonalds: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"mcdonalds: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"McDonald's ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        item_id = item.get("Id")
        category = categories.get(item_id)
        product_name = (item.get("Name") or "").strip()
        if not product_name:
            continue
        variations = item.get("Variations") or []
        if not variations:
            continue
        variation = variations[0]
        if variation.get("DealOnly"):
            continue           # not observed at Sutton, but guard anyway
        price = variation.get("BasePrice")
        if price is None:
            continue
        kcal = _kcal(variation.get("NutritionalInfo"))
        for row_name in [product_name] + _NUTRITION_ALIASES.get(product_name, []):
            key = row_name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "name": row_name,
                "price_gbp": round(float(price), 2),
                "basis": "delivery",
                "store": label,
                "category": category,
                "kcal": kcal,
            })

    if not out:
        raise RuntimeError(
            f"mcdonalds: {len(raw_items)} items for {label} but none survived "
            f"the filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
