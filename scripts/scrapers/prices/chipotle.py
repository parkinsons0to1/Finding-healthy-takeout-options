"""Chipotle UK — REAL per-branch prices from Chipotle's Just Eat storefront.

WHICH BUSINESS
    `www.chipotle.co.uk` is a marketing site with no priced ordering of its
    own — `/menu` shows dishes and calories, never a `£` sign. Every "Order"
    call to action on the site (the homepage tiles, and every branch page on
    the Yext-hosted `locations.chipotle.co.uk` store locator — checked via
    each page's embedded `pageProps` JSON, field `c_orderDeliveryURL`) points
    at `www.chipotle.co.uk/delivery`, a static hand-off page whose only three
    outbound links are `deliveroo.co.uk/brands/chipotle`,
    `www.ubereats.com/gb/brand/chipotle` and
    `www.just-eat.co.uk/takeaway/brands/chipotle` — no first-party checkout
    anywhere. Every UK branch checked on Just Eat's discovery API reports
    `"isCollection": false, "isDelivery": true` — delivery-only on this
    marketplace, the same shape as Costa (`costa.py`). So, like Subway and
    Costa, the per-branch priced menu here is read from Chipotle's own
    storefront on Just Eat (`www.just-eat.co.uk`) — public, no account — and
    is labelled as a Just Eat price throughout, never implied to be a price
    Chipotle publishes itself.

Handshake
---------
Identical three-step shape to `subway.py` / `costa.py`; see those modules for
the full trace of how each URL was found. Every request goes through
`scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of both the
site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Chipotle".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN base
   (read live, not pinned), `...cdn.restaurant.itemsUrl` is the catalogue
   filename.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

WHY THIS CHAIN NEEDS ITS OWN COMBO LOGIC, NOT JUST A DealOnly FILTER
    `data/db/chipotle.json` (this project's nutrition table) is PDF-derived
    and per-*ingredient* — "Chicken" (185 kcal), "Steak" (165 kcal),
    "Barbacoa" (154 kcal), "Carnitas" (210 kcal), "Sofritas (braised tofu)"
    (84 kcal) are rows for the protein alone, not a purchasable dish. Nobody
    orders "a Chicken" at Chipotle — they order a Burrito/Bowl/Salad/Tacos
    *with* Chicken, and the till only ever prices the whole assembled item.
    `scripts/api/prices.py`'s `ESTIMATED_PRICES["chipotle"]` already worked
    around this by keying flat estimates ("chicken": 9.45, "steak": 10.45, …)
    to the bare protein name, i.e. pricing the ingredient row as if it were
    "a standard build with this protein". This module reproduces that same
    convention with a real price instead of a guess: Just Eat's catalogue
    represents a build as one `DealOnly: false` base product (e.g. "Burrito",
    £13.50) immediately followed, in catalogue order, by a run of
    `DealOnly: true` protein/topping options (their `BasePrice` is the
    *added* cost, e.g. "Steak 🌶️" +£1.40) — this is the same DealOnly
    convention `subway.py`/`costa.py` document, just consumed additively
    instead of filtered out. This module walks the flat item list keeping the
    most recent adult base item (Burrito, Burrito Bowl, Quesadilla, Salad,
    Tacos (3) — Kid's-menu bases are explicitly excluded, see the trap below)
    and sums base + addon for every protein that follows it, emitting one row
    per protein name once the value is confirmed stable.

TRAP — the Kid's menu reuses the exact same protein items at a different base
       price, and naive positional pairing conflates the two
    "Kid's Build Your Own Tacos" (£8.85) is immediately followed by the same
    `Chicken` / `Steak 🌶️` / `Carnitas` / `Barbacoa 🌶️` items (now costing
    +£0.05 each) as the adult builds. Reading every DealOnly-protein
    positionally paired to *whatever* base item preceded it, without
    filtering, yields two different "Chicken" prices (£13.50 adult vs £8.90
    kids) for the same key — checked at Dulwich (East Dulwich) and it is
    exactly this collision. This module tracks `current_base` only while the
    most recent `DealOnly: false` item's name does not start with "Kid's",
    so kids' combo prices are never mixed into the adult rows.

VERIFIED STABLE ACROSS BASE TYPES
    At every branch checked, each protein's added cost is identical whichever
    adult base it follows — Chicken is £13.50 whether it is a Burrito, Bowl,
    Salad, Quesadilla-filling equivalent, or Tacos (3); Steak/Barbacoa are
    always +£1.40 (£14.90 total), Carnitas always +£1.00 (£14.50 total). So
    one row per protein is emitted (not one per base type) — checked, not
    assumed: every base type produced the same combo total for the same
    protein at Dulwich before this was relied on.

NAME DRIFT — Just Eat's protein names need aliasing to the nutrition PDF's
    "Braised Beef Barbacoa 🌶️" (Just Eat) is "Barbacoa" (nutrition); a
    trailing chilli emoji is stripped from "Steak 🌶️"/"Barbacoa 🌶️" to get
    the plain name; "Sofritas 🌱"/"Sofritas🌱" (emoji spacing is inconsistent
    in the catalogue) becomes "Sofritas (braised tofu)"; "Chicken" and
    "Carnitas" already match the nutrition table exactly, no alias needed.

NOT EMITTED — no-priced-signal ingredients
    Rice, beans, tortilla, fajita veggies, salsas, cheese-as-topping, sour
    cream and lettuce have no standalone Just Eat price at all (they're
    bundled into the base build's £13.50, or in one case — "Fajita Veggie",
    "Cheese" as a quesadilla filling, "Veggie" — priced as a £0.00 filler
    choice with the same DealOnly convention, meaning free, not "no price
    found"). Guessing a price for these from an unrelated side item (e.g.
    treating "Tortilla on the Side (VG)" at £1.80 as the burrito's tortilla)
    would be inventing a number nothing on the menu supports, so this module
    does not emit rows for them at all — only the five proteins get a real
    price, matching exactly what `ESTIMATED_PRICES["chipotle"]` already
    scoped itself to.

PRICE BASIS — delivery, from Chipotle's Just Eat storefront
    Every row is labelled "delivery" — the only service type Chipotle lists
    on this marketplace at every branch checked (see the WHICH BUSINESS
    section). This is a real per-branch price a customer pays today, but it
    is Chipotle's price on a third-party platform with Just Eat's markup
    baked in, not necessarily the counter price walking into the shop; no
    channel for that comparison exists online (see `subway.py` for the
    identical caveat). It is measurably higher than the old estimates: a
    Chicken build here is £13.50 against the £9.45 this project had guessed.

PER STORE
    Chipotle Mexican Grill - Dulwich (East Dulwich), SE22 8EP is the default
    — the nearest Chipotle branch to this project's other south-London
    defaults (there is none in Sutton itself; checked a wide radius around
    SM1 1EZ and found no Chipotle at all).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "chipotle"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Chipotle Mexican Grill - Dulwich (East Dulwich), SE22 8EP.
DEFAULT_STORE_SLUG = "chipotle-mexican-grill---dulwich-east-dulwich"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

#: Adult base item names whose DealOnly protein run should be summed. Any
#: base item name NOT starting "Kid's" is accepted too (new limited-time
#: bases have appeared, e.g. "Go Half Veggie Bowl") — this set only matters
#: for excluding the Kid's menu explicitly, see the module docstring's trap.
_KIDS_PREFIX = "kid's"

#: Just Eat protein item name (cleaned of emoji/whitespace) -> the nutrition
#: PDF's spelling of the same protein (`data/db/chipotle.json`). Only the two
#: that actually differ need an entry; identity ones fall through unchanged.
_PDF_ALIASES = {
    "braised beef barbacoa": "Barbacoa",
    "sofritas": "Sofritas (braised tofu)",
}

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF☀-➿️]", re.UNICODE)


def _clean_protein_name(raw: str) -> str:
    name = _EMOJI_RE.sub("", raw).strip()
    return name


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"chipotle: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Chipotle branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"chipotle: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"chipotle: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("chipotle")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"chipotle: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"chipotle: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"chipotle: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"chipotle: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("chipotle: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "chipotle: preloadedState.menu.restaurant.cdn.restaurant missing "
            "— the Next.js state shape has moved") from None


def fetch_prices(store_id: str | None = None, basis: str = "delivery",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Chipotle branch — five protein builds.

    Give a `store_id` (the Just Eat slug, e.g.
    "chipotle-mexican-grill---dulwich-east-dulwich"), or a `postcode` to use
    the nearest listed branch. Only "delivery" is offered — every branch
    checked lists `isCollection: false` on Just Eat.
    """
    if basis != "delivery":
        raise ValueError(f"chipotle: unknown basis {basis!r} (only "
                         f"'delivery' — Chipotle's Just Eat storefront has no "
                         f"collection service type at any branch checked)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"chipotle: no Chipotle listed on Just Eat for "
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
        raise RuntimeError(f"chipotle: no itemsUrl for {slug!r}")

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"chipotle: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"chipotle: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"chipotle: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Chipotle ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    # protein name -> {combo prices seen}, so a discrepancy across base types
    # is visible rather than silently averaged away.
    combos: dict[str, set[float]] = {}
    current_base: tuple[str, float] | None = None
    for it in raw_items:
        variations = it.get("Variations") or []
        if not variations:
            continue
        v = variations[0]
        deal_only = v.get("DealOnly")
        price = v.get("BasePrice")
        item_name = (it.get("Name") or "").strip()
        if deal_only is False:
            current_base = (None if item_name.lower().startswith(_KIDS_PREFIX)
                            else (item_name, float(price or 0)))
            continue
        if deal_only is True and current_base is not None and price is not None:
            protein = _clean_protein_name(item_name)
            key = protein.lower()
            if key not in ("chicken", "steak", "barbacoa", "braised beef barbacoa",
                          "carnitas", "sofritas"):
                continue  # topping/filler choice (cheese, veggie, fajita veggie…)
            combo_price = round(current_base[1] + float(price), 2)
            combos.setdefault(protein, set()).add(combo_price)

    if not combos:
        raise RuntimeError(
            f"chipotle: {len(raw_items)} items for {label} but no base+protein "
            f"pairs were found — the DealOnly/base-run convention has changed")

    out: list[dict] = []
    for protein, prices in combos.items():
        if len(prices) != 1:
            # A protein priced differently depending on which base preceded
            # it (beyond the known Kid's-menu split, already excluded) means
            # the positional-pairing assumption broke — surface it loudly
            # rather than silently picking one.
            raise RuntimeError(
                f"chipotle: {protein!r} combo price is not stable across base "
                f"types at {label} ({sorted(prices)}) — positional base/"
                f"protein pairing is no longer safe to assume")
        price = next(iter(prices))
        display_name = _PDF_ALIASES.get(protein.lower(), protein)
        out.append({
            "name": display_name,
            "price_gbp": price,
            "basis": "delivery",
            "store": label,
            "category": "Build Your Own - Burrito, Bowl, Salad or Tacos",
        })

    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
