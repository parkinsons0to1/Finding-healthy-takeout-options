"""Pret A Manger UK — REAL per-store prices from Pret's Just Eat storefront.

WHICH BUSINESS
    `www.pret.co.uk` publishes its own priced menu JSON (`_next/data/.../
    products/categories/{category}.json`, the source `data/db/pret.json`'s
    nutrition rows already come from) but that endpoint carries **no
    price** — only nutrition, ingredients and allergens. The site's own
    "Order Online" entry (`/en-GB/orderonline`) is a static hand-off page:
    its outbound links are `deliveroo.co.uk/brands/pret-a-manger`,
    `www.just-eat.co.uk/takeaway/brands/pret-a-manger` and
    `www.ubereats.com/gb/brand/pret-a-manger` — no first-party checkout
    anywhere on the marketing site. So, like Chipotle/Subway/Costa/itsu/
    LEON, the per-branch priced menu here is read from Pret's own storefront
    on Just Eat (`www.just-eat.co.uk`) — public, no account — and is
    labelled as a Just Eat price throughout, never implied to be a price
    Pret publishes itself. Unlike Costa/Chipotle/LEON, Pret - Sutton lists
    BOTH `isCollection: true` and `isDelivery: true` on the discovery API.

Handshake
---------
Identical three-step shape to `subway.py`/`costa.py`/`chipotle.py`/`itsu.py`/
`leon.py`; see `subway.py` for the full trace of how each URL was found.
Every request goes through `scripts.scrapers.base.fetch_protected`
(Cloudflare sits in front of both the site and its API host; curl_cffi's
safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Pret".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN base
   (read live, not pinned), `...cdn.restaurant.itemsUrl` is the catalogue
   filename, `...cdn.restaurant.menus[]` the two service-type menus.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

NOT A TRAP HERE, unlike Subway — no channel duplication
    Every one of the 714 items at Pret - Sutton carries BOTH menuGroupIds
    (delivery and collection) on its single `Variations[0]`, with one price
    for both — checked exhaustively, 714/714. Same shape as `itsu.py`. This
    module reads every `DealOnly: false` row once and labels it
    "collection" (matching `itsu.py`'s/`subway.py`'s convention for a
    channel-identical price).

TRAP — 480 of 714 items are `DealOnly: true` meal-deal-builder components,
       the same near-zero stub shape `subway.py`/`chipotle.py`/`itsu.py`
       document
    Only `DealOnly: false` rows are ever emitted — the same rule as every
    other Just Eat adapter here.

NOT A TRAP — `"Type": "deal"` does not mean "meal-deal bundle" on this menu
    Unlike itsu's one `Type: "deal"` bundle item, 40 of Pret's `DealOnly:
    false` real products (every hot/iced coffee, tea, frappé — "Latte",
    "Cappuccino", "Iced Chai Latte", …) are typed `"deal"` rather than
    `"menuitem"`, for reasons internal to Just Eat's catalogue tooling —
    they are standalone, individually priced drinks, not bundles. This
    module reads `DealOnly`, never `Type`, to decide what is a real price.

TRAP — the same product is listed under two different Item IDs with an
       identical price, not two different prices
    20 product names (e.g. "Banoffee Pot", "Pret's Lobster Roll",
    "Coronation Chicken") each appear as 2-3 separate `Items[]` entries —
    almost certainly because Just Eat's Sutton catalogue cross-lists a
    product into more than one category. Checked every duplicate name for a
    price conflict across its copies: zero disagreements (every duplicate
    agrees to the penny and, where present, the kcal). This module dedupes
    by lowercased name and keeps the first price seen, which is safe because
    they never disagree — not because collisions are silently favoured.

TRAP — one non-DealOnly row is a literal £0.00 "Allergen Guide" listing, not
       a free product
    Unlike the DealOnly stubs, this one survives the DealOnly filter — it's
    a real, standalone catalogue entry Just Eat prices at exactly £0.00,
    presumably a link-out rather than a purchasable item. Nothing else on
    this menu is genuinely free, so rows are dropped on `price <= 0`, not
    just `price is None`.

TRAP — one product name carries an invisible Unicode zero-width space
    "Korean BBQ Tofu Super Plate" ships from the CDN as
    `"Korean BBQ Tofu Super Plate​"` — a trailing zero-width space
    that is invisible in any UI but breaks a literal string match. This
    module strips zero-width/format Unicode characters (`​`, `‌`,
    `‍`, `﻿`) from every product name before using it, both for
    the emitted row name and for alias lookups.

NAME DRIFT — sixteen pairs confirmed by exact-or-near calorie match, the
    same method `subway.py` uses
    Portion-naming drift ("Bircher Muesli" PDF / "Bircher Muesli Bowl" JE,
    338/343 kcal), "Bloomer" dropped from three toastie names ("Classic
    Cheese Bloomer Toastie" 638 = "Classic Cheese Toastie" 638; "Ham &
    Cheese Bloomer Toastie" 592 = "Ham & Cheese Toastie" 592; "Tuna Melt
    Bloomer Toastie" 552 = "Tuna Melt  Toastie" [sic, double space in the
    catalogue] 552), "&"-vs-"and" ("Ham & Cheese" PDF 531 = "Ham and
    Cheese" JE 531), an apostrophe token break ("The Pret Lobster Roll" 340
    = "Pret's Lobster Roll" 339), an accented-e drop ("Vanilla Matcha
    Frappe" 431 = "Vanilla Matcha Frappé" 431 exactly; "Classic Frappe" 365
    vs "Classic Frappé" 350 — close but not exact, aliased anyway, the same
    recipe-drift call `subway.py` makes for its Garlic Cheesesteak pair), a
    "Super Plate" portion suffix on four proteins ("Chipotle Chicken" 709 ≈
    "Chipotle Chicken Super Plate" 710; "Shawarma Chicken" 608 = "Shawarma
    Chicken Super Plate" 608; "Miso Salmon" 761 = "Miso Salmon Super Plate"
    761; "Korean BBQ Tofu" 449 = "Korean BBQ Tofu Super Plate" 449), a
    genuine mis-spelling ("poppi Strawberry & Lemon" PDF 27 kcal = "poppi
    Strawbery & Lemon" [sic] JE 27 kcal), a "Regular" size qualifier ("Coke
    Can" 140 = "Coke Can Regular" 140; "Coke Bottle" 212 = "Coke Bottle
    Regular" 212), a "Half" dropped even though the JE price/kcal are the
    half-size portion's ("Pole & Line Caught Tuna Half Baguette" 257 = JE's
    plain "Pole & Line Caught Tuna Baguette" 257 — its full-size sibling
    isn't sold on this branch's Just Eat listing at all), a fuller product
    name on the JE side for the same filling ("Wiltshire Cured Ham & Grevé
    Baguette" 596 = "Ham & Greve Baguette" JE 596 — "Slim Ham & Grevé
    Baguette" at 298 kcal, roughly half, is correctly NOT this pair), an
    "Iced Black Americano"/"Iced Americano" naming drop (2 kcal both), and a
    generic-vs-specific product name ("Super Fruit" PDF 88 kcal = "Superfruit
    Salad" JE 88 kcal). Every alias here is a same-or-near kcal pair
    confirmed on this store's data, not a guess from similar-looking words.

NOT MATCHED, and correctly so
    "Chicken Salad" (PDF, 529 kcal) has two token-similar JE candidates
    ("Sandwich Chicken Salad", no kcal published; "Chicken Salad Baguette",
    595 kcal) and neither confirms as the same product, so it is left
    unmatched rather than guessed. "Ham & Cheese" was confirmed via "Ham
    and Cheese" (see above) so is NOT confused with the very different
    "Ham & Cheese Croissant" (312 kcal) or "Ham & Cheese Toastie" (592
    kcal) that share two of its three words. "Crayfish & Rocket",
    "Babyccino", "Choc Bar", "Dark Chocolate Corn Cakes" and the two
    "…Pret's Baked Beans & Egg Pot" breakfast pots have no Just Eat listing
    at this branch at all — checked, not assumed absent.

PRICE BASIS — collection, from Pret's Just Eat storefront
    Rows are labelled "collection" (see the channel-duplication section
    above for why collection and delivery are the same number here). This
    is a real, per-branch price a customer pays today, but it is Pret's
    price on a third-party marketplace, not necessarily what the same item
    costs walking in and asking at the counter; no channel for that
    comparison exists online (see `subway.py` for the identical caveat).

PER STORE
    Pret A Manger - Sutton (SM1 1EX) is the default — Sutton itself has a
    Pret, unlike itsu/LEON, so this uses the same town as this project's
    other south-London defaults rather than the nearest substitute.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "pret"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Pret A Manger - Sutton, SM1 1EX — matches this project's other
#: south-London defaults directly (Sutton itself has a Pret).
DEFAULT_STORE_SLUG = "pret-a-manger---sutton-sutton"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)
#: Zero-width/format Unicode characters that show up invisibly in some
#: product names (see the module docstring's zero-width-space trap).
_INVISIBLE_RE = re.compile(r'[​‌‍﻿]')

#: Just Eat product name (lowercased, invisible chars stripped) -> the
#: nutrition PDF's spelling of the same product (`data/db/pret.json`). Every
#: pairing verified by an exact or near-exact calorie match — see the NAME
#: DRIFT section in the module docstring.
_PDF_ALIASES = {
    "classic frappé": "Classic Frappe",
    "vanilla matcha frappé": "Vanilla Matcha Frappe",
    "pret's lobster roll": "The Pret Lobster Roll",
    "chipotle chicken super plate": "Chipotle Chicken",
    "shawarma chicken super plate": "Shawarma Chicken",
    "miso salmon super plate": "Miso Salmon",
    "korean bbq tofu super plate": "Korean BBQ Tofu",
    "ham and cheese": "Ham & Cheese",
    "superfruit salad": "Super Fruit",
    "bircher muesli bowl": "Bircher Muesli",
    "tuna & cucumber granary": "Tuna & Cucumber",
    "pole & line caught tuna baguette": "Pole & Line Caught Tuna Half Baguette",
    "ham & greve baguette": "Wiltshire Cured Ham & Grevé Baguette",
    "classic cheese toastie": "Classic Cheese Bloomer Toastie",
    "ham & cheese toastie": "Ham & Cheese Bloomer Toastie",
    "tuna melt  toastie": "Tuna Melt Bloomer Toastie",
    "poppi strawbery & lemon": "poppi Strawberry & Lemon",
    "coke can regular": "Coke Can",
    "coke bottle regular": "Coke Bottle",
    "iced americano": "Iced Black Americano",
}


def _clean_name(raw: str) -> str:
    return _INVISIBLE_RE.sub("", raw or "").strip()


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"pret: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Pret branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"pret: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"pret: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("pret")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"pret: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"pret: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"pret: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"pret: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("pret: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "pret: preloadedState.menu.restaurant.cdn.restaurant missing — "
            "the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, unioned across both service-type menus
    (both are fully populated for Pret, but union defensively regardless)."""
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
    """Priced Just Eat menu for one Pret branch.

    Give a `store_id` (the Just Eat slug, e.g.
    "pret-a-manger---sutton-sutton"), or a `postcode` to use the nearest
    listed branch. Only "collection" is offered — every item checked prices
    identically on both service types on this platform (see module
    docstring), so there is no separate delivery basis to select.
    """
    if basis != "collection":
        raise ValueError(f"pret: unknown basis {basis!r} (only "
                         f"'collection' — Just Eat delivery prices for this "
                         f"chain are identical, see module docstring)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"pret: no Pret listed on Just Eat for "
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
        raise RuntimeError(f"pret: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"pret: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"pret: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"pret: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Pret A Manger ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        item_id = item.get("Id")
        category = categories.get(item_id)
        product_name = _clean_name(item.get("Name") or "")
        for variation in item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue           # meal-deal-builder component, not a price
            price = variation.get("BasePrice")
            # `price is None` alone lets through a literal £0.00 "Allergen
            # Guide" row that Just Eat lists as a real, non-DealOnly product
            # on this menu — an informational link, not a free item. `> 0`
            # rather than `!= 0` since nothing on this menu is genuinely free.
            if not price or price <= 0 or not product_name:
                continue
            kcal = _kcal(variation.get("NutritionalInfo"))
            names = [product_name]
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
                    "basis": "collection",
                    "store": label,
                    "category": category,
                    "kcal": kcal,
                })

    if not out:
        raise RuntimeError(
            f"pret: {len(raw_items)} items for {label} but none survived "
            f"the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
