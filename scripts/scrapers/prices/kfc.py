"""KFC UK — REAL per-restaurant Click + Collect and Delivery prices.

KFC's ordering backend serves the whole priced menu to anonymous callers: no
token, no session, no basket. Two calls get you there — a national restaurant
list, then a static per-restaurant menu file with real POS prices attached.

Handshake
---------
1. **Runtime config** — `API_KEY` and `menuBaseUrl` ship in the Next.js
   runtime config embedded in every www.kfc.co.uk page (inside the big
   `"KFC_API":"...","API_KEY":"..."` blob). Both are read from the live
   homepage at run time rather than pinned, so a rotation is picked up
   automatically.

2. **Restaurants** (anonymous, only needs the `x-api-key` header)::

       GET https://prod.kfcapi.com/api/v3/restaurants/all?codemarket=UK
       -> [{"name", "storeid": "02105", "refid": "77021005",
            "geolocation": {"latitude", "longitude"}, "status", ...}, ...]

   `refid` (not `storeid`) is the id the priced-menu file is keyed on.

3. **The priced menu** is a static JSON file, one per restaurant per channel::

       GET {menuBaseUrl}{refid}-{channel}.json
       channel = "ClickAndCollect" | "Delivery"
       -> {"refid", "channel", "items": [...], "categories": [...], ...}

   `menuBaseUrl` is `"https://menuoutput.prod.platform.kfcapi.com/"` at the
   time of writing. No auth, no query params — just GET it.

TRAP — `GET /api/v3/restaurants/{refid}/menu?modeType=..&serviceType=..`
       looks like the menu route and answers 200, but it's a dead end
    It's real (used by the site) and returns
    `{"channel":"ClickAndCollect","menuUrl":"https://menu-output-prod.s3.eu-west-1.amazonaws.com/{refid}-{channel}.json",...}`
    — a pointer into a *different*, private S3 bucket. Fetching that exact
    `menuUrl` gets a genuine S3 `AccessDenied` (checked with three TLS
    profiles, path-style and virtual-hosted-style URLs, with and without the
    region suffix — always denied, for every refid). The bucket is not the
    real distribution point; `menuBaseUrl` from `/util/settings?type=website`
    (`https://menuoutput.prod.platform.kfcapi.com/`) is a *different* host
    serving the *same* filename convention, publicly, and is what this module
    uses. Found by reverse-engineering the SPA's redirect-to-menu logic
    (`apiEndpoints.restaurantMenu` is a decoy; the real client-side URL
    builder reads `menuBaseUrl` out of `/util/settings`).

TRAP — most rows in the menu file are not menu items
    Each file lists 400-600 "items", but only ~150-170 of them are real,
    orderable, priced menu entries. The rest are: recipe components with
    `categoryId: null` (e.g. the £1.33 "Regular Signature Fries" that's
    actually a meal's fries slot, versus the real £2.29 standalone side),
    £0.00 customisation ingredients (lettuce, mayo, jalapeños), POS-only
    housekeeping rows ("Staff Card", "Void By Ticket", "Table Service",
    "Special Offer1".."21" with no name), and duplicate listings of the same
    item filed again under a "Recommended" category. This module keeps only
    items with a non-null `categoryId` (real menu-tree membership) and a
    price above zero, then de-duplicates on (name, price) — verified this
    drops zero false positives: no surviving name maps to two different
    prices at the same store.

TRAP — `type: "Meal"` items carry their price in `levels[0].price`, not `price`
    `price` is null on every Meal-type row; the real, full, ready-to-order
    price (burger + fries + drink, already netting off free default
    component choices) is in `levels`. `levels` was `[{levelId:1,...},
    {levelId:2,...}]` with identical prices at every item checked here, but
    this module takes the minimum rather than assuming that always holds.

TRAP — a wrong refid or channel 403s, it does not come back empty
    `{menuBaseUrl}99999999-ClickAndCollect.json` and
    `{menuBaseUrl}77021005-BogusChannel.json` both answer a genuine S3-style
    403 (no such key), never 200 with an empty item list. So on this route an
    empty response is impossible by construction; a non-200 is treated as a
    hard failure rather than "this store/channel has no menu".

PRICE BASIS
    `channel="ClickAndCollect"` -> ``basis="collection"``,
    `channel="Delivery"` -> ``basis="delivery"`` (KFC's own delivery, not the
    Deliveroo/UberEats/JustEat aggregator prices, which live behind those
    platforms and are out of scope here). Sanity-checked against
    `ESTIMATED_PRICES["kfc"]` for Sutton - High Street: Fillet Burger £5.99
    (est. £5.99), Zinger Burger £5.99 (est. £5.99), Tender £1.99 (est.
    £1.99), Fillet Tower Burger £6.99 (est. £6.79) — all within a few percent
    or exact.
"""
from __future__ import annotations

import math
import os
import re

CHAIN = "kfc"

HOME = "https://www.kfc.co.uk/"
API_V1_FALLBACK = "https://prod.kfcapi.com/api/v1"
API_V3_FALLBACK = "https://prod.kfcapi.com/api/v3"
APIKEY_FALLBACK = "siYAzKattmaIHSwMV9OJYtaoP8SRq"
MENU_BASE_FALLBACK = "https://menuoutput.prod.platform.kfcapi.com/"

#: Sutton - High Street (SM1 1NR) — the restaurant this adapter was verified
#: against. This is a `refid`, not the shorter `storeid`.
DEFAULT_REFID = "77021005"

_CHANNEL = {"collection": "ClickAndCollect", "delivery": "Delivery"}

_runtime_config: dict[str, str] | None = None
_restaurants_cache: list[dict] | None = None


def _request(method: str, url: str, headers: dict | None = None, params=None):
    """Plain HTTP with browser TLS impersonation, trying each profile in turn.

    Same rationale as nandos.py: some hosts reset the connection under
    "chrome" here but succeed under "safari", so never pin a single profile.
    """
    from curl_cffi import requests as cffi_requests

    kwargs = {"timeout": 90}
    if headers:
        kwargs["headers"] = headers
    if params:
        kwargs["params"] = params
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(ca):
        kwargs["verify"] = ca
    last = None
    for profile in ("safari", "chrome", "edge"):
        try:
            return cffi_requests.request(method, url, impersonate=profile, **kwargs)
        except Exception as exc:  # noqa: BLE001 - profile-specific transport failure
            last = exc
            continue
    raise RuntimeError(f"kfc: all TLS profiles failed for {url}: {last}")


def runtime_config() -> dict[str, str]:
    """`API_KEY` / `menuBaseUrl` out of the live site, read once per process.

    Falls back to known-good values if the homepage layout changes, so a
    cosmetic edit to the site shell cannot break pricing.
    """
    global _runtime_config
    if _runtime_config is not None:
        return _runtime_config
    cfg = {"apiKey": APIKEY_FALLBACK, "apiV1": API_V1_FALLBACK,
           "apiV3": API_V3_FALLBACK, "menuBaseUrl": MENU_BASE_FALLBACK}
    try:
        r = _request("GET", HOME)
        if r is not None and r.status_code == 200:
            html = r.text
            m = re.search(r'"API_KEY":"([^"]+)"', html)
            if m:
                cfg["apiKey"] = m.group(1)
            m = re.search(r'"KFC_API":"([^"]+)"', html)
            if m:
                cfg["apiV1"] = m.group(1)
            m = re.search(r'"KFC_API_V3":"([^"]+)"', html)
            if m:
                cfg["apiV3"] = m.group(1)
    except RuntimeError:
        pass
    try:
        headers = _headers(cfg)
        r = _request("GET", cfg["apiV1"] + "/util/settings",
                     headers=headers, params={"type": "website"})
        if r is not None and r.status_code == 200:
            base = r.json().get("menuBaseUrl")
            if base:
                cfg["menuBaseUrl"] = base
    except (RuntimeError, ValueError):
        pass
    _runtime_config = cfg
    return cfg


def _headers(cfg: dict[str, str]) -> dict[str, str]:
    return {"x-api-key": cfg["apiKey"], "codemarket": "UK", "countrycode": "GB",
            "langcode": "en", "Origin": "https://www.kfc.co.uk",
            "Referer": HOME, "Accept": "application/json"}


def restaurants() -> list[dict]:
    """Every KFC UK restaurant, with storeid/refid/coordinates. Anonymous."""
    global _restaurants_cache
    if _restaurants_cache is not None:
        return _restaurants_cache
    cfg = runtime_config()
    r = _request("GET", cfg["apiV3"] + "/restaurants/all",
                headers=_headers(cfg), params={"codemarket": "UK"})
    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else "no response"
        raise RuntimeError(f"kfc: restaurant list failed ({code})")
    data = r.json()
    if not data:
        raise RuntimeError("kfc: restaurant list came back empty — "
                           "the /restaurants/all route has changed")
    _restaurants_cache = data
    return data


def nearest_restaurant(lat: float, lng: float,
                       estate: list[dict] | None = None) -> dict | None:
    """The closest available restaurant to a point, by great-circle distance."""
    best, best_km = None, None
    for r in (estate if estate is not None else restaurants()):
        if r.get("status") != "available":
            continue
        geo = r.get("geolocation") or {}
        rlat, rlng = geo.get("latitude"), geo.get("longitude")
        if rlat is None or rlng is None:
            continue
        dlat, dlng = math.radians(rlat - lat), math.radians(rlng - lng)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(rlat))
             * math.sin(dlng / 2) ** 2)
        km = 6371.0 * 2 * math.asin(math.sqrt(a))
        if best_km is None or km < best_km:
            best, best_km = r, km
    return best


def _find_restaurant(refid: str, estate: list[dict]) -> dict | None:
    for r in estate:
        if r.get("refid") == refid:
            return r
    return None


def _menu(refid: str, channel: str) -> dict:
    cfg = runtime_config()
    url = f"{cfg['menuBaseUrl']}{refid}-{channel}.json"
    r = _request("GET", url)
    if r is None:
        raise RuntimeError(f"kfc: GET {url} failed (no response)")
    if r.status_code != 200:
        # A wrong refid or channel 403s (S3-style AccessDenied) rather than
        # coming back empty, so any non-200 here is a hard failure.
        raise RuntimeError(f"kfc: menu file for {refid}/{channel} failed "
                           f"({r.status_code}) — {r.text[:150]}")
    try:
        return r.json()
    except ValueError as exc:
        raise RuntimeError(f"kfc: menu file for {refid}/{channel} was not "
                           f"JSON — check menuBaseUrl ({exc})") from None


def _item_price(item: dict) -> float | None:
    if item.get("type") == "Meal":
        levels = item.get("levels") or []
        prices = [float(lv["price"]) for lv in levels if lv.get("price") is not None]
        return min(prices) if prices else None
    price = item.get("price")
    return float(price) if price not in (None, "") else None


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 lat: float | None = None, lng: float | None = None) -> list[dict]:
    """Priced menu for one restaurant.

    `store_id` is a KFC `refid` (e.g. "77021005"), not the shorter `storeid`.
    Give a `store_id`, or `lat`/`lng` to use the nearest available branch.
    `basis` is "collection" (Click + Collect, default) or "delivery" (KFC's
    own delivery — not the Deliveroo/UberEats/JustEat aggregator prices).
    """
    channel = _CHANNEL.get(basis)
    if channel is None:
        raise ValueError(f"kfc: unknown basis {basis!r} (use 'collection' or "
                         f"'delivery' — aggregator prices aren't covered here)")

    record = None
    if lat is not None and lng is not None:
        record = nearest_restaurant(lat, lng)
        if record is None:
            raise RuntimeError(f"kfc: no restaurant near {lat},{lng}")
    refid = str(record["refid"] if record else (store_id or DEFAULT_REFID))
    if record is None:
        record = _find_restaurant(refid, restaurants())

    data = _menu(refid, channel)
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"kfc: menu file for {refid}/{channel} has no items "
                           f"— the file schema has changed")

    cats = {c.get("categoryId"): c.get("name") for c in (data.get("categories") or [])}
    label = f"KFC {record['name']}" if record and record.get("name") else f"KFC #{refid}"

    out: list[dict] = []
    seen: set[tuple[str, float]] = set()
    for it in items:
        if it.get("categoryId") is None:
            continue  # recipe component / customisation ingredient, not a menu item
        price = _item_price(it)
        name = (it.get("name") or "").strip()
        if not name or price is None or price <= 0:
            continue
        key = (name.lower(), round(price, 2))
        if key in seen:
            continue  # same item re-listed under "Recommended"
        seen.add(key)
        nutrition = it.get("nutrition") or {}
        out.append({
            "name": name,
            "price_gbp": round(price, 2),
            "basis": basis,
            "store": label,
            "category": cats.get(it.get("categoryId")),
            "kcal": nutrition.get("kcal"),
        })

    if not out:
        raise RuntimeError(f"kfc: {len(items)} items for {label}/{channel} but "
                           f"none survived category/price filtering — the "
                           f"categoryId convention has changed")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:20]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
