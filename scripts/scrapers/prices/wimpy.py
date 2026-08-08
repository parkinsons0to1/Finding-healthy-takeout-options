"""Wimpy UK — REAL per-branch prices from Wimpy's Just Eat storefront.

WHICH BUSINESS
    `wimpy.uk.com` has no ordering of its own — the site's own store-locator
    API (`GET /api/v2/locations?all=true`) lists, per branch, up to three
    `"Platform Order URL"` attributes (Deliveroo / Just Eat / Uber Eats) and
    nothing first-party. Same shape as Subway/Costa/Chipotle: the priced
    per-branch menu is read from Wimpy's Just Eat storefront, never implied
    to be a price Wimpy publishes itself.

DIFFERENCE FROM COSTA/SUBWAY/CHIPOTLE — Wimpy IS collection-eligible
    Every Wimpy branch checked on Just Eat's discovery API reports
    `"isCollection": true"` (Costa/Chipotle are delivery-only there), so
    unlike those three this module labels its rows "collection" — cheaper
    and more comparable to a walk-in price than the delivery figure.

Handshake
---------
Identical shape to `costa.py` / `subway.py` / `chipotle.py`; see those
modules for the full trace of how each URL was found. Every request goes
through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of
both the site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "Wimpy".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN
   base (read live, not pinned), `...cdn.restaurant.itemsUrl` is the
   catalogue filename.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue. Unlike Costa, no
   `DealOnly: true` £0 stubs were found in this catalogue — every variation
   checked carries a real `BasePrice` — but the filter is kept anyway since
   a stub costs nothing to skip and Just Eat's own franchise catalogues are
   not guaranteed uniform chain-to-chain.

NAME DRIFT — `data/db/wimpy.json` (the brand PDF) vs. the till
    A meaningful share of the PDF's names (20 of 118 rows) carry a trailing
    parenthetical caveat that is genuine PDF content, not a scraping
    artefact — "Chicken Wrap (Figures exclude choice of sauce)", "Waffle
    Stack (Figures exclude choice of topping)". These add real words
    ("figures", "exclude", "choice", "sauce"/"topping") that the till's
    plain "Chicken Wrap" doesn't have, so the shared token matcher — which
    requires equal token sets, not a subset — cannot bridge them without an
    alias inventing text the PDF happens to use. Left unmatched rather than
    guessed at; see the chain's docstring notes for the honest count.

STORE — Wimpy Morden, SM4 5BE
    Nearest Wimpy Just Eat lists to Wimbledon (checked from SW19 1RF).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "wimpy"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Wimpy Morden, SM4 5BE — nearest Wimpy Just Eat lists to Wimbledon.
DEFAULT_STORE_SLUG = "wimpy---morden-morden-sm4"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

_KCAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kcal", re.I)


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"wimpy: GET {url} failed (Cloudflare handshake "
                           f"never succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """Wimpy branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"wimpy: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"wimpy: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("wimpy")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"wimpy: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"wimpy: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"wimpy: __NEXT_DATA__ not found for {slug!r} — "
                           f"the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"wimpy: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("wimpy: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "wimpy: preloadedState.menu.restaurant.cdn.restaurant missing — "
            "the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    """itemId -> category name, unioned across every day-part menu."""
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


def _names(name: str) -> list[str]:
    """Booklet-style aliases for one priced item. Additive."""
    base = re.sub(r"\s+", " ", (name or "").strip())
    if not base:
        return []
    names = [base]
    if "'" in base:
        names.append(base.replace("'", ""))  # "Kids'" -> "Kids", one token
    return names


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Wimpy branch.

    Give a `store_id` (the Just Eat slug, e.g. "wimpy---morden-morden-sm4"),
    or a `postcode` to use the nearest listed branch. "collection" and
    "delivery" share one price list on this platform (Just Eat doesn't
    surface a separate figure per service type here) — `basis` only labels
    the row.
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"wimpy: unknown basis {basis!r}")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"wimpy: no Wimpy listed on Just Eat for "
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
        raise RuntimeError(f"wimpy: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"wimpy: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"wimpy: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        # A wrong slug 404s on the menu page already, so an empty 200 here
        # means the CDN payload shape moved, never that the branch sells
        # nothing.
        raise RuntimeError(f"wimpy: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"Wimpy ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item_id = raw_item.get("Id")
        category = categories.get(item_id)
        product_name = (raw_item.get("Name") or "").strip()
        for variation in raw_item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue           # meal-deal-builder component, not a price
            price = variation.get("BasePrice")
            if price is None:
                continue
            full_name = (f"{product_name} {variation['Name'].strip()}"
                        if (variation.get("Name") or "").strip()
                        else product_name)
            kcal = _kcal(variation)
            for row_name in _names(full_name):
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
            f"wimpy: {len(raw_items)} items for {label} but none survived "
            f"the DealOnly filter — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
