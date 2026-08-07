"""itsu UK — REAL per-store prices from itsu's Just Eat storefront.

WHICH BUSINESS
    `www.itsu.com` is a Nuxt marketing site (menu pages exist under `/menu/`
    but carry calories and ingredient copy, never a `£` sign — checked
    `/menu/`, `/menu/rice-bowls/`, `/menu/noodles/`, `/menu/sushi-and-poke/`,
    `/menu/gyoza-and-bao/`, `/loyalty/`: no priced ordering anywhere, no
    "Order Now" link even in the nav). The store locator (`/location/`) is
    the only page that ties a branch to ordering — each branch record in its
    embedded payload carries `deliveroo_url`, `uber_eats_url` and
    `just_eat_url` fields (the same three-marketplace hand-off shape
    `chipotle.py` documents from a Yext locator instead), and a wide sample
    of branches were checked with none carrying any other ordering link. So,
    like Chipotle/Subway/Costa, the per-branch priced menu here is read from
    itsu's own storefront on Just Eat (`www.just-eat.co.uk`) — public, no
    account — and is labelled as a Just Eat price throughout, never implied
    to be a price itsu publishes itself.

Handshake
---------
Identical three-step shape to `subway.py`/`costa.py`/`chipotle.py`; see
`subway.py` for the full trace of how each URL was found. Every request goes
through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of
both the site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "itsu".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN base
   (read live, not pinned), `...cdn.restaurant.itemsUrl` is the catalogue
   filename, `...cdn.restaurant.menus[]` the two service-type menus.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

NOT A TRAP HERE, unlike Subway — no channel duplication
    Subway's catalogue lists every item twice, once per `menuGroupId`
    (collection vs delivery), because each variation is gated to a single
    channel. itsu's catalogue does the opposite: every one of the 106 items
    checked at both Wimbledon and Baker Street 15 carries BOTH menuGroupIds
    (delivery and collection) on its single `Variations[0]`, with an
    identical price either way — there is nothing to double-count and no
    channel choice to make. Checked exhaustively (`Counter` over every
    variation's `MenuGroupIds` tuple): 106/106 items at Wimbledon carry
    exactly the same two-ID pair. So this module reads every `DealOnly:
    false` row once and labels it "collection" (matching `subway.py`'s
    convention for a channel-identical price), not because delivery is
    assumed equal but because the catalogue only ever expresses one price
    for both.

TRAP — meal-deal-builder components carry the real item's name at a
       near-zero DealOnly price, exactly like Subway's/Chipotle's stub rows
    The one `Type: "deal"` product ("hot bowl & gyoza [for 1]", £16.75) is
    immediately followed by eight `DealOnly: true` items — "spicy chicken
    teriyaki" at £0.20, "Thai veggie'balls curry" at £0.00, and so on — which
    are the flavour choices the deal's picker composes internally, not a
    price for that dish on its own. Every one of those eight names also
    exists as its own standalone `DealOnly: false` product elsewhere in the
    same catalogue at its real price (e.g. "Thai chicken curry" is £10.85 as
    a real dish, £0.10 as the deal-builder stub) — reading the stub instead
    of the real row would silently zero out eight prices. Only `DealOnly:
    false` rows are ever emitted, same rule as every other Just Eat adapter
    in this project.

NAME DRIFT — three noodle bowls and one sushi box, confirmed by exact
    calorie match, the same method `subway.py` uses
    Just Eat calls three dishes "{Flavour} noodle'bowl" where the nutrition
    PDF (`data/db/itsu.json`) drops "bowl": "katsu curry noodle'bowl" (451
    kcal) = "katsu curry noodles" (451 kcal); "Thai noodle'bowl" (558) =
    "Thai noodles" (558); "Korean spicy noodle'bowl" (495) = "Korean spicy
    noodles" (495). Likewise "veggie sushi collection" (644 kcal) is the
    nutrition PDF's "veggie sushi selection" (644 kcal). Every pairing here
    is an exact kcal match at the same price point, not a guess from
    similar-looking words; aliased rows repeat the same price under the
    PDF's spelling so the nutrition join lands.

NOT MATCHED, and correctly so — hot-bar and coffee-counter items aren't on
    this menu at all
    Roughly half the nutrition PDF's rows (porridge, egg pots, brewed
    coffee/matcha drinks, plain "coca cola") have no Just Eat counterpart at
    any price, checked, not assumed — itsu's Just Eat storefront sells
    packaged/prepared food and canned drinks only, never a made-to-order
    coffee or a bowl scooped from the hot bar, so there is no price for
    those items to find on this platform. Conversely, several Just Eat rows
    ("California rolls", "super salmon light", "tuna tartare poké", every
    sharing platter) have no nutrition-PDF counterpart either — the PDF
    simply doesn't cover them. Neither gap is a bug in this module; both are
    reported honestly via the resulting nutrition-join hit rate rather than
    forced to match.

PRICE BASIS — collection, from itsu's Just Eat storefront
    Rows are labelled "collection" (see the channel-duplication section
    above for why collection and delivery are the same number here). This is
    a real, per-branch price a customer pays today, but it is itsu's price
    on a third-party marketplace, not necessarily what the same item costs
    walking in and asking at the counter; no channel for that comparison
    exists online (see `subway.py` for the identical caveat).

PER STORE
    itsu - Wimbledon (SW19 3RU) is the default — the nearest itsu branch to
    this project's other south-London defaults found on Just Eat (a search
    centred on Sutton itself, SM1 1EZ, returned no itsu at all; Wimbledon is
    the closest one that showed up searching outward).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "itsu"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: itsu - Wimbledon, SW19 3RU — nearest itsu to this project's other
#: south-London defaults that Just Eat lists.
DEFAULT_STORE_SLUG = "itsuwimbledon-wimbledon"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)

#: Just Eat product name (lowercased) -> the nutrition PDF's spelling of the
#: same dish (`data/db/itsu.json`). Every pairing verified by an exact
#: calorie match — see the NAME DRIFT section in the module docstring.
_PDF_ALIASES = {
    "katsu curry noodle'bowl": "katsu curry noodles",
    "thai noodle'bowl": "Thai noodles",
    "korean spicy noodle'bowl": "Korean spicy noodles",
    "veggie sushi collection": "veggie sushi selection",
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"itsu: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """itsu branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"itsu: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"itsu: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("itsu")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"itsu: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"itsu: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"itsu: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"itsu: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("itsu: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "itsu: preloadedState.menu.restaurant.cdn.restaurant missing — "
            "the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, unioned across both service-type menus (both
    carry real itemIds here, unlike Subway's asymmetric duplicate)."""
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


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one itsu branch.

    Give a `store_id` (the Just Eat slug, e.g. "itsuwimbledon-wimbledon"), or
    a `postcode` to use the nearest listed branch. Only "collection" is
    offered — every item checked prices identically on both service types on
    this platform (see module docstring), so there is no separate delivery
    basis to select.
    """
    if basis != "collection":
        raise ValueError(f"itsu: unknown basis {basis!r} (only "
                         f"'collection' — Just Eat delivery prices for this "
                         f"chain are identical, see module docstring)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"itsu: no itsu listed on Just Eat for "
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
        raise RuntimeError(f"itsu: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"itsu: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"itsu: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"itsu: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"itsu ({slug})").strip()
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
                continue           # meal-deal-builder flavour choice, not a price
            price = variation.get("BasePrice")
            if price is None or not product_name:
                continue
            key = product_name.lower()
            if key in seen:
                continue
            seen.add(key)
            kcal = _kcal(variation.get("NutritionalInfo"))
            for out_name in [product_name, _PDF_ALIASES.get(key)]:
                if not out_name:
                    continue
                out.append({
                    "name": out_name,
                    "price_gbp": round(float(price), 2),
                    "basis": "collection",
                    "store": label,
                    "category": category,
                    "kcal": kcal,
                })

    if not out:
        raise RuntimeError(
            f"itsu: {len(raw_items)} items for {label} but none survived "
            f"the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
