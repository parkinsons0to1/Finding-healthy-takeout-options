"""Tim Hortons UK — REAL per-branch prices from Tim Hortons' Just Eat storefront.

WHICH BUSINESS
    `timhortons.co.uk` (note: no `www` — the `www` subdomain's TLS
    certificate does not cover its own hostname, a misconfiguration on
    their end, not this scraper's; the bare domain serves the same site
    correctly) runs no ordering of its own — its homepage carries "in
    partnership with Just Eat / Deliveroo / Uber Eats" logo slides and no
    first-party checkout. Same shape as `costa.py`/`caffe_nero.py`: the
    priced per-branch menu here is read from Tim Hortons' Just Eat
    storefront, never implied to be a price Tim Hortons publishes itself.

NO LONDON BRANCH — checked exhaustively, not assumed
    Querying Just Eat's discovery API from six London postcodes (Wimbledon,
    the City, Stratford, the West End) found zero Tim Hortons listings.
    Manchester and Birmingham postcodes found four. UK Tim Hortons expansion
    has concentrated outside London to date — this is a real gap in
    coverage, not a broken query, confirmed by the same discovery call that
    works for every other Just-Eat-backed adapter here returning >1,000
    unrelated restaurants for the same postcodes.

DELIVERY-ONLY on this platform
    All four branches found report `"isCollection": false, "isDelivery":
    true` — matching `caffe_nero.py`/`costa.py`, unlike `wimpy.py`/`gdk.py`.

Handshake
---------
Identical three-step shape to `caffe_nero.py`/`costa.py`/`wimpy.py`; see
those modules for the full trace. Every request goes through
`scripts.scrapers.base.fetch_protected`.

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Tim Hortons".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__` for the menu-CDN base and `itemsUrl`.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue: 455 items, 249 of
   them non-`DealOnly` (the rest are meal-deal-builder stubs and separately-
   listed bare size upcharges like "Medium - Caramel Iced Latte" that
   duplicate what the sized product's own `Variations[]` already price —
   see the next section).

TRAP — a sized drink is ONE item with three priced `Variations`, not three
       items — and the variation `Name` field is not consistently shaped
    "Caramel Iced Latte" is a single item whose three non-`DealOnly`
    variations are named "Caramel Iced Latte Small" / "... Medium" / "...
    Large" — the *whole* product name repeated, not just the size word.
    Other drinks abbreviate ("Pecan and Golden Sugar Latte SM/MD/LG"), put
    the size first ("Small French Vanilla Latte"), or use a dash ("Latte -
    Small UK"). `_extract_size` strips the product's own name out of the
    variation name (whichever end it's stuck to) and normalises whatever
    single word is left (Small/Sm/S, Medium/Md/M, Large/Lg/L, case-
    insensitive) — verified against every multi-variation item in the
    catalogue at write time, not guessed at from one example.

NAME DRIFT — "(Small)"/"(Large)" convention, and the bare name means Medium
    `data/db/tim_hortons.json` (nutrition) publishes a bare name plus
    "(Small)"/"(Large)" siblings for sized drinks — no "(Medium)" row, the
    bare name already is the medium serving (checked: nutrition "Cappuccino"
    kcal exactly matches JE's Medium variation, not Small or Large). So a
    JE Medium variation is emitted under the bare product name, Small/Large
    variations get " (Small)"/" (Large)" appended, matching the nutrition
    table's own convention rather than JE's.

"NEW!"/"NEW!!" PREFIX — stripped
    ~30 JE items carry a "NEW!"/"NEW!!" marketing prefix
    (`data/db/tim_hortons.json` never does) — stripped before emitting.

MORE NAME DRIFT, each verified rather than guessed
    `_BASE_NAME_ALIASES` renames 6 JE item names to their nutrition-table
    counterpart: "Original Blend"/"Dark Roast" are JE's own item name
    dropping the word "Coffee" that every one of its own *variation* names
    still carries; the four Iced Capp® pairings (JE "Iced Capp®" -> nutrition
    "Original Iced Capp®", "Iced Capp® Supreme Caramel" -> "Caramel Iced
    Capp®", "Iced Capp® Supreme - Oreo" -> "Oreo® Iced Capp®", "Iced Capp®
    Supreme Mocha" -> "Mocha Iced Capp®") are each confirmed by an exact
    kcal match on the Small variation (e.g. 211 kcal on both sides for the
    first pair). Separately, `_FRAPPE_RE` adds a "Frappe" -> "Frappé" alias
    (JE's own spelling has no accent; the nutrition table's does) — one fix
    that resolves 8 drinks x 3 sizes at once, so it's applied as a pattern
    rather than 24 separate table entries. No "Flat White" exists on this
    platform at all — checked directly, not merely absent from the alias
    table.

STORE — Tim Hortons - Manchester Market Street
    No Tim Hortons is listed on Just Eat anywhere near Wimbledon or central
    London (see "NO LONDON BRANCH" above) — Manchester Market Street is the
    first of the four UK branches this platform lists at all.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "tim_hortons"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Tim Hortons - Manchester Market Street — see STORE in the module docstring.
DEFAULT_STORE_SLUG = "tim-hortons-uk--market-street"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_KCAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kcal", re.I)
_NEW_PREFIX_RE = re.compile(r"^NEW!+\s*", re.I)

_SIZE_WORDS = {
    "sm": "Small", "small": "Small",
    "md": "Medium", "medium": "Medium",
    "lg": "Large", "large": "Large",
}
#: Matches a size word anywhere in a variation name, as a whole word —
#: variation names put the size in wildly different places/spellings (see
#: the module docstring's TRAP section), so hunting for the word anywhere
#: is far more robust than assuming a fixed prefix/suffix position.
_SIZE_RE = re.compile(r"\b(small|medium|large|sm|md|lg)\b", re.I)

#: JE product name -> `data/db/tim_hortons.json` nutrition-table base name
#: for the SAME drink. The Iced Capp® pairings verified by an exact kcal
#: match on the Small variation (e.g. JE "Iced Capp®" Small = 211 kcal =
#: nutrition "Original Iced Capp® (Small)"); "Original Blend"/"Dark Roast"
#: are JE's own item name simply omitting the word "Coffee" that every one
#: of its own variation names *and* the nutrition table both carry.
_BASE_NAME_ALIASES = {
    "original blend": "Original Blend Coffee",
    "dark roast": "Dark Roast Coffee",
    "iced capp®": "Original Iced Capp®",
    "iced capp® supreme caramel": "Caramel Iced Capp®",
    "iced capp® supreme - oreo": "Oreo® Iced Capp®",
    "iced capp® supreme mocha": "Mocha Iced Capp®",
}

#: "Frappe" (JE's spelling, no accent) -> "Frappé" (`data/db/tim_hortons.json`'s
#: spelling) as a whole word — affects 8 drinks x 3 sizes. Not the same as
#: an accent-stripping normaliser: JE's own text already has no accent, so
#: the fix is adding one back for the join, not removing one.
_FRAPPE_RE = re.compile(r"\bFrappe\b")


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"tim_hortons: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Tim Hortons branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"tim_hortons: postcode {postcode!r} rejected by "
                           f"the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"tim_hortons: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("tim hortons")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"tim_hortons: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"tim_hortons: menu page HTTP {r.status_code} "
                           f"for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"tim_hortons: __NEXT_DATA__ not found for "
                           f"{slug!r} — the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tim_hortons: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("tim_hortons: no UK menu-CDN base in "
                           "__NEXT_DATA__ — clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "tim_hortons: preloadedState.menu.restaurant.cdn.restaurant "
            "missing — the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for menu in restaurant.get("menus") or []:
        for cat in menu.get("categories") or []:
            name = cat.get("name")
            for item_id in cat.get("itemIds") or []:
                out.setdefault(item_id, name)
    return out


def _kcal(variation: dict) -> float | None:
    text = (variation.get("NutritionalInfo") or {}).get("EnergyDisplay") or ""
    m = _KCAL_RE.search(text)
    return float(m.group(1)) if m else None


def _extract_size(variation_name: str) -> str | None:
    """"Dark Roast Coffee - Small (Black) UK" -> "Small".

    Hunts for a size word anywhere in the variation name (see the module
    docstring's TRAP section for why position can't be assumed) rather than
    trying to strip the product's own name back out — the product name on
    this platform is sometimes itself incomplete ("Dark Roast" the item,
    "Dark Roast Coffee" in every one of its variation names), so subtracting
    it is less reliable than just finding the size word directly. Returns
    None if no recognisable size word is present at all (e.g. "Espresso
    Shot Single/Double UK" — not a size, a shot count).
    """
    m = _SIZE_RE.search(variation_name)
    return _SIZE_WORDS.get(m.group(1).lower()) if m else None


def fetch_prices(store_id: str | None = None, basis: str = "delivery",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Tim Hortons branch.

    Give a `store_id` (the Just Eat slug), or a `postcode` to use the
    nearest listed branch (see NO LONDON BRANCH in the module docstring —
    most UK postcodes will find none). Every branch found so far is
    delivery-only on this platform.
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"tim_hortons: unknown basis {basis!r}")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"tim_hortons: no Tim Hortons listed on Just "
                               f"Eat for {postcode!r}")
        record = found[0]
        slug = record["uniqueName"]
    else:
        slug = store_id or DEFAULT_STORE_SLUG

    next_data = _menu_page(slug)
    cdn_base = _cdn_base(next_data)
    restaurant = _restaurant_node(next_data)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"tim_hortons: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"tim_hortons: items JSON HTTP {r.status_code} "
                           f"for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"tim_hortons: items JSON for {slug!r} was not "
                           f"JSON ({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"tim_hortons: items JSON for {slug!r} came back "
                           f"empty — the handshake broke, not that the shop "
                           f"is bare")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Tim Hortons ({slug})").strip()
    addr = (record or {}).get("address") or (info.get("location") or {})
    town = addr.get("postalCode") or addr.get("postCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item_id = raw_item.get("Id")
        category = categories.get(item_id)
        raw_name = re.sub(r"\s+", " ",
                          _NEW_PREFIX_RE.sub("", raw_item.get("Name") or "")).strip()
        base_names = [raw_name]
        base_alias = _BASE_NAME_ALIASES.get(raw_name.lower())
        if base_alias:
            base_names.append(base_alias)

        variations = [v for v in raw_item.get("Variations") or []
                     if not v.get("DealOnly")]
        multi_sized = len(variations) > 1

        for variation in variations:
            price = variation.get("BasePrice")
            if price is None:
                continue
            vname = (variation.get("Name") or "").strip()
            size = _extract_size(vname) if (multi_sized and vname) else None
            kcal = _kcal(variation)

            for product_name in base_names:
                if size == "Medium":
                    full_name = product_name               # bare name = Medium
                elif size in ("Small", "Large"):
                    full_name = f"{product_name} ({size})"
                elif vname:
                    # No recognisable size word — the variation name is real
                    # extra info (e.g. "Espresso Shot Single UK"), so keep
                    # it, but strip any leading/trailing repeat of the
                    # product name first so items don't end up double-named
                    # ("Espresso Espresso Shot Single UK").
                    low_v, low_p = vname.lower(), product_name.lower()
                    if low_v.startswith(low_p):
                        extra = vname[len(product_name):].strip(" -")
                    elif low_v.endswith(low_p):
                        extra = vname[:-len(product_name)].strip(" -")
                    else:
                        extra = vname
                    full_name = (f"{product_name} {extra}".strip()
                                if extra else product_name)
                else:
                    full_name = product_name

                names = [full_name]
                if _FRAPPE_RE.search(full_name):
                    names.append(_FRAPPE_RE.sub("Frappé", full_name))

                for row_name in names:
                    key = row_name.lower()
                    if not row_name or key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "name": row_name,
                        "price_gbp": round(float(price), 2),
                        "basis": basis,
                        "store": label,
                        "category": category,
                        "kcal": kcal,
                    })

    if not out:
        raise RuntimeError(
            f"tim_hortons: {len(raw_items)} items for {label} but none "
            f"survived the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:30]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
