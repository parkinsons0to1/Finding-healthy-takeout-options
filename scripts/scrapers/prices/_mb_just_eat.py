"""Shared Just Eat handshake for Mitchells & Butlers brands.

WHY THIS EXISTS
    `miller_carter.py` first found that M&B brands — whose own sites are
    reservation/booking-only with zero ordering links — nonetheless have a
    priced, anonymous, collection-eligible storefront on Just Eat. The exact
    same three-step shape (discovery API -> restaurant page's
    `__NEXT_DATA__` -> CDN items JSON) turned out to work unmodified for
    Harvester and Toby Carvery too (see `harvester.py`, `toby_carvery.py`),
    which is the signal that this is a Just Eat integration pattern shared
    across the M&B estate, not a Miller & Carter idiosyncrasy. This module
    factors that handshake out so a fourth or fifth M&B brand is one file
    of brand-specific glue, not a fourth copy of the whole trace.

    Checked and found NOT to carry this pattern: Beefeater and Brewers
    Fayre. Those are Whitbread brands (Premier Inn's parent), not
    Mitchells & Butlers — their own site JS ships under `apis/whitbread/`
    and its shared `window.rwl` config only knows about a "Menus" page and
    a "Book" (table reservation) page, no ordering page at all. Zero
    listings for either on Just Eat, Deliveroo (`/brands/{slug}` 404s), or
    Uber Eats (the one lookalike result — "The Grapes Beefeater" — is an
    independent pub, and its own Uber Eats page states outright: "The
    Grapes Beefeater is unavailable on Uber Eats at this time."). See
    `beefeater.py`/`brewers_fayre.py` — no, those adapters do not exist;
    there is no cracked source for either brand as of this writing, and
    this module doesn't apply to them.

Handshake
---------
Every request goes through `scripts.scrapers.base.fetch_protected`
(Cloudflare in front of both Just Eat and the menu CDN rejects plain
`requests`).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` by the brand's own display-name prefixes.
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__` for `props.appProps.clientConfig.jeRestaurantCdnUrls.uk`
   (the CDN base) and `props.appProps.preloadedState.menu.restaurant.cdn.restaurant`
   (the restaurant node, which carries `itemsUrl` and a per-category
   `itemIds` map).
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue. Each `Items[]` entry
   has one or more `Variations[]`; `DealOnly` variations are skipped (not a
   standalone purchasable price), the rest carry `BasePrice` and an
   embedded `NutritionalInfo.EnergyDisplay` kcal string.

DIETARY-TAG SUFFIX
    Menu names carry "(V)"/"(VE)"/"(GF)" markers and trailing "*" allergen
    asterisks that the nutrition side of this project doesn't always
    reproduce identically, so every row is emitted once under its raw name
    and again with the suffix stripped (`_strip_diet_tags`), matching
    `frankie_bennys.py`'s approach to the same platform shape.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_KCAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kcal", re.I)
_DIET_TAG_RE = re.compile(
    r"[\*]*\s*(\((?:v|ve|vg|vegan|gf|gluten-free)\)\s*)+\**\s*$", re.I)


def _get(url: str, referer: str = JE_HOME, brand: str = "mb"):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"{brand}: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str, name_prefixes: tuple[str, ...],
                brand: str = "mb") -> list[dict]:
    """Just Eat listings for `postcode` whose name starts with one of
    `name_prefixes` (case-insensitive) — e.g. `("harvester",)` or
    `("toby carvery",)`."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url, brand=brand)
    if r.status_code == 404:
        raise RuntimeError(f"{brand}: postcode {postcode!r} rejected by "
                           f"the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"{brand}: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    prefixes = tuple(p.lower() for p in name_prefixes)
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith(prefixes)]


def _menu_page(slug: str, brand: str = "mb") -> dict:
    r = _get(MENU_PAGE.format(slug=slug), brand=brand)
    if r.status_code == 404:
        raise RuntimeError(f"{brand}: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"{brand}: menu page HTTP {r.status_code} for "
                           f"{slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"{brand}: __NEXT_DATA__ not found for {slug!r} "
                           f"— the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{brand}: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict, brand: str = "mb") -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError(f"{brand}: no UK menu-CDN base in __NEXT_DATA__ "
                           f"— clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict, brand: str = "mb") -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            f"{brand}: preloadedState.menu.restaurant.cdn.restaurant "
            f"missing — the Next.js state shape has moved") from None


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


def fetch_je_menu(*, brand: str, default_store_slug: str,
                  name_prefixes: tuple[str, ...],
                  display_name_fallback: str,
                  store_id: str | None = None, basis: str = "collection",
                  postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one branch of an M&B brand.

    `brand` is the short id used in error messages (e.g. "harvester").
    `default_store_slug` is the Just Eat slug used when neither `store_id`
    nor `postcode` is given. `name_prefixes` filters the discovery API
    (case-insensitive `str.startswith`). Returns the same row shape the
    adapter's `fetch_prices` promises: name/price_gbp/basis/store/category/
    kcal.
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"{brand}: unknown basis {basis!r}")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode, name_prefixes, brand=brand)
        if not found:
            raise RuntimeError(f"{brand}: no branch listed on Just Eat for "
                               f"{postcode!r}")
        record = found[0]
        slug = record["uniqueName"]
    else:
        slug = store_id or default_store_slug

    next_data = _menu_page(slug, brand=brand)
    cdn_base = _cdn_base(next_data, brand=brand)
    restaurant = _restaurant_node(next_data, brand=brand)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"{brand}: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}", brand=brand)
    if r.status_code != 200:
        raise RuntimeError(f"{brand}: items JSON HTTP {r.status_code} for "
                           f"{slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{brand}: items JSON for {slug!r} was not "
                           f"JSON ({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"{brand}: items JSON for {slug!r} came back "
                           f"empty — the handshake broke, not that the "
                           f"shop is bare")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"{display_name_fallback} ({slug})").strip()
    addr = (record or {}).get("address") or (info.get("location") or {})
    town = addr.get("postalCode") or addr.get("postCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item_id = raw_item.get("Id")
        category = categories.get(item_id)
        product_name = re.sub(r"\s+", " ", (raw_item.get("Name") or "")).strip()
        for variation in raw_item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue
            price = variation.get("BasePrice")
            if price is None:
                continue
            vname = (variation.get("Name") or "").strip()
            full_name = f"{product_name} {vname}" if vname else product_name
            kcal = _kcal(variation)

            names = [full_name]
            stripped = _DIET_TAG_RE.sub("", full_name).strip()
            if stripped and stripped.lower() != full_name.lower():
                names.append(stripped)

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
            f"{brand}: {len(raw_items)} items for {label} but none "
            f"survived the DealOnly filter — the catalogue shape has moved")
    return out
