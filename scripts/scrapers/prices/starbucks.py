"""Starbucks UK — REAL per-store prices from Starbucks' Just Eat storefront.

WHICH BUSINESS
    `www.starbucks.co.uk` carries no priced menu at all — `/menu` embeds a
    huge localisation blob, and every one of its 25 `£` occurrences is
    Rewards/Stars-card copy ("£1 = 10 Stars", "top up between £5 and £100"),
    never a drink or food price. The site's own "Order" call to action
    (`/order-picker`) hands off to three places: the Starbucks UK **app**
    (App Store / Google Play links — account-based ordering, out of scope
    per this project's read-only-no-account rule), and, for anyone without
    the app, brand pages on Deliveroo, Uber Eats and **Just Eat** (all three
    links present on that page). So, like Subway/Costa/Chipotle, the
    per-branch priced menu here is read from Starbucks' own storefront on
    Just Eat (`www.just-eat.co.uk`) — public, no account — and is labelled
    as a Just Eat price throughout, never implied to be a price Starbucks
    publishes itself. The app-based first-party channel is real but
    genuinely blocked by the account requirement; it is not needed here
    because the Just Eat storefront is a full, honestly-labelled substitute.

Handshake
---------
Identical three-step shape to `subway.py`/`costa.py`/`chipotle.py`; see
`subway.py` for the full trace of how each URL was found. Every request goes
through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of
both the site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Starbucks" (also matches the
   "STARBUCKS®" all-caps spelling some branches use).
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN base
   (read live, not pinned), `...cdn.restaurant.itemsUrl` is the catalogue
   filename.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

Every branch checked (Sutton, North Cheam, three central London, two
Manchester, three Birmingham — 8 total) reports `"isCollection": false,
"isDelivery": true` — delivery-only on this marketplace, the same shape as
Costa/Chipotle.

TRAP — drinks are priced as a base ("deal" item, DealOnly:false) plus a
       size upcharge (a same-named "menuitem" item, DealOnly:true), the
       same additive shape `chipotle.py` documents for proteins — but the
       addon here is SIZE, not a filling
    "Caffè Americano" appears as a `deal` item at £4.25 (`DealOnly: false`),
    immediately followed by three `menuitem` entries named "Tall" (+£0.00),
    "Grande" (+£0.60 → £4.85 — wait, verified per-drink, see below), "Venti"
    (+£0.60 further). This module walks the flat item list exactly like
    `chipotle.py`'s combo logic: track the most recent `DealOnly: false`
    item as `current_base`, and for every immediately-following `DealOnly:
    true` item whose name is a known size word (Short/Tall/Grande/Venti —
    Trenta/Solo/Doppio never seen but accepted), sum base + addon. Confirmed
    across all 50 drinks with a size run: the "Tall" addon is £0.00 in every
    case, i.e. the deal's own listed price already IS the Tall price — a
    directly-observed fact, not an assumption. Ristretto Bianco and Flat
    White only ever offer "Short" (no Tall/Grande/Venti at all), consistent
    with them being espresso-based, fixed-volume drinks.

TRAP — the same `DealOnly: true` size/choice items are reused for TWO
       different purposes depending on what precedes them, and only one of
       those runs is a genuine size ladder
    Bundle deals ("Hot Breakfast Bundle" £10.70, "Afternoon Break Bundle",
    "Dinner For One Bundle", "Lunch Bundle") are also `deal` items and are
    also immediately followed by a run of `DealOnly: true` items — but that
    run lists the bundle's food/drink CHOICE options ("All Day Breakfast
    Wrap" +£6.25, "Caffè Americano" +£0.00, "Smoked Bacon Roll" +£6.10, …),
    not sizes. Summing these into the bundle price the way sizes are summed
    would fabricate nonsense combo prices. This module only forms a combo
    when the `DealOnly: true` item's name is a recognised size word; a
    bundle's choice run never matches that whitelist, so bundles are walked
    over and correctly produce no combo rows. Bundle root prices themselves
    are not emitted (nothing in this project's nutrition table is "a
    bundle", and decomposing one into its parts would be a guess).

TRAP — every product with a real price ALSO carries a £0-ish `DealOnly:
       true` stub of itself, exactly the shape `subway.py`/`costa.py`
       document
    E.g. "All Day Breakfast Wrap" appears once at £6.25 with `DealOnly:
    true` (the meal-deal-builder component, inside the Hot Breakfast Bundle's
    choice run) and once at the same £6.25 with `DealOnly: false` (the real,
    standalone product). Only `DealOnly: false` rows are read as prices;
    `DealOnly: true` rows are only ever consumed as size/addon deltas onto a
    tracked base, never as a price by themselves.

WHICH SIZE IS REPORTED
    Grande is used as the reported price for every drink with a size ladder
    (falling back to whichever single size a drink actually offers, e.g.
    "Short" for Ristretto Bianco/Flat White) — Starbucks UK's own app and
    till default new customers to Grande, and it is the middle of the three
    common sizes. `fetch_prices(size=...)` accepts "Tall"/"Grande"/"Venti" to
    override.

NAME DRIFT AND THE MILK PROBLEM — `data/db/starbucks.json` (the Starbucks UK
    beverage allergen book) is per-MILK, not per-size: "Cappuccino - whole
    milk", "Cappuccino - semi-skimmed milk", … (up to 7 milk options per
    drink), one kcal/protein figure per row, no size given at all. Just
    Eat's storefront is the mirror image: it prices by SIZE, and never
    prices milk as a choice at all — no milk-named modifier item exists
    anywhere in the catalogue for any drink, at any branch checked. That
    absence is the basis for this module's join: since Just Eat charges the
    same price for a given drink+size regardless of which milk the till
    pours, one row is emitted **for every milk variant the nutrition table
    lists for that drink**, all carrying the identical Grande price. This is
    not a guess about *which* milk a customer gets — it is the documented
    fact that milk choice does not change the price on this platform. Where
    a drink's nutrition rows carry an irregular milk set (e.g. Brown Sugar
    Cloud Frappuccino only lists almond/coconut/soya/whole, no oat or dairy
    2%/skimmed) or a "(Standard Build)" suffix on one particular milk (seen
    on the three "Cloud Frappuccino" drinks' whole-milk row, and on the four
    protein drinks' single listed milk), `_FAMILY_OVERRIDES` reproduces that
    exact irregular set — read directly off `data/db/starbucks.json`, not
    inferred — rather than assuming the standard 7-milk pattern.

NAME DRIFT — plain (no-milk) drinks and teas need name changes, not milk
    enumeration, each verified by literal comparison against
    `data/db/starbucks.json`: "Caffè Americano"→"Americano", "Iced Caffè
    Americano"→"Iced Americano", "Cold Brew Coffee"→"Cold Brew", "Mint Herbal
    Blend Tea"→"Mint Herbal Blend", "Classic Chai Latte"→"Chai Tea Latte"
    (family), "Iced Chai Latte"→"Iced Chai Tea Latte" (family), "Matcha
    Latte"→"Matcha Green Tea Latte" (family), "Iced Matcha Green
    Latte"→"Iced Matcha Green Tea Latte" (family), "White Chocolate
    Mocha"→"White Mocha" (family), "Iced White Chocolate Mocha"→"Iced White
    Mocha" (family), "Caffè Mocha"→"Mocha" (family), "Caffè Latte"→"Caffe
    Latte" (family — the nutrition book spells it without the grave accent,
    and this project's exact-match join is byte-literal, so the accent must
    be dropped or the join silently fails), "Iced Caffè Latte"→"Iced Latte"
    (family), "Caramel Frappucino® Blended Beverage" (Just Eat's own
    spelling is missing a "p") →"Caramel Frappuccino®" (family), and every
    "… Frappuccino® Blended Beverage" product drops the trailing "Blended
    Beverage" to match the book's shorter product names. "Iced Brown Sugar
    Oat Shaken Espresso" is a single exact row, not a milk family — the oat
    milk is baked into the recipe name itself (there is a *separate* 6-milk
    "Iced Brown Sugar Shaken Espresso" family in the book that Just Eat does
    not currently sell), so it aliases to exactly one nutrition row:
    "Iced Brown Sugar Oat Shaken Espresso - oat drink".

NOT ALIASED — no matching nutrition row exists at all
    A number of newer/seasonal Just Eat products have no entry anywhere in
    the beverage book, checked exhaustively rather than assumed missing:
    the "Caramelised Banana" range (Latte/Matcha Latte/Oat Shaken
    Espresso/Velvet Latte — zero hits for "Caramelised Banana" in the book),
    "Cherry & Pomegranate", "Pink Coconut" and "Caramel/Iced Caramel Protein
    Americano", plus "Filter Coffee". These are still emitted under their
    own Just Eat name (a real, useful price) — they simply will not join to
    a nutrition row until the book is updated to cover them.

NOT EMITTED — food/snack items, real prices but no nutrition counterpart yet
    `data/db/starbucks.json` is drawn entirely from the *beverage* allergen
    book (`SUM26_UK_AllergenBook_CORE_BEVERAGE_v02.pdf` — every one of its
    337 rows is a drink; there is no Starbucks food PDF in this project yet).
    The 71 standalone food/snack products on Just Eat (paninis, croissants,
    cake, crisps, juices, …) are still emitted here under their own Just Eat
    name at their real price — e.g. "Signature Tuna Melt Panini" £7.25,
    "Smoked Bacon Roll" £6.10, "Egg Bites with Three Cheese & Ham" £5.20 —
    because they are real, useful numbers (and measurably higher than this
    project's old estimates: "tuna melt panini" was guessed at £5.75, "bacon
    roll" at £4.45, "ham & cheese toastie" at £5.25 against the real £7.25/
    £6.10/£7.20), but none of them can join to a nutrition row until a food
    PDF is added.

PRICE BASIS — delivery, from Starbucks' Just Eat storefront
    Every row is labelled "delivery" — the only service type Starbucks
    lists on this marketplace at every branch checked. This is a real
    per-branch price a customer pays today, but it carries Just Eat's
    delivery markup and is not necessarily the counter price walking into
    the shop; no channel for that comparison exists online (see
    `subway.py` for the identical caveat).

PER STORE
    Starbucks - Sutton, SM1 1LX is the default, matching `subway.py`'s and
    `costa.py`'s south-London default.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "starbucks"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Starbucks - Sutton, SM1 1LX — matches subway.py/costa.py's default.
DEFAULT_STORE_SLUG = "starbuckssutton-sutton"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

#: Recognised size words for the base+addon combo walk. Order of preference
#: for which size gets reported, see `_pick_size`.
_SIZE_WORDS = {"short", "tall", "grande", "venti", "trenta", "solo", "doppio"}
_SIZE_PREFERENCE = ("grande", "tall", "venti", "short", "trenta", "solo", "doppio")

#: The book's standard 7-milk set, used unless `_FAMILY_OVERRIDES` says
#: otherwise for that particular drink.
_STD_MILKS = [
    ("almond drink", False), ("coconut drink", False), ("oat drink", False),
    ("semi-skimmed milk", False), ("skimmed milk", False),
    ("soya drink", False), ("whole milk", False),
]

#: Just Eat drink name -> the book's family-name prefix, when it differs
#: from the Just Eat name. Milks default to `_STD_MILKS` unless the name
#: also appears in `_FAMILY_OVERRIDES`.
_FAMILY_ALIASES = {
    "Iced Caffè Latte": "Iced Latte",
    "Caramel Frappucino® Blended Beverage": "Caramel Frappuccino®",
    "Caffè Latte": "Caffe Latte",
    "White Chocolate Mocha": "White Mocha",
    "Caffè Mocha": "Mocha",
    "Iced White Chocolate Mocha": "Iced White Mocha",
    "Iced Caffè Mocha": "Iced Mocha",
    "Coffee Frappuccino® Blended Beverage": "Coffee Frappuccino®",
    "Mocha Frappuccino® Blended Beverage": "Mocha Frappuccino®",
    "Caramel Cream Frappuccino® Blended Beverage": "Caramel Cream Frappuccino®",
    "Strawberries & Cream Frappuccino® Blended Beverage": "Strawberries & Cream Frappuccino®",
    "Chocolate Cream Frappuccino® Blended Beverage": "Chocolate Cream Frappuccino®",
    "Cookies & Cream Frappuccino® Blended Beverage": "Cookies & Cream Frappuccino®",
    "Classic Chai Latte": "Chai Tea Latte",
    "Iced Chai Latte": "Iced Chai Tea Latte",
    "Matcha Latte": "Matcha Green Tea Latte",
    "Iced Matcha Green Latte": "Iced Matcha Green Tea Latte",
    # Same name in both, listed for clarity / self-documentation only.
    "Caramel Macchiato": "Caramel Macchiato",
    "Ristretto Bianco": "Ristretto Bianco",
    "Flat White": "Flat White",
    "Cappuccino": "Cappuccino",
    "Iced Caramel Macchiato": "Iced Caramel Macchiato",
    "Classic Hot Chocolate": "Classic Hot Chocolate",
}

#: Just Eat drink name -> explicit (milk suffix, needs "(Standard Build)")
#: list, replacing `_STD_MILKS` for drinks whose book entry is irregular.
#: Every set here was read directly off `data/db/starbucks.json`, not
#: inferred from the standard pattern.
_FAMILY_OVERRIDES: dict[str, list[tuple[str, bool]]] = {
    "Brown Sugar Cloud Frappuccino": [
        ("almond drink", False), ("coconut drink", False),
        ("soya drink", False), ("whole milk", True),
    ],
    "Caramel Mocha Cloud Frappuccino": [
        ("almond drink", False), ("coconut drink", False),
        ("semi-skimmed milk", False), ("soya drink", False),
        ("whole milk", True),
    ],
    "Strawberry Matcha Cloud Frappuccino": [
        ("almond drink", False), ("coconut drink", False),
        ("oat drink", False), ("semi-skimmed milk", False),
        ("skimmed milk", False), ("soya drink", False),
        ("whole milk", True),
    ],
    "Caramel Protein Latte": [
        ("semi-skimmed milk", True), ("whole milk", False),
    ],
}

#: Just Eat drink name -> the single exact nutrition row name (no milk
#: enumeration — either the drink has no milk at all, or the book only ever
#: lists it under one fixed milk).
_SINGLE_ALIASES = {
    "Caffè Americano": "Americano",
    "Iced Caffè Americano": "Iced Americano",
    "Cold Brew Coffee": "Cold Brew",
    "Iced Brown Sugar Oat Shaken Espresso": "Iced Brown Sugar Oat Shaken Espresso - oat drink",
    "Iced Caramel Protein Latte": "Iced Caramel Protein Latte - semi-skimmed milk (Standard Build)",
    "Vanilla Protein Matcha Latte": "Vanilla Protein Matcha Latte - semi-skimmed milk (Standard Build)",
    "Iced Vanilla Protein Matcha Latte": "Iced Vanilla Protein Matcha Latte - semi-skimmed milk (Standard Build)",
    "Mint Herbal Blend Tea": "Mint Herbal Blend",
    "English Breakfast Tea": "English Breakfast Tea",
    "Emperor's Clouds & Mist Tea": "Emperor's Clouds & Mist Tea",
    "Earl Grey Tea": "Earl Grey Tea",
    "Cool Lime Starbucks Refresha® Drink": "Cool Lime Starbucks Refresha® Drink",
    "Peach Iced Tea": "Peach Iced Tea",
    "Strawberry Acai Starbucks Refresha® Drink": "Strawberry Acai Starbucks Refresha® Drink",
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"starbucks: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Starbucks branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"starbucks: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"starbucks: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("starbucks")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"starbucks: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"starbucks: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"starbucks: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"starbucks: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("starbucks: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "starbucks: preloadedState.menu.restaurant.cdn.restaurant missing "
            "— the Next.js state shape has moved") from None


def _pick_size(sizes: dict[str, float], preferred: str | None) -> str:
    if preferred:
        want = preferred.strip().lower()
        for s in sizes:
            if s.lower() == want:
                return s
        raise RuntimeError(f"starbucks: requested size {preferred!r} not "
                           f"offered (have {sorted(sizes)})")
    for want in _SIZE_PREFERENCE:
        for s in sizes:
            if s.lower() == want:
                return s
    return next(iter(sizes))


def _rows_for_drink(je_name: str, price: float) -> list[tuple[str, float]]:
    """The nutrition-table row name(s) a priced Just Eat drink maps to."""
    if je_name in _SINGLE_ALIASES:
        return [(_SINGLE_ALIASES[je_name], price)]
    if je_name in _FAMILY_OVERRIDES:
        prefix = _FAMILY_ALIASES.get(je_name, je_name)
        milks = _FAMILY_OVERRIDES[je_name]
    elif je_name in _FAMILY_ALIASES:
        prefix = _FAMILY_ALIASES[je_name]
        milks = _STD_MILKS
    else:
        # No known nutrition row (seasonal/new item) — still a real price,
        # just not joinable yet. See "NOT ALIASED" in the module docstring.
        return [(je_name, price)]
    out = []
    for milk, standard_build in milks:
        suffix = " (Standard Build)" if standard_build else ""
        out.append((f"{prefix} - {milk}{suffix}", price))
    return out


def fetch_prices(store_id: str | None = None, basis: str = "delivery",
                 postcode: str | None = None, size: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Starbucks branch.

    `size` selects which of a drink's Tall/Grande/Venti prices is reported
    (default Grande, falling back to whatever single size a drink actually
    offers). Only "delivery" is offered — every branch checked lists
    `isCollection: false` on Just Eat.
    """
    if basis != "delivery":
        raise ValueError(f"starbucks: unknown basis {basis!r} (only "
                         f"'delivery' — Starbucks' Just Eat storefront has no "
                         f"collection service type at any branch checked)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"starbucks: no Starbucks listed on Just Eat "
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
        raise RuntimeError(f"starbucks: no itemsUrl for {slug!r}")

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"starbucks: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"starbucks: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"starbucks: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Starbucks ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    # drink base name -> {size: combo price}
    combos: dict[str, dict[str, float]] = {}
    # standalone food/snack products (menuitem, DealOnly:false) by name.
    food: dict[str, float] = {}
    current_base: tuple[str, float, str] | None = None
    for it in raw_items:
        variations = it.get("Variations") or []
        if not variations:
            continue
        v = variations[0]
        deal_only = v.get("DealOnly")
        price = v.get("BasePrice")
        item_name = (it.get("Name") or "").strip()
        item_type = it.get("Type")
        if deal_only is False:
            current_base = (item_name, float(price or 0), item_type)
            if item_type == "menuitem":
                food[item_name] = float(price or 0)
            continue
        if (deal_only is True and current_base is not None and price is not None
                and current_base[2] == "deal" and item_name.lower() in _SIZE_WORDS):
            base_name, base_price, _ = current_base
            combo_price = round(base_price + float(price), 2)
            combos.setdefault(base_name, {})[item_name] = combo_price

    if not combos and not food:
        raise RuntimeError(
            f"starbucks: {len(raw_items)} items for {label} but no priced "
            f"drinks or food were found — the DealOnly/base-run convention "
            f"has changed")

    out: list[dict] = []
    for base_name, sizes in combos.items():
        chosen = _pick_size(sizes, size)
        price = sizes[chosen]
        for row_name, row_price in _rows_for_drink(base_name, price):
            out.append({
                "name": row_name,
                "price_gbp": row_price,
                "basis": "delivery",
                "store": label,
                "category": f"Hot & Iced Beverages ({chosen})",
            })
    for item_name, price in food.items():
        out.append({
            "name": item_name,
            "price_gbp": price,
            "basis": "delivery",
            "store": label,
            "category": "Bakery & Food",
        })

    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
