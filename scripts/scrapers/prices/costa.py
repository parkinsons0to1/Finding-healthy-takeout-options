"""Costa Coffee UK — REAL per-store prices from Costa's Just Eat storefront.

WHICH BUSINESS
    `www.costa.co.uk` has no priced ordering of its own. `/menu` carries
    nutrition only (zero `£` on the page); `/order-online/click-and-collect`
    and `/order-online/delivery` are both static landing pages that hand off
    to the Costa Coffee Club **app** (`app.costa.co.uk/.../ordertab` —
    requires an account, out of scope) or to three third-party marketplaces
    whose brand pages the delivery page itself links to: Deliveroo, Uber Eats
    and Just Eat. Every Costa branch checked on Just Eat's discovery API
    reports `"isCollection": false` — this chain sells **delivery only** on
    the marketplace tier, unlike Subway (`subway.py`), which had both. So the
    per-store priced menu here, like Subway's, is read from Costa's own
    storefront on Just Eat (`www.just-eat.co.uk`) — public, no account — and
    is labelled as a Just Eat price throughout, never implied to be a price
    Costa publishes itself.

Handshake
---------
Same three-step shape as `subway.py`; see that module for the full trace of
how each URL was found. Every request goes through
`scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of both the
site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Costa".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN base
   (read live, not pinned), `...cdn.restaurant.itemsUrl` is the catalogue
   filename, `...cdn.restaurant.menus[]` the day-part menus.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

TRAP — every product still carries a `DealOnly: true` stub at £0.00 (see
       `subway.py`'s matching trap) — same filter, same reason
    "Latte" appears twice: once at £0.00 with `DealOnly: true` (the
    meal-deal-builder component) and once at the real £4.60 with
    `DealOnly: false`. Only `DealOnly: false` rows are ever emitted.

NOT A TRAP HERE, unlike Subway — no channel duplication
    Costa's `menus[]` are day-part menus (breakfast / all-day / …), not one
    copy per service type — there is only one service type, delivery, so
    there is nothing to double-count. A product can legitimately belong to
    several of the four `menuGroupId`s at once (available across day parts);
    checked for name+price conflicts across all four and found none (140
    priced products, 0 disagreements), so this module reads every
    `DealOnly: false` row once, regardless of which day-part menu(s) list it.

LIMITATION — the real priced "Latte" has no size or milk choice at all
    The £0 `DealOnly` stub carries `ModifierGroupsIds` (milk/size options
    live inside the meal-deal builder); the real, standalone-orderable
    "Latte" at £4.60 carries `ModifierGroupsIds: null` — there is no
    customisation on this platform, just one fixed recipe per drink name.
    The nutrition table (`data/db/costa.json`) is far more granular
    ("Latte - Medium - Semi-skimmed - Signature", "Latte - Small - Oat -
    Decaf", …), and nothing here says which of those a plain "Latte" is. No
    alias is guessed for drinks — a wrong milk/size match would be worse than
    no match. Food rows don't have this problem: Costa's nutrition names for
    food ("Almond Croissant (V)", "Chicken Fajita Wrap") already match the
    Just Eat product names directly, no aliasing needed.

PRICE BASIS — delivery, from Costa's Just Eat storefront
    Every row is labelled "delivery" — the only service type Costa lists on
    this marketplace at every branch checked. This is a real per-branch price
    a customer pays today, but it is Costa's price on a third-party platform,
    not necessarily the counter price in the shop; no channel for that
    comparison exists online (see `subway.py` for the identical caveat).

PER STORE
    Costa Coffee - Carshalton High St (SM5 3AX) is the default, chosen to
    match `pizza_hut.py`'s Carshalton default.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "costa"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Costa Coffee - Carshalton High St, SM5 3AX — matches pizza_hut.py's default.
DEFAULT_STORE_SLUG = "costa-carshalton"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"costa: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Costa branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"costa: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"costa: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("costa")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"costa: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"costa: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"costa: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"costa: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("costa: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "costa: preloadedState.menu.restaurant.cdn.restaurant missing — "
            "the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, unioned across every day-part menu."""
    out: dict[str, str] = {}
    for menu in restaurant.get("menus") or []:
        for cat in menu.get("categories") or []:
            name = cat.get("name")
            for item_id in cat.get("itemIds") or []:
                out.setdefault(item_id, name)
    return out


def fetch_prices(store_id: str | None = None, basis: str = "delivery",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Costa branch.

    Give a `store_id` (the Just Eat slug, e.g. "costa-carshalton"), or a
    `postcode` to use the nearest listed branch. Only "delivery" is offered —
    every branch checked lists `isCollection: false` on Just Eat.
    """
    if basis != "delivery":
        raise ValueError(f"costa: unknown basis {basis!r} (only 'delivery' — "
                         f"Costa's Just Eat storefront has no collection "
                         f"service type at any branch checked)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"costa: no Costa listed on Just Eat for "
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
        raise RuntimeError(f"costa: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"costa: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"costa: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"costa: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Costa ({slug})").strip()
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
            if price is None:
                continue
            row_name = (f"{product_name} {variation['Name'].strip()}"
                        if (variation.get("Name") or "").strip()
                        else product_name)
            key = row_name.lower()
            if not row_name or key in seen:
                continue
            seen.add(key)
            out.append({
                "name": row_name,
                "price_gbp": round(float(price), 2),
                "basis": "delivery",
                "store": label,
                "category": category,
            })

    if not out:
        raise RuntimeError(
            f"costa: {len(raw_items)} items for {label} but none survived "
            f"the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
