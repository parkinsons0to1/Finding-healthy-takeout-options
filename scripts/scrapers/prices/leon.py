"""LEON UK — REAL per-store prices from LEON's Just Eat storefront.

WHICH BUSINESS
    `leon.co` has no priced ordering of its own — `/menu/` (not fetched
    directly here, but linked from the homepage) and `/delivery/` are the
    only ordering-adjacent pages, and `/delivery/` is a static hand-off page
    whose outbound links are `deliveroo.co.uk/brands/leon`,
    `www.just-eat.co.uk/takeaway/brands/leon`, `www.ubereats.com/` and
    `feedr.co` (an office-catering aggregator, out of scope) — no first-party
    checkout. So, like Chipotle/Subway/Costa/itsu, the per-branch priced menu
    here is read from LEON's own storefront on Just Eat
    (`www.just-eat.co.uk`) — public, no account — and is labelled as a Just
    Eat price throughout, never implied to be a price LEON publishes itself.
    Every LEON branch checked on Just Eat's discovery API reports
    `"isCollection": false, "isDelivery": true` — delivery-only on this
    marketplace, the same shape as Costa/Chipotle.

Handshake
---------
Identical three-step shape to `subway.py`/`costa.py`/`chipotle.py`/`itsu.py`;
see `subway.py` for the full trace of how each URL was found. Every request
goes through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in
front of both the site and its API host; curl_cffi's safari profile gets
through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "LEON".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN base
   (read live, not pinned), `...cdn.restaurant.itemsUrl` is the catalogue
   filename, `...cdn.restaurant.menus[]` the two day-part menus.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

NOT A TRAP HERE, unlike Subway — no channel duplication, and no DealOnly
    stubs either
    Both of Battersea's `menus[]` report `serviceTypes: ["delivery"]` — there
    is only one channel, so there is nothing to double-count (same as
    Costa/Chipotle). Every one of the 166 items checked is `Type: "menuitem"`
    with `DealOnly: false` on its only variation — this catalogue has none of
    the near-zero deal-builder stub rows Subway/Chipotle/itsu carry, so no
    DealOnly filter is even needed here; it is still applied defensively in
    case a future menu adds one.

TRAP — `menus[].categories[].itemIds` is split by DAY PART, not duplicated —
       the same trap Subway documents, just for a different reason
    The two `menuGroupId`s are a breakfast menu and an all-day menu, not two
    copies of one menu: `categories[]` lists all 24 category names under
    both `menuGroupId`s, but "Big Breakfasts"/"Poached Egg pots"/"Organic
    Porridge…" only carry real `itemIds` on one menu and "Superfood
    Salads"/"Big Rice Boxes"/"Wraps"/"Burgers"… only carry them on the other
    — checked directly (menu A: 4+9+10+4+6+3+3+2 breakfast-shaped categories
    populated, lunch categories all `itemIds: []`; menu B: the exact
    opposite). This module builds the category map from the union of every
    non-empty copy across both menus, same fix as `subway.py`/`costa.py`.

NAME DRIFT — sized drinks/sides use "{name} - Regular"/"{name} - Large";
    the nutrition PDF publishes one unsized row per drink, and Regular is
    that row
    Just Eat lists 25 Regular/Large pairs (lattes, coolers, iced teas, hash
    browns, LEON Slaw…); `data/db/leon.json` publishes exactly one row per
    drink/side with no size in the name. Checked which size that row is by
    exact-kcal match wherever the nutrition PDF prints a kcal figure: Latte
    (195), Iced Latte (129), Mocha (388), Hot Chocolate (411), Chai Latte
    (260), Vanilla Matcha Latte (252), Unsweetened Matcha Latte (195), Hash
    Browns (216), Crisp Peach Cooler (92) and Raspberry & Pomegranate Cooler
    (77) all match the **Regular** JE variation exactly, never Large — so
    "Regular" is emitted under the plain name (mirroring `subway.py`'s
    6-inch convention) and "Large" gets a " Large" suffix so it can never be
    matched to the Regular-basis macros. Two drinks in the same size-suffixed
    set do NOT match at Regular: Cappuccino (PDF 168 kcal vs JE Regular 142 /
    Large 192) and Americano/Iced Americano (PDF 10 kcal vs JE 1 kcal both
    sizes) — recipe drift over time, the same kind of near-miss `subway.py`
    keeps under "Garlic Cheesesteak"/"Garlic Cheese Steak" (539 vs 548 kcal).
    The Regular-name convention is still applied to them for consistency
    (the product identity is not in doubt, only the exact kcal), same
    reasoning subway.py uses to alias its close-but-not-exact pairs anyway.

NAME DRIFT — six more pairs confirmed by exact calorie match, portion-size
    or dietary-suffix wording only
    "The LoVe Burger (VG)" (565 kcal) = the PDF's "LOVe Burger"; "Bacon
    Muffin (no egg)" (340) = "Bacon Muffin"; "Chilli Sauce (VG)" (19) =
    "Chilli Sauce"; "GFC – Crispy Chicken Nuggets (5 pieces)" (451) = the
    PDF's unsized "GFC - Crispy Chicken Nuggets" (its 10-piece/903-kcal and
    15-piece-bucket/1354-kcal siblings are correctly NOT this row — checked,
    not merged); "Honey Sriracha GFC Chicken Nuggets (5 pieces)" (521) =
    unsized "Honey Sriracha GFC Chicken Nuggets" (10-piece sibling excluded
    the same way); "Cheddar & Black Pepper Mac Bites (4 Pieces)" (323) =
    unsized "Cheddar & Black Pepper Mac Bites" (7-piece/12-piece siblings
    excluded). Every alias here is a same-kcal pair, not a guess from
    similar-looking words; near-name matches that do NOT share a kcal
    (Ruby Red Porridge, Banana & Cinnamon Porridge, Karma Cola — all off by
    30-40 kcal against every JE size) were checked and rejected.

NOT MATCHED, and correctly so
    Roughly half the nutrition PDF (smoothies, mezze pots, several rice-box
    and salad builds, kids' items, most sauces) has no Just Eat counterpart
    at any price on this delivery-only branch, and conversely several JE
    rows (build-your-own bowls, some Bowl'd items, grocery jars) have no
    nutrition-PDF counterpart. Neither is a bug in this module — both are
    reported honestly via the resulting nutrition-join hit rate.

PRICE BASIS — delivery, from LEON's Just Eat storefront
    Every row is labelled "delivery" — the only service type LEON lists on
    this marketplace at every branch checked. This is a real per-branch
    price a customer pays today, but it is LEON's price on a third-party
    platform, not necessarily the counter price in the shop; no channel for
    that comparison exists online (see `subway.py` for the identical
    caveat).

PER STORE
    LEON - Battersea (SW8 5BN) is the default — the only LEON south of the
    river that Just Eat lists near this project's other south-London
    defaults (a search centred on Sutton itself, SM1 1EZ, and on Wimbledon,
    SW19, returned no LEON at all; every other branch found is in central
    London).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "leon"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: LEON - Battersea, SW8 5BN — the only LEON south of the river Just Eat
#: lists near this project's other south-London defaults.
DEFAULT_STORE_SLUG = "leon---battersea-south-lambeth"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)

#: Just Eat product name (lowercased) -> the nutrition PDF's spelling of the
#: same dish (`data/db/leon.json`). Every pairing verified by an exact
#: calorie match — see the NAME DRIFT sections in the module docstring.
_PDF_ALIASES = {
    "the love burger (vg)": "LOVe Burger",
    "bacon muffin (no egg)": "Bacon Muffin",
    "chilli sauce (vg)": "Chilli Sauce",
    "gfc – crispy chicken nuggets (5 pieces)": "GFC - Crispy Chicken Nuggets",
    "gfc - crispy chicken nuggets (5 pieces)": "GFC - Crispy Chicken Nuggets",
    "honey sriracha gfc chicken nuggets (5 pieces)":
        "Honey Sriracha GFC Chicken Nuggets",
    "cheddar & black pepper mac bites (4 pieces)":
        "Cheddar & Black Pepper Mac Bites",
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"leon: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """LEON branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"leon: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"leon: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("leon")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"leon: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"leon: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"leon: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"leon: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("leon: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "leon: preloadedState.menu.restaurant.cdn.restaurant missing — "
            "the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, unioned across both day-part menus (see the
    module docstring's category trap)."""
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


def _row_name(product_name: str) -> str:
    """Strip the Regular/Large size suffix — see the module docstring's
    NAME DRIFT section for which size matches the nutrition PDF's basis."""
    if product_name.endswith(" - Regular"):
        return product_name[: -len(" - Regular")]
    if product_name.endswith(" - Large"):
        return product_name[: -len(" - Large")] + " Large"
    return product_name


def fetch_prices(store_id: str | None = None, basis: str = "delivery",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one LEON branch.

    Give a `store_id` (the Just Eat slug, e.g.
    "leon---battersea-south-lambeth"), or a `postcode` to use the nearest
    listed branch. Only "delivery" is offered — every branch checked lists
    `isCollection: false` on Just Eat.
    """
    if basis != "delivery":
        raise ValueError(f"leon: unknown basis {basis!r} (only 'delivery' — "
                         f"LEON's Just Eat storefront has no collection "
                         f"service type at any branch checked)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"leon: no LEON listed on Just Eat for "
                               f"{postcode!r}")
        record = found[0]
        slug = record["uniqueName"]
    else:
        slug = store_id or DEFAULT_STORE_SLUG

    next_data = _menu_page(slug)
    cdn_base = _cdn_base(next_data)
    restaurant = _restaurant_node(next_data)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"leon: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"leon: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"leon: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"leon: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"LEON ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        item_id = item.get("Id")
        category = categories.get(item_id)
        product_name = (item.get("Name") or "").strip()
        for variation in item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue           # meal-deal-builder component, not a price
            price = variation.get("BasePrice")
            if price is None or not product_name:
                continue
            row_name = _row_name(product_name)
            kcal = _kcal(variation.get("NutritionalInfo"))
            names = [row_name]
            alias = _PDF_ALIASES.get(product_name.lower())
            if alias:
                names.append(alias)
            for out_name in names:
                key = out_name.lower()
                if not out_name or key in seen:
                    continue
                seen.add(key)
                out.append({
                    "name": out_name,
                    "price_gbp": round(float(price), 2),
                    "basis": "delivery",
                    "store": label,
                    "category": category,
                    "kcal": kcal,
                })

    if not out:
        raise RuntimeError(
            f"leon: {len(raw_items)} items for {label} but none survived "
            f"the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
