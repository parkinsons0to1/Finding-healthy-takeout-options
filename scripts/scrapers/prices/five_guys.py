"""Five Guys UK — REAL per-branch prices from Five Guys' OWN ordering site.

WHICH BUSINESS
    `www.fiveguys.co.uk`'s "Order" button goes to `order.fiveguys.co.uk` —
    Five Guys' own storefront (nopCommerce-based, server-rendered), not a
    marketplace. It is browsable to a fully priced menu with no account and
    no payment step reached; this module stops the moment prices are read.

Handshake
---------
A stateful, cookie-based multi-step flow (nopCommerce session cart) — a
`requests.Session` carries cookies across four plain GET/POST calls, no
Cloudflare/TLS obstacle, no auth. Every step was found by reading
`/findpostcode`'s inline JS for the AJAX calls it makes, not guessed.

1. ``GET /findpostcode`` — issues the session cookie.
2. ``POST /StoreSelectionNxg/FindStorelst`` with `lat`/`lon` — finds branches
   near a point and stores the result set in the session; returns `"true"`.
3. ``GET /StoreSelection`` — the branch list for that session, nearest
   first, each with `storeId` (an `href="/TimeSlotSelection?storeId=..."`)
   and `data-tracking-restaurantname`/full address.
4. ``GET /TimeSlotSelection?storeId={id}&orderType=ClickAndCollect`` — a
   `<select name="SelectedSlotInternalId">` of bookable slots; the first
   `<option>` is always the earliest available (its value already encodes
   the store, date and time, e.g. `"191-202608071755-1800-1"` — read live,
   never parsed apart or reconstructed).
5. ``POST /TimeSlotSelectionNxg/SelectTimeSlot`` with `StoreId`,
   `OrderType="ClickAndCollect"`, `IsAsap="False"`, and that
   `SelectedSlotInternalId` — commits the slot to the session and returns
   the priced `/menu` page HTML directly.

TRAP — no `£` and no JSON menu payload anywhere on the page; prices are
       ONLY in the product links' tracking attributes
    The rendered menu cards show calories and descriptions but never a
    price (it's filled in client-side from a separate tracking payload the
    JS never actually needs to display, since price also isn't shown until
    the item is opened). Every product link instead carries
    `data-tracking-itemname`, `data-tracking-itemprice` (a decimal string,
    e.g. `"12.2500"`), `data-tracking-itemid` and `data-tracking-itemcategory`
    as a flat attribute run — this module reads those four attributes with
    one regex rather than trying to parse a price out of visible markup that
    doesn't carry one.

PRICE BASIS — collection (`ClickAndCollect`) only
    Delivery uses a different `orderType` on this same platform but was not
    checked; only collection is read and reported here.

NAME DRIFT — none needed for the dishes that matched
    Burgers/dogs/sandwiches ("Cheeseburger", "Bacon Burger", "Hot Dog", "BLT",
    "Grilled Cheese", "Veggie Sandwich", …) already match
    `data/db/five_guys.json` verbatim. Fries and shakes do not: the order
    site distinguishes "REGULAR SALTED FRIES"/"REGULAR CAJUN FRIES" while
    the nutrition book has one plain "Reg Fries" row per size (seasoning is
    a free choice, not priced separately here at any size checked — Little/
    Regular/Large Salted and Cajun are pairwise identical) — no alias is
    guessed for these; they are emitted under the order site's own name.

PER STORE
    Five Guys - Croydon Leisure, CR0 4YA (`store_id="191"`) is the default —
    the nearest branch Five Guys' own locator returns for this project's
    Sutton point (there is no Five Guys in Sutton itself).
"""
from __future__ import annotations

import re

import requests

CHAIN = "five_guys"

_POSTCODE_RE = re.compile(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")

BASE = "https://order.fiveguys.co.uk"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

#: Sutton, SM1 1EZ approx (this project's default point) — used to find the
#: nearest branch when no explicit store_id/lat/lon is given.
DEFAULT_LAT, DEFAULT_LON = 51.3618, -0.1945

#: Five Guys - Croydon Leisure, CR0 4YA — nearest branch to Sutton on this
#: platform's own locator (checked; no closer one exists).
DEFAULT_STORE_ID = "191"
DEFAULT_LABEL_HINT = "Croydon Leisure"

_ITEM_RE = re.compile(
    r'data-tracking-itemname="([^"]+)" data-tracking-itemprice="([^"]+)" '
    r'data-tracking-itemid="([^"]+)" data-tracking-itemcategory="([^"]+)"')
_SLOT_SELECT_RE = re.compile(
    r'name="SelectedSlotInternalId"[^>]*>(.*?)</select>', re.S)
_SLOT_OPTION_RE = re.compile(r'value="([^"]+)"')
_STORE_CARD_RE = re.compile(
    r'data-tracking-restaurantname="([^"]+)"><div class="card_header">'
    r'<h3>[^<]*</h3>.*?<span class="showFilePanel"[^>]*>([^<]+)</span>', re.S)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def find_stores(lat: float, lon: float) -> list[tuple[str, str]]:
    """Nearest Five Guys branches to a point, as (name, full_address) pairs,
    in the order the site lists them (nearest first)."""
    s = _session()
    s.get(f"{BASE}/findpostcode", timeout=30)
    r = s.post(f"{BASE}/StoreSelectionNxg/FindStorelst",
              data={"lat": lat, "lon": lon}, timeout=30)
    if r.status_code != 200 or r.text.strip().lower() != "true":
        raise RuntimeError(f"five_guys: no branches found near ({lat}, {lon})")
    r2 = s.get(f"{BASE}/StoreSelection", timeout=30)
    return _STORE_CARD_RE.findall(r2.text)


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 lat: float | None = None, lon: float | None = None) -> list[dict]:
    """Priced Five Guys menu for one branch, via the ClickAndCollect flow."""
    if basis != "collection":
        raise ValueError(f"five_guys: unknown basis {basis!r} (only "
                         f"'collection' has been checked)")

    s = _session()
    r = s.get(f"{BASE}/findpostcode", timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"five_guys: /findpostcode HTTP {r.status_code}")

    label_hint = None
    if store_id is None:
        use_lat = lat if lat is not None else DEFAULT_LAT
        use_lon = lon if lon is not None else DEFAULT_LON
        r2 = s.post(f"{BASE}/StoreSelectionNxg/FindStorelst",
                    data={"lat": use_lat, "lon": use_lon}, timeout=30)
        if r2.status_code != 200 or r2.text.strip().lower() != "true":
            raise RuntimeError(f"five_guys: no branches found near "
                               f"({use_lat}, {use_lon})")
        r3 = s.get(f"{BASE}/StoreSelection", timeout=30)
        m = re.search(r'storeId=(\d+)&amp;orderType=ClickAndCollect', r3.text)
        if not m:
            raise RuntimeError("five_guys: StoreSelection page had no store "
                               "links — the page shape has moved")
        store_id = m.group(1)
        cards = _STORE_CARD_RE.findall(r3.text)
        if cards:
            name, addr = cards[0]
            pc = _POSTCODE_RE.search(addr.strip().upper())
            label_hint = f"{name.strip()} ({pc.group(0)})" if pc else name.strip()
        else:
            label_hint = None
    else:
        label_hint = f"{DEFAULT_LABEL_HINT} (CR0 4YA)" if store_id == DEFAULT_STORE_ID else None

    r4 = s.get(f"{BASE}/TimeSlotSelection",
              params={"storeId": store_id, "orderType": "ClickAndCollect"}, timeout=30)
    if r4.status_code != 200:
        raise RuntimeError(f"five_guys: TimeSlotSelection HTTP {r4.status_code} "
                           f"for store {store_id!r}")
    m = _SLOT_SELECT_RE.search(r4.text)
    if not m:
        raise RuntimeError(f"five_guys: no timeslot picker for store {store_id!r} "
                           f"— branch may be closed or the page shape moved")
    slots = _SLOT_OPTION_RE.findall(m.group(1))
    if not slots:
        raise RuntimeError(f"five_guys: no bookable timeslots for store "
                           f"{store_id!r} right now")

    r5 = s.post(f"{BASE}/TimeSlotSelectionNxg/SelectTimeSlot",
               data={"StoreId": store_id, "OrderType": "ClickAndCollect",
                     "IsAsap": "False", "SelectedSlotInternalId": slots[0]},
               timeout=30)
    if r5.status_code != 200:
        raise RuntimeError(f"five_guys: SelectTimeSlot HTTP {r5.status_code} "
                           f"for store {store_id!r}")

    items = _ITEM_RE.findall(r5.text)
    if not items:
        raise RuntimeError(f"five_guys: menu for store {store_id!r} came back "
                           f"with zero priced items — the tracking-attribute "
                           f"shape has moved")

    label = f"Five Guys - {label_hint}" if label_hint else f"Five Guys (store {store_id})"

    out: list[dict] = []
    for name, price, _item_id, category in items:
        try:
            price_gbp = round(float(price), 2)
        except ValueError:
            continue
        out.append({
            "name": name.strip(),
            "price_gbp": price_gbp,
            "basis": "collection",
            "store": label,
            "category": category.strip(),
        })
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
