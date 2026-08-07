"""Subway UK — REAL per-store prices from Subway's Just Eat storefront.

WHICH BUSINESS
    Subway UK runs no transactional website of its own. `www.subway.com/en-gb`
    (and `order.subway.com`, which just redirects to `www.subway.com`) is a
    pure marketing microsite — menu pages exist but carry no prices, and the
    only "Order Now" link on the homepage points at the gift-card page. The
    site's own nav fragment (`/en-gb/nav.plain.html`) lists MENU, Find A
    Subway, Rewards, About Us, Gift Card — no ordering entry at all. Confirmed
    by walking a real store's page (`restaurants.subway.com/united-kingdom/...`)
    end to end: no order link, no aggregator link, nothing. UK franchisees
    sell delivery/collection exclusively through Just Eat, Uber Eats and
    Deliveroo — Subway UK says so itself in search results for "how to order".
    So the per-store priced menu here is read from **Subway's own storefront
    on Just Eat** (`www.just-eat.co.uk`), which is public, needs no account,
    and is the only place a real, per-branch Subway price exists online. This
    is a different business relationship than Pizza Hut/Greggs (own site) —
    labelled as a Just Eat price throughout, never implied to be Subway's own
    published price.

Handshake
---------
`www.just-eat.co.uk` and its API host sit behind Cloudflare, which resets a
plain-`requests` connection; every request here goes through
`scripts.scrapers.base.fetch_protected` (curl_cffi browser impersonation, safari
profile succeeds where chrome gets RST).

1. **Find a store** — the discovery API, no auth::

       GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}
       -> {"restaurants": [{"id", "name", "uniqueName", "address": {...},
                             "isCollection", "isDelivery", "cuisines": [...]}, ...]}

   Filter to `name` starting "Subway". `uniqueName` is the slug used everywhere
   else.

2. **The store's menu page** — server-rendered Next.js, no auth::

       GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu
       -> <script id="__NEXT_DATA__">{...}</script>

   Inside, `props.appProps.preloadedState.menu.restaurant.cdn.restaurant` carries
   `itemsUrl` (a filename, not a URL), `menus[].menuGroupId` +
   `menus[].serviceTypes` (which group is "collection" and which is "delivery"
   — the hash IDs are not stable across stores, so they are read fresh every
   call, never hardcoded), and `menus[].categories[].itemIds` for category
   names.

3. **The priced catalogue** — a static JSON on Just Eat's menu CDN, whose base
   URL is NOT in the page: it's `clientConfig.jeRestaurantCdnUrls.uk` in the
   same `__NEXT_DATA__` blob (`https://menu-globalmenucdn.je-apis.com` at time
   of writing, but read live rather than pinned)::

       GET {cdnBase}/{itemsUrl}
       -> {"Items": [{"Name", "Type", "Variations": [
             {"Name", "BasePrice", "DealOnly", "MenuGroupIds": [...],
              "NutritionalInfo": {"EnergyDisplay": "1247 kJ/298 kcal"}}, ...
           ]}, ...]}

TRAP — `uk.api.just-eat.io/restaurants/bypostcode/{postcode}` (no `/discovery/`,
       no `/enriched/`) is a dead route now
    It 404s with `{"message":"uri not found"}` — a valid JSON body, HTTP 404,
    easy to mistake for "this postcode has no restaurants" if the status code
    isn't checked. It is a moved endpoint, not an empty result. The live path
    is `/discovery/uk/restaurants/enriched/bypostcode/{postcode}`.

TRAP — every item is listed TWICE, once per channel, and the channel copies
       are NOT distinguished by name
    `Items` has one entry gated to the collection `menuGroupId` and a second,
    identically-named entry gated to the delivery one. Reading the list
    without filtering by `MenuGroupIds` double-counts every product. Checked
    at two stores (Hammersmith, Sutton): where a (name, size) pair exists on
    both channels the price is byte-identical every time (0 differences across
    204–258 matched pairs per store) — so this module reads the **collection**
    group only and reports one row per item, not because delivery is assumed
    equal but because it was measured equal.

TRAP — the same product also appears a THIRD time, priced £0.00–£0.90 and
       `"DealOnly": true` — that is not the walk-up price
    "Chicken Breast 6-inch" carries a stub entry at £0.90 with `DealOnly:
    true`, alongside the real product (name "Chicken Breast", variation name
    "6-inch") at £7.39. The stubs are the pricing components a meal-deal
    builder composes internally (their prices don't even make sense stacked:
    90p + a footlong stub at £1.40 is nowhere near a whole sandwich); reading
    them as the sandwich price would underprice most of the menu by 5–10x.
    Every row emitted here has `DealOnly: false` verified.

TRAP — `menus[].categories[].itemIds` is populated on only ONE of the two
       channel copies of each category
    Each `menus[]` entry lists all 13 categories twice (a quirk of the same
    channel-duplication as the items), and exactly one of the two copies per
    category carries real `itemIds` — the other has `itemIds: []`. Category
    names are built from the union of every non-empty copy across both menus,
    or a genuine miss (roughly a fifth of items, mostly ungrouped "Specials")
    is reported as no category rather than none at all.

NAME DRIFT — the nutrition PDF and Just Eat spell some products differently
    `data/db/subway.json` (the brand nutrition PDF) and this Just Eat catalogue
    disagree on wording for a handful of real products — never guessed, each
    pairing below confirmed by an EXACT calorie match at the same format (sub /
    wrap / salad), the same join method `pizza_hut.py` uses: "Turkey" (PDF) is
    "Turkey Breast" here (312/381/119 kcal exactly, all three formats);
    "Ham and Turkey" is "Turkey & Ham" (327/415/135 kcal exactly); "Tuna
    Mayonaise" is "Tuna Mayo" (400/427/166 kcal exactly); "Spiced Plant Patty"
    is "Plant Patty (VE)" (424/494/232 kcal exactly). Two more are a spacing
    difference only, close but not exact on calories (recipe drifts slightly
    over time): "Garlic Cheesesteak" / "Garlic Cheese Steak" (539 vs 548 kcal)
    and "Big Cheesesteak Toastie" / "Big Cheese Steak Toastie" (458 vs 472).
    Aliased rows repeat the same price under the PDF's spelling so the
    nutrition join lands. Coincidental same-calorie pairs that are NOT the
    same product (e.g. "Lincolnshire Sausage and Bacon" happens to share 446
    kcal with "3x Oat & Raisin Cookie") were checked and rejected — a calorie
    match alone is not proof, only a necessary condition on top of the names
    already looking like the same product.

TRAP — nine PDF rows are filed under "Salads" but are actually Jacket Potato
       nutrition, and the join needs both names
    "Tuna Mayo & Cheese", "Chicken Breast & Cheese", "Ham & Cheese",
    "Chicken Tikka & Cheese", "Turkey & Cheese", "Spicy Italian & Cheese",
    "Rotisserie-Style Chicken & Cheese", "Ham, Turkey & Cheese" and
    "B.M.T & Cheese" all carry a PDF category of Salads (there is no cheese
    filling in a Subway salad) and match, calorie for calorie exactly, this
    store's "{filling} & Cheese Jacket Potato" price rows instead. This
    module does not try to fix the PDF's mislabelled category — it just
    emits the Jacket Potato price under both its own name and the PDF's
    "Salads" spelling, so the join works regardless of which side is wrong.

NAMING — the 6-inch size is unlabelled, matching the nutrition booklet's basis
    Every sized product ships two variations, `"6-inch"` and `"Footlong"`
    (Toasties spell it `"6 Inch"` — both are recognised). The nutrition table
    (`data/db/subway.json`) publishes 6-inch figures under the plain name
    ("Chicken Breast" = 340 kcal, a 6-inch sub), so the 6-inch row here is
    emitted under the plain product name to join it, and Footlong gets its own
    suffixed row so it can never be matched to the 6-inch macros.

PRICE BASIS — collection, from Subway's Just Eat storefront
    Rows are labelled "collection" (Just Eat's own Click & Collect service
    type on this listing). This is a real, per-branch price a customer pays
    today — but it is Subway's price on a third-party marketplace, not
    necessarily what the same item costs walking in and asking at the
    counter; no channel for that comparison exists online. Delivery is
    measured identical at both stores checked (see the trap above), so no
    separate delivery uplift is reported — it would be pretend precision.

PER STORE
    Sutton High Street (SM1 1HF) is the default, chosen to sit next to this
    project's other south-London defaults. Prices are per branch like every
    other adapter here.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "subway"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Subway® Sutton High Street, SM1 1HF — the branch this adapter was verified
#: against, chosen to match the other adapters' south-London default.
DEFAULT_STORE_SLUG = "subway-sutton-high-street"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)

#: Row name (as this module emits it) -> the nutrition PDF's spelling(s) of
#: the same product. Every pairing verified by an exact calorie match at
#: matching format (sub/wrap/salad) — see the NAME DRIFT and mislabelled-
#: category traps in the module docstring. Never derived by eyeballing words.
_PDF_ALIASES = {
    "Turkey Breast": ["Turkey"],
    "Turkey Breast Wrap": ["Turkey Wrap"],
    "Turkey Breast Salad": ["Turkey Salad"],
    "Turkey & Ham": ["Ham and Turkey"],
    "Turkey & Ham Wrap": ["Ham and Turkey Wrap"],
    "Turkey & Ham Salad": ["Ham and Turkey Salad"],
    "Tuna Mayo": ["Tuna Mayonaise"],
    "Tuna Mayo Wrap": ["Tuna Mayonaise Wrap"],
    "Tuna Mayo Salad": ["Tuna Mayonaise Salad"],
    "Plant Patty (VE)": ["Spiced Plant Patty"],
    "Plant Patty (VE) Wrap": ["Spiced Plant Patty Wrap"],
    "Plant Patty (VE) Salad": ["Spiced Plant Patty Salad"],
    "Garlic Cheese Steak": ["Garlic Cheesesteak"],
    "Big Cheese Steak Toastie": ["Big Cheesesteak Toastie"],
    # Jacket Potato rows the PDF mislabels as Salads — see that trap.
    "Tuna Mayo & Cheese Jacket Potato": ["Tuna Mayo & Cheese"],
    "Chicken Breast & Cheese Jacket Potato": ["Chicken Breast & Cheese"],
    "Rotisserie-Style Chicken & Cheese Jacket Potato":
        ["Rotisserie-Style Chicken & Cheese"],
    "Ham & Cheese Jacket Potato": ["Ham & Cheese"],
    "Chicken Tikka & Cheese Jacket Potato": ["Chicken Tikka & Cheese"],
    "Turkey Breast & Cheese Jacket Potato": ["Turkey & Cheese"],
    "Spicy Italian & Cheese Jacket Potato": ["Spicy Italian & Cheese"],
    "Ham, Turkey Breast & Cheese Jacket Potato": ["Ham, Turkey & Cheese"],
    "Classic B.M.T.® Jacket Potato": ["B.M.T & Cheese"],
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"subway: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Subway restaurants Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"subway: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"subway: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("subway")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"subway: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"subway: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"subway: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"subway: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("subway: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "subway: preloadedState.menu.restaurant.cdn.restaurant missing — "
            "the Next.js state shape has moved") from None


def _menu_groups(restaurant: dict) -> tuple[str | None, str | None]:
    """(collection menuGroupId, delivery menuGroupId), read fresh — the hash
    IDs are not stable across stores, so they are never hardcoded."""
    collection = delivery = None
    for menu in restaurant.get("menus") or []:
        types = set(menu.get("serviceTypes") or [])
        if "collection" in types:
            collection = menu.get("menuGroupId")
        if "delivery" in types:
            delivery = menu.get("menuGroupId")
    return collection, delivery


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, from whichever of the two per-category copies
    (see the module docstring's category trap) actually carries itemIds."""
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


def _row_name(product_name: str, variation_name: str) -> str:
    v = (variation_name or "").strip().lower()
    if v in ("", "6-inch", "6 inch"):
        return product_name.strip()
    if v == "footlong":
        return f"{product_name.strip()} Footlong"
    return f"{product_name.strip()} {variation_name.strip()}"


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Subway branch.

    Give a `store_id` (the Just Eat slug, e.g. "subway-sutton-high-street"),
    or a `postcode` to use the nearest listed branch. Only "collection" is
    offered — delivery is measured identical at every branch checked (see the
    module docstring), so there is no separate delivery basis to select.
    """
    if basis != "collection":
        raise ValueError(f"subway: unknown basis {basis!r} (only "
                         f"'collection' — Just Eat delivery prices for this "
                         f"chain are identical, see module docstring)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"subway: no Subway listed on Just Eat for "
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
        raise RuntimeError(f"subway: no itemsUrl for {slug!r}")
    collection_group, _delivery_group = _menu_groups(restaurant)
    if not collection_group:
        raise RuntimeError(f"subway: no collection menu group for {slug!r} — "
                           f"this branch may be delivery-only")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"subway: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"subway: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"subway: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Subway ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        item_id = item.get("Id")
        category = categories.get(item_id)
        for variation in item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue           # meal-deal-builder component, not a price
            if collection_group not in (variation.get("MenuGroupIds") or []):
                continue           # the delivery-channel duplicate of this row
            price = variation.get("BasePrice")
            if price is None:
                continue
            row_name = _row_name(item.get("Name") or "", variation.get("Name") or "")
            kcal = _kcal(variation.get("NutritionalInfo"))
            for name in [row_name] + _PDF_ALIASES.get(row_name, []):
                key = name.lower()
                if not name or key in seen:
                    continue
                seen.add(key)
                out.append({
                    "name": name,
                    "price_gbp": round(float(price), 2),
                    "basis": "collection",
                    "store": label,
                    "category": category,
                    "kcal": kcal,
                })

    if not out:
        raise RuntimeError(
            f"subway: {len(raw_items)} items for {label} but none survived "
            f"the DealOnly/menu-group filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
