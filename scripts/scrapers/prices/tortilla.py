"""Tortilla UK — REAL per-store prices from Tortilla's Just Eat storefront.

WHICH BUSINESS
    `www.tortilla.co.uk/order-online` is a static hand-off page — its
    outbound links are `deliveroo.co.uk/brands/tortilla`,
    `www.just-eat.co.uk/takeaway/brands/tortilla` and
    `www.ubereats.com/gb/brand/tortilla` (plus a Just Eat *business* portal
    search link, `app.business.just-eat.co.uk/menus/search?...`, which is a
    partner-side tool, not a customer storefront, and is ignored here) — no
    first-party checkout anywhere on the marketing site. So, like every
    other build-your-own chain in this project, the per-branch priced menu
    here is read from Tortilla's own storefront on Just Eat
    (`www.just-eat.co.uk`) — public, no account — and is labelled as a Just
    Eat price throughout, never implied to be a price Tortilla publishes
    itself.

Handshake
---------
Identical three-step shape to `subway.py`/`chipotle.py`/`itsu.py`/`pret.py`;
see `subway.py` for the full trace of how each URL was found. Every request
goes through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in
front of both the site and its API host; curl_cffi's safari profile gets
through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Tortilla".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN base
   (read live, not pinned), `...cdn.restaurant.itemsUrl` is the catalogue
   filename.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

NOT A TRAP HERE, unlike Subway — no channel duplication
    Every one of the 153 items at Tortilla - Wimbledon carries BOTH
    menuGroupIds (delivery and collection) on its single variation, checked
    exhaustively (153/153) — the same shape as `itsu.py`/`pret.py`. Rows are
    labelled "collection".

WHY THIS CHAIN NEEDS ITS OWN COMBO LOGIC, NOT JUST A DealOnly FILTER
    `data/db/tortilla.json` (this project's nutrition table, from Tortilla's
    own PDF) is per-*ingredient and per-portion-size*: "Chicken Asado
    (MeDiuM Burrito/Bowl)" (133 kcal) and "Chicken Asado (large Burrito/Bowl)"
    (199 kcal) are rows for the protein alone at two different portion
    sizes, never a purchasable dish — the same shape `chipotle.py` documents
    for Chipotle's PDF. Unlike Chipotle, Just Eat's catalogue here does NOT
    price the protein as a `DealOnly` add-on to a base item — it lists each
    protein/format pair as its own fully priced, `DealOnly: false` product
    ("Chicken Asado Burrito" £11.70, "Barbacoa (Beef) Bowl" £13.30, "Carnitas
    (Pork) Salad" £11.70, …), so no additive combo logic is needed, only
    name mapping.

VERIFIED STABLE ACROSS FORMAT — Burrito, Bowl and Salad are the same price
    for a given protein
    Checked at Wimbledon: Chicken Asado is £11.70 as a Burrito, Bowl or
    Salad; Barbacoa (Beef) is always £13.30; Carnitas (Pork), Grilled Veg
    and Vegan Chilli No Carne are always £11.70 — the same "one row per
    protein, not per base type" finding `chipotle.py` documents, verified
    the same way (every format checked, not assumed).

SCOPE — only the two nutrition categories with an unambiguous Just Eat price
    are emitted: "MeDiuM Burrito/Bowl" and "MeDiuM salaD"
    The nutrition PDF splits each protein across eleven size/format
    categories (medium and large Burrito/Bowl, medium and large Salad, Tres
    Tacos, Quesadilla, Nachos Queso, Protein Pots, Balance/Plant Fuel Bowls,
    Kids' Burrito, Cali Caesar Wrap, breakfast formats). Just Eat's
    Burrito/Bowl/Salad items are the medium size (there is no separate
    "Large Chicken Asado Burrito" product on this branch's listing — "Large
    Burrito Meal (for 1)" at £16.90 is a fixed-recipe upsell bundle, not a
    protein-selectable large burrito, so it cannot be used to price the
    "large Burrito/Bowl" nutrition rows). Every other category either has no
    per-protein Just Eat product at all (Tacos, Quesadilla, Nachos, Fuel
    Bowls are single fixed recipes on this menu, not protein-selectable) or
    would require guessing a size correspondence nothing on the menu
    confirms. Rather than invent a number, this module only emits what a
    real Just Eat price supports: the medium Burrito/Bowl category, the
    medium Salad category, and the four standalone "Protein Pot" products
    (which map 1:1 to the nutrition PDF's "protein pots" category by name
    and are sold as their own priced item, not derived).

NAME DRIFT — the nutrition PDF spells the same protein differently across
    its own categories, and Just Eat spells it differently again
    Checked directly, not guessed: the "MeDiuM Burrito/Bowl" and "protein
    pots" categories spell it "Beef Barbacoa", but the "MeDiuM salaD"
    category spells the SAME protein "Barbacoa Beef" (reversed word order,
    within the same PDF). Just Eat spells its Burrito/Bowl/Salad item
    "Barbacoa (Beef)". Similarly "Pork Carnitas" (PDF, both categories) is
    "Carnitas Pork" on Just Eat's Burrito/Bowl item but "Carnitas (Pork)" on
    its Salad item. This module keeps one alias table per nutrition
    category rather than a single global one, because a single table cannot
    represent the PDF disagreeing with itself.

NOT EMITTED — "Grilled Veg (topping)" vs "Grilled Veg (filling)"
    The PDF carries two different "Grilled Veg" rows per category (a
    smaller "topping" portion and a larger "filling" portion); Just Eat's
    "Grilled Veg Burrito/Bowl/Salad" is a single filling-sized portion with
    no separate topping option, so this module aliases only to "…
    (filling)", matching Chipotle's rule of never guessing a size nothing on
    the menu supports.

PRICE BASIS — collection, from Tortilla's Just Eat storefront
    Rows are labelled "collection" (see the channel-duplication section
    above). This is a real, per-branch price a customer pays today, but it
    is Tortilla's price on a third-party marketplace, not necessarily what
    the same item costs walking in and asking at the counter; no channel
    for that comparison exists online (see `subway.py` for the identical
    caveat).

PER STORE
    Tortilla - Wimbledon (SW19 1RE) is the default — the nearest Tortilla to
    this project's other south-London defaults that Just Eat lists (a
    search centred on Sutton itself, SM1 1EZ, returned no Tortilla at all).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "tortilla"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Tortilla - Wimbledon, SW19 1RE — nearest Tortilla to this project's other
#: south-London defaults that Just Eat lists.
DEFAULT_STORE_SLUG = "tortilla-wimbledon-wimbledon"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

#: Just Eat's Burrito/Bowl/Salad item name always ends in one of these
#: format words (optionally followed by a "(VG)"/emoji decoration); stripped
#: to isolate the protein name.
_FORMAT_SUFFIX_RE = re.compile(
    r'\s*(Burrito|Bowl|Salad)\s*(\(VG\))?\s*🌱?\s*$', re.I)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF🧡]", re.UNICODE)

#: JE protein name (lowercased, format suffix stripped) -> the nutrition
#: PDF's spelling in the "MeDiuM Burrito/Bowl" category. Verified by direct
#: reading of `data/db/tortilla.json`, not guessed — see the module
#: docstring's NAME DRIFT section for why this differs from the salad table.
_BURRITO_BOWL_ALIASES = {
    "chicken asado": "Chicken Asado (MeDiuM Burrito/Bowl)",
    "barbacoa (beef)": "Beef Barbacoa (MeDiuM Burrito/Bowl)",
    "carnitas pork": "Pork Carnitas (MeDiuM Burrito/Bowl)",
    "carnitas (pork)": "Pork Carnitas (MeDiuM Burrito/Bowl)",
    "grilled veg": "Grilled Veg (filling) (MeDiuM Burrito/Bowl)",
    "vegan chilli no carne": "Vegan Chilli (MeDiuM Burrito/Bowl)",
}

#: Same idea, for the "MeDiuM salaD" category — note the PDF reverses
#: "Beef Barbacoa" to "Barbacoa Beef" here, within its own document.
_SALAD_ALIASES = {
    "chicken asado": "Chicken Asado (MeDiuM salaD)",
    "barbacoa (beef)": "Barbacoa Beef (MeDiuM salaD)",
    "carnitas pork": "Pork Carnitas (MeDiuM salaD)",
    "carnitas (pork)": "Pork Carnitas (MeDiuM salaD)",
    "grilled veg": "Grilled Veg (filling) (MeDiuM salaD)",
    "vegan chilli no carne": "Vegan Chilli (MeDiuM salaD)",
}

#: JE "{X} Protein Pot" item name -> the nutrition PDF's "protein pots"
#: category row it prices. Confirmed 1:1 by name, no kcal on the JE side to
#: cross-check (protein pots have no NutritionalInfo in this catalogue). The
#: JE name carries a "(NNg of protein)" suffix that varies by protein, so
#: this is matched by prefix, not exact string — see `_pot_key`.
_PROTEIN_POT_ALIASES = {
    "chicken protein pot": "Chicken Asado (protein pots)",
    "beef protein pot": "Beef Barbacoa (protein pots)",
    "pork protein pot": "Pork Carnitas (protein pots)",
    "vegan chilli protein pot": "Vegan Chilli (protein pots)",
}


def _pot_key(item_name: str) -> str | None:
    """JE's protein-pot items carry a "(NNg of protein)" suffix that varies
    per protein (e.g. "Chicken Protein Pot (41g of protein)") — strip any
    trailing parenthetical to match `_PROTEIN_POT_ALIASES`."""
    stripped = re.sub(r'\s*\([^)]*\)\s*$', '', item_name).strip().lower()
    return stripped if stripped in _PROTEIN_POT_ALIASES else None


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"tortilla: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Tortilla branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"tortilla: postcode {postcode!r} rejected by "
                           f"the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"tortilla: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("tortilla")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"tortilla: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"tortilla: menu page HTTP {r.status_code} for "
                           f"{slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"tortilla: __NEXT_DATA__ not found for {slug!r} "
                           f"— the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tortilla: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("tortilla: no UK menu-CDN base in __NEXT_DATA__ "
                           "— clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "tortilla: preloadedState.menu.restaurant.cdn.restaurant "
            "missing — the Next.js state shape has moved") from None


def _protein_and_format(item_name: str) -> tuple[str, str] | None:
    """(protein key, format word lowercased) for a Burrito/Bowl/Salad item
    name, or None if this isn't a format-suffixed item. The format word
    comes from the regex's own capture group rather than a second check
    against the string's tail, because the tail can carry trailing
    decoration ("Salad (VG) 🌱") that a naive endswith("Salad") misses."""
    m = _FORMAT_SUFFIX_RE.search(item_name)
    if not m:
        return None
    stripped = _EMOJI_RE.sub("", item_name[: m.start()]).strip()
    return stripped.lower(), m.group(1).lower()


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Tortilla branch — the five medium
    Burrito/Bowl builds, their Salad equivalents, and the four Protein Pots.

    Give a `store_id` (the Just Eat slug, e.g.
    "tortilla-wimbledon-wimbledon"), or a `postcode` to use the nearest
    listed branch. Only "collection" is offered — every item checked prices
    identically on both service types on this platform (see module
    docstring), so there is no separate delivery basis to select.
    """
    if basis != "collection":
        raise ValueError(f"tortilla: unknown basis {basis!r} (only "
                         f"'collection' — Just Eat delivery prices for this "
                         f"chain are identical, see module docstring)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"tortilla: no Tortilla listed on Just Eat "
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
        raise RuntimeError(f"tortilla: no itemsUrl for {slug!r}")

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"tortilla: items JSON HTTP {r.status_code} for "
                           f"{slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"tortilla: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"tortilla: items JSON for {slug!r} came back "
                           f"empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Tortilla ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    # protein key -> {format: price}, so a cross-format disagreement is
    # visible rather than silently picked.
    burrito_bowl: dict[str, dict[str, float]] = {}
    salad: dict[str, float] = {}
    pots: dict[str, float] = {}

    for it in raw_items:
        variations = it.get("Variations") or []
        if not variations:
            continue
        v = variations[0]
        if v.get("DealOnly"):
            continue
        price = v.get("BasePrice")
        item_name = (it.get("Name") or "").strip()
        if price is None or not item_name:
            continue

        pot_key = _pot_key(item_name)
        if pot_key is not None:
            pots.setdefault(pot_key, float(price))
            continue

        parsed = _protein_and_format(item_name)
        if parsed is None:
            continue
        protein, fmt = parsed
        if fmt == "salad":
            if protein in _SALAD_ALIASES:
                if protein in salad and salad[protein] != float(price):
                    raise RuntimeError(
                        f"tortilla: {protein!r} salad price is not stable "
                        f"at {label} — positional mapping unsafe")
                salad[protein] = float(price)
        else:
            if protein in _BURRITO_BOWL_ALIASES:
                burrito_bowl.setdefault(protein, {})[item_name] = float(price)

    if not burrito_bowl and not salad and not pots:
        raise RuntimeError(
            f"tortilla: {len(raw_items)} items for {label} but no "
            f"protein/format matches were found — the catalogue naming has "
            f"changed")

    out: list[dict] = []
    for protein, by_format in burrito_bowl.items():
        prices = set(by_format.values())
        if len(prices) != 1:
            raise RuntimeError(
                f"tortilla: {protein!r} price is not stable across "
                f"Burrito/Bowl at {label} ({by_format}) — cross-format "
                f"pairing is no longer safe to assume")
        price = next(iter(prices))
        out.append({
            "name": _BURRITO_BOWL_ALIASES[protein],
            "price_gbp": round(price, 2),
            "basis": "collection",
            "store": label,
            "category": "MeDiuM Burrito/Bowl",
        })

    for protein, price in salad.items():
        out.append({
            "name": _SALAD_ALIASES[protein],
            "price_gbp": round(price, 2),
            "basis": "collection",
            "store": label,
            "category": "MeDiuM salaD",
        })

    for pot_key, price in pots.items():
        out.append({
            "name": _PROTEIN_POT_ALIASES[pot_key],
            "price_gbp": round(price, 2),
            "basis": "collection",
            "store": label,
            "category": "protein pots",
        })

    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
