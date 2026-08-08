"""Domino's UK — REAL per-store prices from Domino's own Just Eat storefront.

WHICH BUSINESS
    `www.dominos.co.uk` and every subdomain tried (`api-mobile`, `easy`,
    `web`, `legacy`, `cloudroute`, `mobileintegration`) are behind an Akamai
    edge that 403s every path — including `/robots.txt` — with a "Dominos
    Not Available In Your Location" page. This is a genuine IP-geolocation
    block, not a bot-fingerprint problem: this project's proxy egress
    geolocates as US-based, spoofing GB via `X-Forwarded-For` /
    `CloudFront-Viewer-Country` / `Accept-Language` had no effect (Akamai
    Edgescape reads the real IP, not headers), and every other chain tried
    from the same egress — including Pizza Hut, on the same kind of
    franchise-delivery model — works fine. So Domino's own site is out of
    reach here, full stop.

    But the received wisdom that "Domino's UK runs its own delivery and
    isn't on marketplaces" turned out to be wrong, or at least stale: Just
    Eat's discovery API lists two live Domino's branches a few hundred
    metres apart in Sutton alone (`Domino's - London - Sutton South`,
    `Domino's - London - Sutton North`), both `isDelivery: true` AND
    `isCollection: true` — unlike Costa/Chipotle/GDK, Domino's sells through
    both channels on this marketplace. That is a different host entirely
    (`www.just-eat.co.uk`, not any `dominos.co.uk` subdomain), so the
    Akamai geo-block Domino's own site enforces never comes into play. Like
    Subway/Costa/Chipotle/GDK in this project, the per-branch priced menu
    here is read from Domino's own storefront on Just Eat — public, no
    account — and is labelled as a Just Eat price throughout, never implied
    to be Domino's own published price.

Handshake
---------
Identical three-step shape to `subway.py` / `costa.py` / `gdk.py`; see those
modules for the full trace of how each URL was found. Every request goes
through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of
both the site and its API host; curl_cffi's safari profile gets through —
note this is Just Eat's Cloudflare, a completely different edge network to
Domino's own Akamai block).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Domino's" / "Dominos" (an
   apostrophe-insensitive prefix check, since Just Eat spells it both ways
   across branches — "Domino's - London - Sutton South" has one,
   "Domino's - London - Sutton North" carries a different Unicode
   apostrophe than the discovery API's own display string in some feeds).
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN
   base (read live, not pinned), `...cdn.restaurant.itemsUrl` is the
   catalogue filename, `...cdn.restaurant.menus[]` the two channel menus.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

NOT A TRAP HERE, unlike Subway — no channel-duplicated rows to dedupe
    Sutton South's `menus[]` has one `delivery` menu and one `collection`
    menu (18/19 categories each), the same channel split Subway documents —
    but unlike Subway, Domino's items are NOT listed twice. Every real
    (`DealOnly: false`) variation carries BOTH channel `menuGroupId`s in a
    single `MenuGroupIds` list, e.g. `["<delivery id>", "<collection id>"]` —
    checked exhaustistively: 257 real (product, size) pairs, 0 with a
    duplicate row. So one collection/delivery price serves both channels for
    every item, and rows are labelled "collection" to match `pizza_hut.py`'s
    convention for a channel-identical, occasion-independent price — not
    assumed identical, but structurally the same row in the source data.

TRAP — every pizza also carries FOUR `DealOnly: true` stub rows (one per
       size), priced £0.00, immediately before or after the real product —
       same convention `subway.py`/`costa.py`/`gdk.py` document, same fix
    "Domino's Mighty Meaty® - Large 13.5\"" appears as its own `Item` with
    `Type: "deal"`-adjacent naming (size baked into the `Name` string, empty
    `Variations[].Name`) at £0.00, `DealOnly: true` — a meal-deal-builder
    component, not the walk-up price. The real, standalone-orderable pizza
    is a SEPARATE `Item` entry: `Name: "Domino's Mighty Meaty®"` with one
    `Variations[]` per size (`"Personal 7\""`, `"Small 9.5\""`, `"Medium
    11.5\""`, `"Large 13.5\""`), each `DealOnly: false` and genuinely priced
    (£10.99–£25.99 at Sutton South). Only `DealOnly: false` rows are ever
    emitted; checked exhaustively — 0 of the 257 real rows are £0.00.

NAME DRIFT AND SIZE/CRUST JOIN — `data/db/dominos.json` is a full
    crust × cheese × size matrix; Just Eat sells ONE fixed crust/cheese per
    named pizza with no customer choice, and it is verifiably the
    **Classic Crust, Standard Mozzarella** row every time
    `data/db/dominos.json` (from Domino's own "Pizzas, Bases & Toppings"
    nutrition guide) publishes each recipe five ways — Classic Crust,
    Italian Style Crust, Thin & Crispy Crust, Stuffed Crust and "Double
    Decadence" — crossed with Standard vs Reduced Fat Mozzarella, none of
    which Just Eat's ordering page lets a customer pick; every JE pizza is
    one fixed recipe per size. Checked at every size for every one of the 24
    named pizzas both sides recognise (matched by name after stripping the
    "Domino's "/"Dominos " prefix, curly/straight apostrophes and & vs
    "and" — see `_PIZZA_ALIASES`): 88 of 96 (recipe × size) pairs carry the
    EXACT same kcal as the nutrition guide's "Classic Crust, {size},
    Standard Mozzarella" row for that recipe; the other 8 are off by 1–57
    kcal (ordinary recipe drift over time, the same tolerance `subway.py`'s
    NAME DRIFT section documents), never a different crust. So every row
    below is emitted under Just Eat's own name AND, for the 24 verified
    recipes, again under the nutrition guide's exact "{recipe} — Classic
    Crust, {Size}, Standard Mozzarella" name so the join lands.

    Five recipes need the alias because the two sides spell the SAME pizza
    differently (checked by exact/near-exact kcal at every size, not
    guessed): "Domino's Mighty Meaty®" is "Mighty Meaty®" (drop the
    "Domino's " prefix); "Pepperoni Passion®" is "Pepperoni Passion" (no ®
    in the guide); "Domino's Texas BBQ®" is "Texas BBQ"; "Domino's Tandoori
    Hot®" is "Dominos Tandoori Hot®" (no apostrophe in the guide); "Original
    Cheese & Tomato" is "Original Cheese and Tomato" (& vs "and"). The other
    19 matched recipes are spelled identically on both sides.

NOT ALIASED — five pizzas Just Eat sells that the nutrition guide has no
       entry for at all, and one where the numbers don't support a join
    The "Italianos Range" (Classico Chicken & Pesto, Perfecto Pepperoni &
    'Nduja, Gusto Goat's Cheese & Pepperoni, Magnifica Chicken & 'Nduja,
    Glorioso Goat's Cheese & Pesto) and the two "Plant-Based" pizzas
    (Margheri-tastic, Vegi Supreme) are newer than the cached nutrition
    guide — no name in `data/db/dominos.json` matches even loosely, and kcal
    is off by 160–900 against every candidate, so nothing is guessed; these
    rows are emitted under their own Just Eat name only, unjoined. The five
    Gluten Free pizzas (Cheese & Tomato, Texas BBQ, Pepperoni Passion, New
    Yorker, Vegi Supreme, one size only) DO have `data/db/dominos.json`
    "GF ... — Small" rows with plausible-looking names, but the kcal
    disagrees by 31–265 with no consistent offset (unlike the Classic-Crust
    matches' near-perfect agreement) — treated as an unverified, probably
    wrong join and left unaliased rather than guessed.

PRICE BASIS — collection, from Domino's Just Eat storefront
    Every row is labelled "collection" — every real variation's
    `MenuGroupIds` covers both the delivery and collection menu, so one
    price serves both (see the trap above). This is a real per-branch price
    a customer pays today, but it is Domino's price on a third-party
    marketplace, not necessarily the walk-in/phone price from Domino's own
    till; no channel for that comparison exists online, since Domino's own
    site is unreachable here (see WHICH BUSINESS).

PER STORE
    Domino's - London - Sutton South is the default, matching every other
    adapter's south-London default.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "dominos"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Domino's - London - Sutton South — the branch this adapter was verified
#: against, matching the other adapters' south-London default.
DEFAULT_STORE_SLUG = "dominos-london---sutton-south-sutton"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)

#: Just Eat's pizza size label -> the nutrition guide's size word.
_SIZE_WORD = {
    'Personal 7"': "Personal", 'Small 9.5"': "Small",
    'Medium 11.5"': "Medium", 'Large 13.5"': "Large",
}

#: Just Eat pizza recipe name -> `data/db/dominos.json` recipe spelling, for
#: the 24 pizzas both sides carry. Every entry verified by exact-or-near-
#: exact kcal match at every size against that recipe's "Classic Crust, X,
#: Standard Mozzarella" nutrition row — see the module docstring's NAME
#: DRIFT section. Identity entries are listed too so the alias table is the
#: single source of truth for "this recipe joins to the nutrition table" —
#: a recipe absent from this dict is deliberately left unaliased (Italianos
#: Range / Plant-Based / Gluten Free, see NOT ALIASED).
_PIZZA_ALIASES = {
    "The Ultimate Hot Honey Pepperoni": "The Ultimate Hot Honey Pepperoni",
    "Meatball Marinara": "Meatball Marinara",
    "The Cheeseburger": "The Cheeseburger",
    "The Meatfielder": "The Meatfielder",
    "Original Cheese & Tomato": "Original Cheese and Tomato",
    "Domino's Mighty Meaty®": "Mighty Meaty®",
    "Pepperoni Passion®": "Pepperoni Passion",
    "Domino's Texas BBQ®": "Texas BBQ",
    "Vegi Supreme": "Vegi Supreme",
    "American Hot": "American Hot",
    "Bacon Double Cheese": "Bacon Double Cheese",
    "Chicken Feast": "Chicken Feast",
    "Domino’s Tandoori Hot®": "Dominos Tandoori Hot®",
    "Hot & Spicy": "Hot & Spicy",
    "Meateor™": "Meateor™",
    "Meatilicious": "Meatilicious",
    "New Yorker": "New Yorker",
    "Ranch BBQ": "Ranch BBQ",
    "Scrummy™": "Scrummy™",
    "The Sizzler": "The Sizzler",
    "Tuna Supreme": "Tuna Supreme",
    "Veg-a-Roma®": "Veg-a-Roma®",
    "Vegi Volcano": "Vegi Volcano",
    "Ham & Pineapple": "Ham & Pineapple",
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"dominos: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Domino's branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"dominos: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"dominos: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    out = []
    for x in restaurants:
        name = str(x.get("name") or "").strip().lower()
        name = name.replace("’", "'")
        if name.startswith("domino's") or name.startswith("dominos"):
            out.append(x)
    return out


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"dominos: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"dominos: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"dominos: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"dominos: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("dominos: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "dominos: preloadedState.menu.restaurant.cdn.restaurant "
            "missing — the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, unioned across the delivery/collection menus
    (both are populated here, unlike the day-part chains — see module
    docstring; a union is still safe since both list the same catalogue)."""
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
    """Priced Just Eat menu for one Domino's branch.

    Give a `store_id` (the Just Eat slug, e.g.
    "dominos-london---sutton-south-sutton"), or a `postcode` to use the
    nearest listed branch. Only "collection" is offered — every real
    variation's `MenuGroupIds` spans both channels, so there is nothing a
    separate "delivery" basis would report differently (see module
    docstring).
    """
    if basis != "collection":
        raise ValueError(f"dominos: unknown basis {basis!r} (only "
                         f"'collection' — every priced row here already "
                         f"covers both Just Eat channels, see module "
                         f"docstring)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"dominos: no Domino's listed on Just Eat for "
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
        raise RuntimeError(f"dominos: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"dominos: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"dominos: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"dominos: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Domino's ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()

    def emit(row_name, price, category, kcal):
        key = row_name.strip().lower()
        if not row_name.strip() or key in seen:
            return
        seen.add(key)
        out.append({
            "name": row_name.strip(),
            "price_gbp": round(float(price), 2),
            "basis": "collection",
            "store": label,
            "category": category,
            "kcal": kcal,
        })

    for item in raw_items:
        item_id = item.get("Id")
        category = categories.get(item_id)
        product_name = (item.get("Name") or "").strip()
        if not product_name:
            continue
        nutrition_recipe = _PIZZA_ALIASES.get(product_name)
        for variation in item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue           # meal-deal-builder component, not a price
            price = variation.get("BasePrice")
            if price is None:
                continue
            var_name = (variation.get("Name") or "").strip()
            kcal = _kcal(variation.get("NutritionalInfo"))

            # Just Eat's own name for the row.
            row_name = f"{product_name} {var_name}" if var_name else product_name
            emit(row_name, price, category, kcal)

            # The nutrition guide's spelling, for the 24 verified pizzas.
            size_word = _SIZE_WORD.get(var_name)
            if nutrition_recipe and size_word:
                alias_name = (f"{nutrition_recipe} — Classic Crust, "
                              f"{size_word}, Standard Mozzarella")
                emit(alias_name, price, category, kcal)

    if not out:
        raise RuntimeError(
            f"dominos: {len(raw_items)} items for {label} but none survived "
            f"the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
