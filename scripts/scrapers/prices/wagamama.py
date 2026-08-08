"""Wagamama UK — REAL per-restaurant prices from Wagamama's own click & collect site.

WHICH BUSINESS
    `takeout.wagamama.com` is Wagamama's own first-party ordering site (an
    ASP.NET MVC storefront on the "Nxg" platform — filenames throughout are
    `StoreSelectionNxg`, `TimeSlotSelectionNxg`), separate from the Deliveroo
    (`deliveroo.co.uk/brands/wagamama`) and Uber Eats
    (`ubereats.com/gb/brand/wagamama-gb`) links on the marketing site
    `www.wagamama.com`. This module reads Wagamama's own click & collect
    prices, never a marketplace's.

Handshake
---------
Plain `requests` — no TLS impersonation needed, no Cloudflare wall. But it IS
a stateful, cookie-based session flow (not a stateless REST/GraphQL API): the
site stores your chosen store and time slot server-side against a session
cookie, then renders the priced menu as normal server-rendered HTML once
both are set. Four requests, one `requests.Session`, no login:

1. ``GET /findpostcode`` — primes the session cookie.
2. ``POST /StoreSelectionNxg/FindStorelst`` with ``lat``/``lon`` (plain
   floats, WGS84) — populates the session's nearby-store list. Returns the
   bare text ``true``; the actual list is read back via step 3's HTML, not
   this response.
3. ``GET /StoreSelection`` — renders every nearby branch as a
   ``data-storenumber`` card; ``<a href="/TimeSlotSelection?storeId=…">``
   inside each card carries the real internal store ID (NOT the same
   number-space as `data-storenumber`, see the trap below).
4. ``GET /TimeSlotSelection?storeId=…&orderType=ClickAndCollect`` — a form
   carrying a CSRF `__RequestVerificationToken` and a `<select
   id="daywiseslot" name="SelectedSlotInternalId">` of bookable slot IDs,
   already populated with today's slots server-side (no need to call the
   `/TimeSlotSelectionNxg/StoreDayWiseSlot` AJAX endpoint the JS uses to
   refresh this list when the customer picks a different day — the page's
   own initial slot list is enough to unlock the menu for today).
5. ``POST /TimeSlotSelectionNxg/SelectTimeSlot`` with `StoreId`, `OrderType`,
   `IsAsap=False`, `__RequestVerificationToken`, and `SelectedSlotInternalId`
   (the first `<option>`'s value, marked "(earliest)") — redirects to
   ``/menu``, now rendering every product, real price and calorie count for
   that store/slot combination server-side (no separate JSON call needed).

TRAP — the `storeId` used everywhere after step 3 is NOT `data-storenumber`
    The `StoreSelection` page's card carries both a small display counter
    (`data-storenumber="1"`, `"2"`, … — just the on-page ranking) and the
    real internal ID inside its Click & Collect link
    (`/TimeSlotSelection?storeId=158&orderType=ClickAndCollect`). Only the
    link's `storeId` is valid on every subsequent request; the display
    counter is cosmetic.

TRAP — prices are NOT in the page until the time-slot step completes
    `GET /menu` before selecting a store/slot renders every product with a
    `price-loading` placeholder and no `£` anywhere in the HTML — client-side
    JS normally fills it in from the session's chosen store. The full flow
    above (steps 1-5) is what makes the *server* render real prices, so no
    extra AJAX call is needed once `SelectTimeSlot` has redirected to `/menu`.

PRICE BASIS — collection (click & collect)
    This site's entire flow is click & collect only (`OrderType=
    ClickAndCollect` throughout); there is no delivery basis to select here.

NAME DRIFT — the nutrition table (`data/db/wagamama.json`, Wagamama's own
    allergen/nutrition matrix from Tenkites) is a GRANULARITY GAP case, the
    same shape `gdk.py` documents at length, not a spelling mismatch this
    module can alias away
    The nutrition matrix decomposes every composable dish into its
    ingredients and swaps — standalone rows for a bare protein ("chicken",
    "duck", "tofu firecracker"), a bare sauce ("amai sauce", "raisukaree
    sauce"), a noodle swap ("on udon noodles", "on rice noodles"), and one
    row per allergy substitution ("mod chicken teriyaki soba (egg allergy -
    on udon noodles"), none of which the till sells as a separately priced
    line — they are choices made *within* one till product's page, not
    products of their own. Roughly a quarter of the matrix's ~171 rows are
    "mod …" allergy-substitution notes alone, which categorically cannot
    carry a till price. This module does not invent a price for a component
    by guessing which whole dish it came from — it emits only what the till
    actually prices as a standalone line, same discipline as
    `gdk.py`/`slim_chickens.py`'s granularity-gap sections. The one alias
    applied is mechanical and verified, not a guess: the till prefixes
    seasonal items with `"new! "` (`"new! buldak bibimbap"`), which the
    nutrition matrix does not, so each such row is also emitted under its
    bare name.

PER STORE
    Wagamama Epsom (nearest to this project's south-London default
    coordinates) is the default, matching every other adapter's convention.
"""
from __future__ import annotations

import html
import re

from ..base import session

CHAIN = "wagamama"

BASE = "https://takeout.wagamama.com"
FIND_POSTCODE = f"{BASE}/findpostcode"
FIND_STORE_LIST = f"{BASE}/StoreSelectionNxg/FindStorelst"
STORE_SELECTION = f"{BASE}/StoreSelection"
TIME_SLOT_SELECTION = f"{BASE}/TimeSlotSelection"
SELECT_TIME_SLOT = f"{BASE}/TimeSlotSelectionNxg/SelectTimeSlot"

#: Sutton, SM1 1EZ coordinates — resolves to Wagamama Epsom (storeId 158),
#: matching every other adapter's south-London default.
DEFAULT_LAT = 51.3618
DEFAULT_LON = -0.1945
DEFAULT_STORE_ID = "158"

_TOKEN_RE = re.compile(
    r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_EARLIEST_SLOT_RE = re.compile(
    r'<option value="([^"]+)">[^<]*\(earliest\)')
_STORE_CARD_RE = re.compile(
    r'data-tracking-restaurantname="([^"]*)".*?'
    r'<span class="showFilePanel"[^>]*data-storenumber="\d+">([^<]*)</span>.*?'
    r'href="/TimeSlotSelection\?storeId=(\d+)&amp;orderType=ClickAndCollect"',
    re.S)
_ITEM_ANCHOR_RE = re.compile(
    r'data-tracking-item data-productid="(\d+)"[^>]*'
    r'data-tracking-itemname="([^"]*)" data-tracking-itemprice="([^"]*)" '
    r'data-tracking-itemid="\d+" data-tracking-itemcategory="([^"]*)">')
_DESCRIPTION_RE = re.compile(r'<div class="description">([^<]*)</div>')
_KCAL_RE = re.compile(r'\((\d+)\s*kCal\)')


def _new_session():
    s = session()
    r = s.get(FIND_POSTCODE, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"wagamama: GET /findpostcode HTTP {r.status_code} "
                           f"— could not open a session")
    return s


def find_stores(lat: float, lon: float) -> list[dict]:
    """Nearby Wagamama branches, as Click & Collect cards on /StoreSelection.

    Returns dicts with `name`, `address`, and `store_id` (the internal ID
    needed by `fetch_prices`, NOT the cosmetic `data-storenumber` — see the
    module docstring's trap).
    """
    s = _new_session()
    r = s.post(FIND_STORE_LIST, data={"lat": lat, "lon": lon}, timeout=60)
    if r.status_code != 200 or r.text.strip().lower() != "true":
        raise RuntimeError(f"wagamama: FindStorelst found no stores near "
                           f"{lat},{lon} (HTTP {r.status_code}, body "
                           f"{r.text[:100]!r})")
    r2 = s.get(STORE_SELECTION, timeout=60)
    if r2.status_code != 200:
        raise RuntimeError(f"wagamama: GET /StoreSelection HTTP {r2.status_code}")
    stores = [{"name": html.unescape(name).strip(),
              "address": html.unescape(addr).strip(),
              "store_id": store_id}
             for name, addr, store_id in _STORE_CARD_RE.findall(r2.text)]
    if not stores:
        raise RuntimeError(f"wagamama: /StoreSelection returned no store "
                           f"cards for {lat},{lon} — the page template "
                           f"has moved")
    return stores


def _select_store_and_slot(s, store_id: str) -> str:
    """Complete the time-slot handshake for `store_id`; returns the priced
    /menu HTML."""
    r = s.get(TIME_SLOT_SELECTION,
              params={"storeId": store_id, "orderType": "ClickAndCollect"},
              timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"wagamama: GET /TimeSlotSelection HTTP "
                           f"{r.status_code} for store {store_id!r}")
    token_m = _TOKEN_RE.search(r.text)
    slot_m = _EARLIEST_SLOT_RE.search(r.text)
    if not token_m or not slot_m:
        raise RuntimeError(f"wagamama: no CSRF token or bookable slot found "
                           f"for store {store_id!r} — the store may be "
                           f"closed/unbookable today, or the page template "
                           f"has moved")
    r2 = s.post(SELECT_TIME_SLOT, data={
        "StoreId": store_id, "OrderType": "ClickAndCollect", "IsAsap": "False",
        "__RequestVerificationToken": token_m.group(1),
        "SelectedSlotInternalId": slot_m.group(1),
    }, timeout=60)
    if r2.status_code != 200 or not r2.url.endswith("/menu"):
        raise RuntimeError(f"wagamama: SelectTimeSlot did not reach /menu "
                           f"for store {store_id!r} (HTTP {r2.status_code}, "
                           f"landed on {r2.url!r})")
    return r2.text


def _kcal_from(chunk: str) -> float | None:
    desc_m = _DESCRIPTION_RE.search(chunk)
    if not desc_m:
        return None
    kcal_m = _KCAL_RE.search(desc_m.group(1))
    return float(kcal_m.group(1)) if kcal_m else None


def fetch_prices(store_id: str | None = None,
                 lat: float | None = None, lon: float | None = None) -> list[dict]:
    """Priced click & collect menu for one Wagamama restaurant.

    Give a `store_id` (the internal ID from `find_stores`, e.g. "158"), or a
    `lat`/`lon` to use the nearest branch. Every row is "collection" — see
    the module docstring, this site has no delivery basis.
    """
    label = None
    if store_id is None:
        found = find_stores(lat if lat is not None else DEFAULT_LAT,
                            lon if lon is not None else DEFAULT_LON)
        store_id = found[0]["store_id"]
        label = f"Wagamama {found[0]['name']}"
    store_id = str(store_id)

    s = _new_session()
    menu_html = _select_store_and_slot(s, store_id)

    matches = list(_ITEM_ANCHOR_RE.finditer(menu_html))
    if not matches:
        raise RuntimeError(f"wagamama: /menu for store {store_id!r} had no "
                           f"priced product anchors — the page template has "
                           f"moved, not that the store is empty")

    label = label or f"Wagamama (store {store_id})"
    out: list[dict] = []
    seen: set[str] = set()

    def emit(name: str, price: float, category: str, kcal: float | None):
        key = name.strip().lower()
        if not name.strip() or key in seen:
            return
        seen.add(key)
        out.append({"name": name.strip(), "price_gbp": round(price, 2),
                    "basis": "collection", "store": label,
                    "category": category, "kcal": kcal})

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else start + 2000
        chunk = menu_html[start:end]
        name = html.unescape(m.group(2)).strip()
        try:
            price = float(m.group(3))
        except ValueError:
            continue
        if not name:
            continue
        category = html.unescape(m.group(4)).strip()
        kcal = _kcal_from(chunk)
        emit(name, price, category, kcal)
        # "new! " is the till's own seasonal-item prefix (see NAME DRIFT) —
        # also emit the bare name the nutrition matrix uses.
        if name.lower().startswith("new! "):
            emit(name[5:].strip(), price, category, kcal)

    if not out:
        raise RuntimeError(f"wagamama: {len(matches)} product anchors for "
                           f"store {store_id!r} but none had a usable name/"
                           f"price — the catalogue shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
