"""German Doner Kebab UK — REAL per-store prices from GDK's Just Eat storefront.

WHICH BUSINESS
    `germandonerkebab.com` is the US/global marketing site (its "Order"
    links go to `order.toasttab.com/...` and `onlineorder.3s-pos.com/gdkusa`
    — US franchise ordering platforms, a different business to the UK
    chain this project's nutrition table (`data/db/gdk.json`) covers), and
    `germandonerkebab.co.uk` is a bare JS redirect stub with no priced
    ordering reachable from it. UK franchisees sell delivery/collection
    through the marketplaces instead — Just Eat lists two branches with
    both `isCollection: true` and `isDelivery: true` within a few miles of
    this project's Sutton default. So the per-branch priced menu here is
    read from GDK's own storefront on Just Eat (`www.just-eat.co.uk`) —
    public, no account — and is labelled as a Just Eat price throughout,
    never implied to be a price GDK publishes itself.

Handshake
---------
Identical three-step shape to `subway.py`/`costa.py`/`chipotle.py`; see
`subway.py` for the full trace of how each URL was found. Every request goes
through `scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of
both the site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` starting "German Doner Kebab".
2. ``GET https://www.just-eat.co.uk/restaurants-{uniqueName}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN
   base, `...cdn.restaurant.itemsUrl` the catalogue filename.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

TRAP — every item is listed TWICE, once per channel (`menus[]` carries one
       delivery `menuGroupId` and one collection `menuGroupId`), the same
       shape `subway.py` documents
    Checked exhaustively at Sutton: 88 (name, price) pairs exist on both
    channel copies, and every single one is byte-identical between them.
    This module reads `DealOnly: false` rows once (first occurrence wins),
    labelled "collection" — matching `subway.py`'s convention for a
    channel-identical price, not because delivery is assumed equal but
    because it was measured equal.

TRAP — every priced item ALSO carries `DealOnly: true` addon-choice stubs
       immediately after it, the same shape `chipotle.py`/`starbucks.py`
       document, but they are NOT read here — see the granularity gap below
    A kebab like "OG Kebab" (£9.19, `DealOnly: false`) is followed by a run
    of `DealOnly: true` choices — "Chicken" (+£0.00), "Beef" (+£0.00), "Mix"
    (+£0.00), "Large Chicken"/"Large Beef"/"Large Mix" (all +£2.00), "Meal"
    (+£3.99), "On Its Own" (+£0.00). The zero-cost meat choices confirm
    Beef/Chicken/Mixed Meat never change the price of a given kebab/wrap/box
    on this platform — but this module does not decompose that into
    per-meat rows (see GRANULARITY GAP below); it exists here as
    documentation of what the £0 stubs mean, verified rather than assumed.

GRANULARITY GAP — `data/db/gdk.json` is far more granular than Just Eat's
                   product names, and this module does not guess the join
    The nutrition table splits every dish by meat (Beef/Chicken/Mixed Meat)
    AND, for kebabs, by sauce ("... with sauce" / "... without sauce" /
    "... Tikka") — e.g. "OG Kebab Beef with sauce", "OG Kebab Beef without
    sauce", "OG Kebab Chicken with sauce", six rows for one JE product ("OG
    Kebab", £9.19). The zero-cost addons above prove the *meat* dimension
    doesn't change the price, but nothing on this platform prices sauce
    choice separately either way to confirm which nutrition row a plain
    "OG Kebab" should join to — inventing "with sauce" would be a guess this
    project's house style (see `costa.py`'s milk limitation) avoids. So this
    module emits each Just Eat product under its own real name and price,
    undecomposed; it will not join to the meat/sauce-split nutrition rows
    until a food-item-level alias table is verified dish by dish.

PRICE BASIS — collection, from GDK's Just Eat storefront
    Every row is labelled "collection" (verified channel-identical to
    delivery, see the trap above) — real per-branch prices, but Just Eat's
    listing, not necessarily GDK's own till price; no channel for that
    comparison exists online.

PER STORE
    German Doner Kebab - Sutton, SM1 1EZ is the default, matching every
    other adapter's south-London default.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "gdk"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: German Doner Kebab - Sutton, SM1 1EZ.
DEFAULT_STORE_SLUG = "german-doner-kebab---sutton-sutton"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"gdk: GET {url} failed (Cloudflare handshake never "
                           f"succeeded through any browser profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """GDK branches Just Eat lists for a UK postcode, nearest first."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"gdk: postcode {postcode!r} rejected by the "
                           f"discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"gdk: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    return [x for x in restaurants
            if str(x.get("name") or "").strip().lower().startswith("german doner kebab")]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"gdk: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"gdk: menu page HTTP {r.status_code} for {slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"gdk: __NEXT_DATA__ not found for {slug!r} — the "
                           f"page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gdk: __NEXT_DATA__ was not valid JSON ({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("gdk: no UK menu-CDN base in __NEXT_DATA__ — "
                           "clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "gdk: preloadedState.menu.restaurant.cdn.restaurant missing — "
            "the Next.js state shape has moved") from None


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one GDK branch (dedup'd across channels)."""
    if basis != "collection":
        raise ValueError(f"gdk: unknown basis {basis!r} (only 'collection' — "
                         f"verified channel-identical to delivery)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"gdk: no German Doner Kebab listed on Just Eat "
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
        raise RuntimeError(f"gdk: no itemsUrl for {slug!r}")

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"gdk: items JSON HTTP {r.status_code} for {slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"gdk: items JSON for {slug!r} was not JSON ({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"gdk: items JSON for {slug!r} came back empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name") or f"GDK ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    seen: dict[str, float] = {}
    for it in raw_items:
        variations = it.get("Variations") or []
        if not variations:
            continue
        v = variations[0]
        if v.get("DealOnly") is not False:
            continue
        item_name = (it.get("Name") or "").strip()
        price = v.get("BasePrice")
        if not item_name or price is None:
            continue
        seen.setdefault(item_name, float(price))  # first occurrence wins (dedup channels)

    if not seen:
        raise RuntimeError(f"gdk: {len(raw_items)} items for {label} but no "
                           f"DealOnly:false rows were found — the convention "
                           f"has changed")

    out = [{"name": n, "price_gbp": round(p, 2), "basis": "collection",
            "store": label, "category": None}
           for n, p in seen.items()]
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
