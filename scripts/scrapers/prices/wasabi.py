"""Wasabi UK — REAL per-store prices from Wasabi's Just Eat storefront.

WHICH BUSINESS
    `www.wasabi.uk.com` has no priced ordering of its own — `/order-wasabi/`
    and `/order-delivery/` are both static hand-off pages whose only
    outbound ordering links are `deliveroo.co.uk/brands/wasabi`,
    `www.just-eat.co.uk/takeaway/brands/wasabi` and a Uber Eats brand search
    URL — no first-party checkout anywhere. So, like every other Just-Eat
    -only chain in this project, the per-branch priced menu here is read
    from Wasabi's own storefront on Just Eat (`www.just-eat.co.uk`) —
    public, no account — and is labelled as a Just Eat price throughout,
    never implied to be a price Wasabi publishes itself.

Handshake
---------
Identical three-step shape to `subway.py`; see that module for the full
trace of how each URL was found. Every request goes through
`scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of both
the site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Wasabi".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN base
   (read live, not pinned), `...cdn.restaurant.itemsUrl` is the catalogue
   filename, `...cdn.restaurant.menus[]` + `serviceTypes` the two channels.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

TRAP — every item is listed TWICE, once per channel, exactly like Subway
    Every one of the 104 unique product names at Wasabi - Borough appears
    once gated to the delivery `menuGroupId` and once to the collection one
    (checked exhaustively: 234 raw variations / 104 unique names = a clean
    2x, with 13 names appearing 4x because those particular products are
    also cross-listed under a second `Items[]` entry — still 2 channel
    copies each). Reading without filtering by `MenuGroupIds` double-counts
    every product. Checked every duplicate name for a price conflict across
    its copies: zero disagreements. This module reads the **collection**
    group only, the same choice `subway.py` makes.

TRAP — `menus[].categories[].itemIds` is populated on only ONE of the two
       channel copies of each category, the same trap `subway.py` documents
    Both `menuGroupId`s list all 15 category names, but only one copy per
    category carries real `itemIds` (checked: delivery menu's first listing
    of each category is populated, collection menu's SECOND listing of the
    same category is populated — order matters, contents don't). This
    module builds the category map from the union of every non-empty copy
    across both menus, the same fix as `subway.py`/`costa.py`.

NAME DRIFT — five pairs confirmed by exact-or-near calorie match, the same
    method `subway.py` uses
    "Harmony set" (PDF, 620 kcal) ≈ "Harmony Set" (JE, 622 kcal); "Salmon
    sashimi" (182) = "Salmon Sashimi Set" (182); "Salmon teriyaki potto"
    (394) = "Teriyaki Salmon Rice Potto" (394) — NOT the very different
    "Teriyaki salmon rice box" (PDF, 501 kcal), which has no Just Eat
    listing on this branch at all and was checked, not assumed, to be a
    different product from the Potto; "Vegan yasai dragon rolls" (332) =
    "Yasai Dragon Rolls" (332); "Vegan yasai set" (478) ≈ "Yasai Roll Set"
    (477). Every alias here is a same-or-near kcal pair confirmed on this
    store's data, not a guess from similar-looking words. Plain-name pairs
    that already share tokens regardless of word order ("Salmon nigiri set"
    / JE "Nigiri Salmon Set", 292 kcal both; "Rainbow set" / "Rainbow Set";
    "Tokyo salmon set" / "Tokyo Salmon Set"; "Mixed maki set" / "Mixed Maki
    Set") need no alias at all — this project's token-based join already
    ignores word order.

NOT MATCHED, and correctly so
    Every "(excl. dressing)" row in the nutrition PDF (a no-dressing
    variant Wasabi's PDF publishes for several sushi sets) has no separate
    Just Eat product — only the with-dressing version is sold on this
    marketplace, checked directly. Several dishes (Omakase box, Seaweed
    onigiri, Chicken katsu donburi, Tofu donburi, Prawn donburi, Tuna
    dragon roll, single-piece Chicken/Pumpkin katsu, Hot Chicken/Vegetable
    Gyoza, Plain yakisoba, Steamed rice as a side) and every hand-built
    "{item} + {item}" combo row the PDF lists have no Just Eat listing at
    this branch at all. Neither gap is a bug in this module.

PRICE BASIS — collection, from Wasabi's Just Eat storefront
    Rows are labelled "collection" (Just Eat's own Click & Collect service
    type on this listing), the same convention `subway.py` uses. This is a
    real, per-branch price a customer pays today, but it is Wasabi's price
    on a third-party marketplace, not necessarily what the same item costs
    walking in and asking at the counter; no channel for that comparison
    exists online (see `subway.py` for the identical caveat). Delivery is
    not separately reported — every duplicate checked was price-identical
    to its collection copy, so a separate delivery basis would be pretend
    precision.

PER STORE
    Wasabi - Borough (SE1 1NE) is the default — the southernmost Wasabi
    branch Just Eat lists near this project's other south-London defaults
    (a search centred on Sutton itself, SM1 1EZ, and on Wimbledon, SW19,
    returned no Wasabi at all; every other branch found is further into
    central London).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "wasabi"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Wasabi - Borough, SE1 1NE — southernmost Wasabi Just Eat lists near this
#: project's other south-London defaults.
DEFAULT_STORE_SLUG = "wasabi-borough-southwark"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)

#: Just Eat product name (lowercased) -> the nutrition PDF's spelling of the
#: same dish (`data/db/wasabi.json`). Every pairing verified by an exact or
#: near-exact calorie match — see the NAME DRIFT section in the module
#: docstring.
_PDF_ALIASES = {
    "harmony set": "Harmony set",
    "salmon sashimi set": "Salmon sashimi",
    "teriyaki salmon rice potto": "Salmon teriyaki potto",
    "yasai dragon rolls": "Vegan yasai dragon rolls",
    "yasai roll set": "Vegan yasai set",
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"wasabi: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Wasabi branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"wasabi: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"wasabi: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("wasabi")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"wasabi: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"wasabi: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"wasabi: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"wasabi: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("wasabi: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "wasabi: preloadedState.menu.restaurant.cdn.restaurant missing "
            "— the Next.js state shape has moved") from None


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
    """itemId -> category name, from whichever of the two per-category
    copies (see the module docstring's category trap) carries itemIds."""
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
    """Priced Just Eat menu for one Wasabi branch.

    Give a `store_id` (the Just Eat slug, e.g. "wasabi-borough-southwark"),
    or a `postcode` to use the nearest listed branch. Only "collection" is
    offered — every duplicate checked prices identically on delivery too
    (see module docstring), so there is no separate delivery basis to
    select.
    """
    if basis != "collection":
        raise ValueError(f"wasabi: unknown basis {basis!r} (only "
                         f"'collection' — Just Eat delivery prices for this "
                         f"chain are identical, see module docstring)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"wasabi: no Wasabi listed on Just Eat for "
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
        raise RuntimeError(f"wasabi: no itemsUrl for {slug!r}")
    collection_group, _delivery_group = _menu_groups(restaurant)
    if not collection_group:
        raise RuntimeError(f"wasabi: no collection menu group for {slug!r} "
                           f"— this branch may be delivery-only")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"wasabi: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"wasabi: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"wasabi: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Wasabi ({slug})").strip()
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
            if collection_group not in (variation.get("MenuGroupIds") or []):
                continue           # the delivery-channel duplicate of this row
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
            f"wasabi: {len(raw_items)} items for {label} but none survived "
            f"the DealOnly/menu-group filter — the catalogue shape has "
            f"changed")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
