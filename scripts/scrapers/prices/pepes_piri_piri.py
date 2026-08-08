"""Pepe's Piri Piri UK — REAL per-store prices from Pepe's Just Eat storefront.

WHICH BUSINESS
    `pepes.co.uk` (redirected from `www.pepes.co.uk`) links its own "Order
    Now" tiles at `https://<venue>.3s-pos.com` — a Blazor WebAssembly
    click-and-collect app built by 3S POS, the same white-label vendor whose
    US storefront `onlineorder.3s-pos.com/gdkusa` is name-checked in
    `gdk.py`. Unlike Slim Chickens' OrderPay stack, 3S POS's menu API
    (`menuapi.3s-pos.com`) answers anonymous requests with
    `401 WWW-Authenticate: Bearer, Basic` — it needs a real OAuth token from
    `authenticationapi.3s-pos.com/connect/token`, and every grant type found
    in the shipped WASM assemblies (`ThreeSPos.Sales.Core.wasm`,
    `ThreeSPos.Sales.Web.Common.Client.WASM.wasm` — pulled from
    `_framework/blazor.boot.json` and grepped as UTF-16 strings, since these
    are genuine compiled wasm modules, not renamed .NET DLLs) is a `password`
    grant for a named client (`three_s_pos_back_office_app`,
    `three_s_pos_loyalty_app`) needing a real staff/customer login — there is
    no anonymous `client_credentials` client embedded anywhere. So Pepe's own
    site has no reachable anonymous pricing surface (confirmed blocked, not
    just unattempted — see BLOCKED below for the full trail).

    Pepe's own storefront on Just Eat (`www.just-eat.co.uk`) does list every
    branch with `isCollection: true` and `isDelivery: true`, public, no
    account — the same fallback `gdk.py`/`subway.py` use for chains with no
    reachable first-party ordering API. Labelled as a Just Eat price
    throughout, never implied to be Pepe's own till price.

BLOCKED — the direct-site route, for the record
    `https://pepes.3s-pos.com/` -> Blazor WASM SPA, no server-rendered prices.
    `https://menuapi.3s-pos.com/api/SystemsCountries/GetOnlineOrderingSystemsCountry/pepes`
        -> 401, `WWW-Authenticate: Bearer` + `Basic realm="menuapi.3s-pos.com"`.
    `https://authenticationapi.3s-pos.com/.well-known/openid-configuration`
        -> confirms `client_credentials` is a supported grant type in general,
        but no public client_id/secret pair for it ships in the WASM bundle —
        every credential found (`three_s_pos_back_office_app` /
        `3D147462-5037-48EB-9DE0-54521D948BEE`, `three_s_pos_loyalty_app`) is
        wired to the `password` grant, which needs a real account. Not
        reattempted with guessed credentials (this project does not create
        fake accounts or guess secrets).

Handshake (Just Eat)
---------------------
Identical three-step shape to `subway.py`/`gdk.py`; see `subway.py` for the
full trace of how each URL was found. Every request goes through
`scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of both
`just-eat.co.uk` and its API host).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Pepe's Piri Piri".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN
   base, `...cdn.restaurant.itemsUrl` the catalogue filename, and
   `...cdn.restaurant.menus[].serviceTypes`/`menuGroupId` identifies which
   channel-copy of the catalogue is "collection" (see the channel-duplicate
   trap below — read fresh every call, never hardcoded, per `subway.py`'s
   own warning that these hash IDs are not stable across stores).
3. ``GET {cdnBase}/{itemsUrl}`` — the priced, calorie-annotated catalogue.

TRAP — every item is listed TWICE, once per channel, and this store's copies
       are NOT proven price-identical (unlike gdk.py's Sutton branch)
    `menus[]` carries one `delivery` menuGroupId and one `collection`
    menuGroupId, each with its own copy of every product (same shape
    `subway.py`/`gdk.py` document). Checked at the Sutton branch: both
    copies of every product here DO carry the same `BasePrice` — but rather
    than assume that holds at every branch (gdk.py measured its own store,
    it did not assume the finding travels), this module filters explicitly
    on the `collection` `menuGroupId` via `MenuGroupIds`, `subway.py`'s
    approach, so a future branch where the channels really do diverge would
    still emit only real collection prices.

NAME DRIFT — the nutrition table (`data/db/pepes_piri_piri.json`, a brand
    allergen/nutrition matrix) and the Just Eat till disagree in ways
    verified by joining on calories (`EnergyDisplay` on the JE side, `kcal`
    on the nutrition side) at matching price, never by eyeballing the words:

    1. **"1/2"/"1/4" vs "Half"/"Quarter"** — till "Half Chicken" (798 kcal,
       £11.29) = booklet "1/2 Chicken" (798 kcal); till "Quarter Chicken"
       (399 kcal) = booklet "1/4 Chicken" (399 kcal).
    2. **Default nugget/wing/strip counts are implicit on the till** — till
       "Chicken Nuggets" (268 kcal) = booklet "Chicken Nuggets – 5" (268
       kcal); "3x Pepe's Wings"/"5x Pepe's Wings" = booklet "Pepe's Wings –
       3"/"Pepe's Wings – 5"; "3x Tender Strips"/"Pepe's 5 Tender Strips" =
       booklet "Tender Strips – 3"/"Tender Strips – 5"; "4x Chilli Cheese
       Nuggets" = booklet "Chilli Cheese Nuggets"; "5x Crispy Onion Rings" =
       booklet "Onion Rings"; "18x Wings"/"28x Wings" = booklet "Wings X 18
       (Serves 2)"/"Wings X 28 (Serves 3)"; "3x Mozzarella Sticks" = booklet
       "Mozarella Sticks" (booklet's own typo, kept verbatim).
    3. **"Single"/"Double" burger tiers** — till "Gourmet Beef Burger"
       (876 kcal) = booklet "Gourmet Beef Burger – Single"; same pattern for
       Gourmet Lamb, Korean Beef, Korean Lamb, Texan Beef, Texan Lamb. The
       booklet's "– Double" rows (e.g. 1361 kcal Gourmet Beef) have no till
       counterpart at all on this branch's Just Eat listing — left
       unaliased rather than guessed at 2x the single price.
    4. **"Pepe's "-branded dips/desserts drop the brand prefix on the
       till** — "Carrot Cake"/"Chocolate Fudge Cake"/"Churros & Chocolate
       Dip"/"Dark Chocolate Sauce Dip"/"Garlic Mayo Dip"/"Piri Piri Mayo
       Dip"/"Strawberry Cheesecake"/"Sweet Chilli Dip"/"Chimichurri Mayo
       Dip" = booklet "Pepe's Carrot Cake"/"Pepe's Chocolate Fudge
       Cake"/"Pepe's Churros"/"Pepe's Dark Chocolate Sauce"/"Pepe's Garlic
       Mayo"/"Pepe's Piri Piri Mayo"/"Pepe's Strawberry Cheesecake"/"Pepe's
       Sweet Chilli Sauce"/"Pepe's Chimichurri Mayo" (word "Sauce"/"Dip"
       itself also drifts, e.g. "Sweet Chilli Dip" vs booklet "...Sweet
       Chilli Sauce" — each pairing confirmed on matching calories, not
       just the shared "Pepe's" prefix).
    5. **250ml sauce bottles are named by flavour only on the till** — the
       six "Pepe's {flavour} Sauce Bottle 250ml" rows = booklet "Piri Piri
       Sauce – {flavour} 250 ml" (Extra Hot/Extreme/Hot/Lemon & Herb/Mango &
       Lime/Mild); calories collide across several flavours (several sit at
       130 kcal) so this pairing is matched by flavour word, never by kcal
       alone.
    6. **Ice cream tubs** — till "Ben & Jerrys {flavour} Ice Cream {size}ml"
       = booklet "{Flavour} ({size}ml)".
    7. **Fruitshoot flavours split differently** — till "Blackcurrant
       Fruitshoot" (8 kcal) = booklet's oddly-named "Fruit Shoot – Apple &
       Blackcurrant" (8 kcal, presumably a blend the booklet names in full);
       "Orange Fruitshoot" = "Fruit Shoot – Orange".
    8. **J2O flavour spelling** — till "J2O Orange & Passion Fruit" (two
       words) = booklet "J2O – Orange & Passionfruit" (one word).
    9. **Kids meals drop "Chicken"** — till "Kids Burger Meal" = booklet
       "Kids Meal – Chicken Burger" (the booklet's "Chicken" token has no
       till counterpart, so this is a hard alias, not something the shared
       token matcher folds away on its own).
    10. **Platters** — till "Combo"/"Family Platter"/"Mega Platter"/"Solo
        Platter" = booklet "Combo (Serves 2-3)"/"Family (Serves
        3-4)"/"Mega (Serves 5-6)"/"Solo (Serves 1)".

    Left UNALIASED, deliberately, because no till counterpart was found on
    this branch (kcal-matching produced only coincidental collisions on
    shared small values like 8/13/39 kcal, which this module does not
    trust): the "– Double" burger tiers (point 3), the six loose 10ml dip
    cups ("Extra Hot (10ml)" etc — the till only sells them bottled at
    250ml), fountain-drink rows (IRN BRU, Tango, and the "Fountain
    LRG/Reg" Pepsi/7UP variants — this branch's Just Eat listing has no
    fountain-drink lines at all, only bottled equivalents), "Chicken Burger
    – Double", "Chicken Nuggets – 8", "Chimichurri Fries"/"Chimmichurri
    Wedges"/"Piri Piri Fries"/"Piri Piri Onion Rings" (no till match found),
    "Gochujang Flavour" (a newer flavour not on this branch's JE menu), and
    "Pepe's Original" (798/1596-kcal collisions with both chicken sizes made
    this too ambiguous to alias with confidence).

PRICE BASIS — collection, from Pepe's Just Eat storefront
    Every row is labelled "collection", filtered on the `collection`
    `menuGroupId` explicitly (see the channel-duplicate trap above) — real
    per-branch prices, but Just Eat's listing, not necessarily Pepe's own
    till price; no channel for that comparison exists online (see BLOCKED).

PER STORE
    Pepe's Piri Piri - Sutton, SM3 8JR is the default, matching every other
    adapter's south-London default.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "pepes_piri_piri"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Pepe's Piri Piri - Sutton, SM3 8JR.
DEFAULT_STORE_SLUG = "pepes-piri-piri---sutton-sutton"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kcal", re.I)

#: Just Eat till name (lowercased) -> the booklet name(s) it should also
#: match, from the NAME DRIFT section above. Every pairing verified on
#: matching calories (or, where calories collide, on the flavour word),
#: never guessed from the words alone.
_PDF_ALIASES: dict[str, list[str]] = {
    "half chicken": ["1/2 Chicken"],
    "quarter chicken": ["1/4 Chicken"],
    "chicken nuggets": ["Chicken Nuggets – 5"],
    "3x pepe's wings": ["Pepe's Wings – 3"],
    "5x pepe's wings": ["Pepe's Wings – 5"],
    "3x tender strips": ["Tender Strips – 3"],
    "pepe's 5 tender strips": ["Tender Strips – 5"],
    "4x chilli cheese nuggets": ["Chilli Cheese Nuggets"],
    "5x crispy onion rings": ["Onion Rings"],
    "18x wings": ["Wings X 18 (Serves 2)"],
    "28x wings": ["Wings X 28 (Serves 3)"],
    "3x mozzarella sticks": ["Mozarella Sticks"],
    "gourmet beef burger": ["Gourmet Beef Burger – Single"],
    "gourmet lamb burger": ["Gourmet Lamb Burger – Single"],
    "korean beef burger": ["Korean Beef Burger – Single"],
    "korean lamb burger": ["Korean Lamb Burger – Single"],
    "texan beef burger": ["Texan Beef Burger – Single"],
    "texan lamb burger": ["Texan Lamb Burger – Single"],
    "carrot cake": ["Pepe’s Carrot Cake"],
    "chocolate fudge cake": ["Pepe’s Chocolate Fudge Cake"],
    "churros & chocolate dip": ["Pepe’s Churros"],
    "dark chocolate sauce dip": ["Pepe’s Dark Chocolate Sauce"],
    "garlic mayo dip": ["Pepe’s Garlic Mayo"],
    "piri piri mayo dip": ["Pepe’s Piri Piri Mayo"],
    "strawberry cheesecake": ["Pepe’s Strawberry Cheesecake"],
    "sweet chilli dip": ["Pepe’s Sweet Chilli Sauce"],
    "chimichurri mayo dip": ["Pepe’s Chimichurri Mayo"],
    "extra hot dip": ["Pepe’s Extra Hot Sauce"],
    "pepe's extra hot sauce bottle 250ml": ["Piri Piri Sauce – Extra Hot 250 ml"],
    "pepe's extreme sauce bottle 250ml": ["Piri Piri Sauce – Extreme 250 ml"],
    "pepe's hot sauce bottle 250ml": ["Piri Piri Sauce – Hot 250 ml"],
    "pepe's lemon & herb sauce bottle 250ml": ["Piri Piri Sauce – Lemon & Herb 250 ml"],
    "pepe's mango & lime sauce bottle 250ml": ["Piri Piri Sauce – Mango & Lime 250 ml"],
    "pepe's mild sauce bottle 250ml": ["Piri Piri Sauce – Mild 250 ml"],
    "ben & jerrys chocolate fudge brownie ice - cream 100ml":
        ["Chocolate Fudge Brownie (100ml)"],
    "ben & jerrys chocolate fudge brownie ice - cream 465ml":
        ["Chocolate Fudge Brownie (465ml)"],
    "ben & jerrys cookie dough ice cream 100ml": ["Cookie Dough (100ml)"],
    "ben & jerrys cookie dough ice cream 465ml": ["Cookie Dough (465ml)"],
    "blackcurrant fruitshoot": ["Fruit Shoot – Apple & Blackcurrant"],
    "orange fruitshoot": ["Fruit Shoot – Orange"],
    "j2o orange & passion fruit": ["J2O – Orange & Passionfruit"],
    "kids burger meal": ["Kids Meal – Chicken Burger"],
    "combo": ["Combo (Serves 2-3)"],
    "family platter": ["Family (Serves 3-4)"],
    "mega platter": ["Mega (Serves 5-6)"],
    "solo platter": ["Solo (Serves 1)"],
    "fajita wrap": ["Chicken Fajita Wrap"],
    "chicken & cheese quesadilla": ["Chicken Quesadilla"],
    "pepe's piri piri salt bottle 135g": ["Piri Piri Salt Bottle 135g"],
    "1.5 ltr pepsi": ["Pepsi 1.5L"],
    "1.5 ltr pepsi max": ["Pepsi Max 1.5L"],
    "1.5 ltr 7up zero": ["7 Up Free 1.5L"],
    "red bull": ["Redbull"],
    "pepe's wedges": ["Wedges"],
    "pepe's side salad": ["Side Salad"],
    "veggie burger": ["Veggie Burger – Single"],
}

#: Both apostrophe glyphs the Just Eat feed mixes within the SAME item set
#: (straight `'` on "Pepe's Wedges", curly U+2019 on "Pepe’s Extra Hot Sauce
#: Bottle 250ml") are folded to one before an alias lookup, and a trailing
#: "." artefact ("Chicken Nuggets.", "BBQ Wrap.", "Extra Hot Dip.") is
#: stripped — both confirmed present verbatim in the raw feed, not typos
#: introduced here.
def _lookup_key(name: str) -> str:
    n = (name or "").strip()
    if n.endswith("."):
        n = n[:-1].strip()
    return n.lower().replace("’", "'")


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"pepes_piri_piri: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Pepe's Piri Piri branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"pepes_piri_piri: postcode {postcode!r} rejected "
                           f"by the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"pepes_piri_piri: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("pepe's piri piri")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"pepes_piri_piri: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"pepes_piri_piri: menu page HTTP {r.status_code} "
                           f"for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"pepes_piri_piri: __NEXT_DATA__ not found for "
                           f"{slug!r} — the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"pepes_piri_piri: __NEXT_DATA__ was not valid "
                           f"JSON ({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("pepes_piri_piri: no UK menu-CDN base in "
                           "__NEXT_DATA__ — clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "pepes_piri_piri: preloadedState.menu.restaurant.cdn.restaurant "
            "missing — the Next.js state shape has moved") from None


def _collection_group(restaurant: dict) -> str | None:
    """The `collection` channel's menuGroupId — read fresh, never hardcoded
    (these hash IDs are not stable across stores, per subway.py)."""
    for menu in restaurant.get("menus") or []:
        if "collection" in set(menu.get("serviceTypes") or []):
            return menu.get("menuGroupId")
    return None


def _category_map(restaurant: dict) -> dict[str, str]:
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
    """Priced Just Eat menu for one Pepe's Piri Piri branch."""
    if basis != "collection":
        raise ValueError(f"pepes_piri_piri: unknown basis {basis!r} (only "
                         f"'collection' is offered)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"pepes_piri_piri: no Pepe's Piri Piri listed "
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
        raise RuntimeError(f"pepes_piri_piri: no itemsUrl for {slug!r}")
    collection_group = _collection_group(restaurant)
    if not collection_group:
        raise RuntimeError(f"pepes_piri_piri: no collection menu group for "
                           f"{slug!r} — this branch may be delivery-only")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"pepes_piri_piri: items JSON HTTP {r.status_code} "
                           f"for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"pepes_piri_piri: items JSON for {slug!r} was "
                           f"not JSON ({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"pepes_piri_piri: items JSON for {slug!r} came "
                           f"back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Pepe's Piri Piri ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for it in raw_items:
        item_id = it.get("Id")
        category = categories.get(item_id)
        item_name = (it.get("Name") or "").strip()
        for v in it.get("Variations") or []:
            if v.get("DealOnly"):
                continue  # meal-deal-builder component, not a priced line
            if collection_group not in (v.get("MenuGroupIds") or []):
                continue  # the delivery-channel duplicate of this row
            price = v.get("BasePrice")
            if not item_name or price is None:
                continue
            kcal = _kcal(v.get("NutritionalInfo"))
            for name in [item_name] + _PDF_ALIASES.get(_lookup_key(item_name), []):
                key = name.strip().lower()
                if not name.strip() or key in seen:
                    continue
                seen.add(key)
                out.append({"name": name.strip(), "price_gbp": round(float(price), 2),
                            "basis": "collection", "store": label,
                            "category": category, "kcal": kcal})

    if not out:
        raise RuntimeError(f"pepes_piri_piri: {len(raw_items)} items for "
                           f"{label} but none survived the DealOnly/menu-"
                           f"group filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
