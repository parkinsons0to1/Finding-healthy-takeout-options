"""Greggs — REAL per-shop Click + Collect prices, from Greggs' own ordering API.

Greggs serves its priced menu to anonymous callers: no token, no session, no
basket. One GET per shop returns every article with `eatOutPrice`, `eatInPrice`,
the full `nutritionalValues` block (calories, protein, salt…) and the day parts
it is sold in.

Handshake
---------
1. **Shops**::

       GET https://production-digital.greggs.co.uk/api/v1.0/shops
           ?latitude=..&longitude=..&distanceInMeters=..
       -> [{"shopCode": "6350", "shopName": "Sutton, 74 High St",
            "priceListId": "10", "address": {...}, "channels": [...]}, ...]

2. **The priced menu**::

       GET https://production-digital.greggs.co.uk/api/v1.0/menus/{shopCode}
       -> [{"articleCode", "articleName", "eatOutPrice", "eatInPrice",
            "isCustomisation", "isMealDeal", "articleCategoryId",
            "dayParts": ["Breakfast", "Lunch", "Evening"],
            "nutritionalValues": [{"name": "Calories", "value": 377, ...}]}, ...]

3. **Category names** are not in the menu payload — the article carries only an
   `articleCategoryId` (1..6). The site resolves it from a Storyblok datasource
   whose read token ships in the page's Nuxt runtime config
   (`STORYBLOK_TOKEN`)::

       GET https://api.storyblok.com/v2/cdn/datasource_entries/
           ?datasource=category-ids&version=published&token=...
       -> 1 Breakfast, 2 Savouries & Bakes, 3 Drinks & Snacks,
          4 Sandwiches & Salads, 5 Sweet Treats, 6 Hot Food

   Both the API host and that token are read from the live homepage at run
   time rather than pinned, so a rotation is picked up automatically.

TRAP — `www.greggs.com/api/v1.0/...` is NOT the API
    Every path in the bundle is written `${GREGGS_BASE_URI}/api/v1.0/...`, and
    the obvious guess — hanging it off the www host — returns **404 with the
    SPA's HTML 404 page, 276 kB of it, so it looks like a real response**.
    `GREGGS_BASE_URI` is in the Nuxt payload embedded in every page:
    `GREGGS_BASE_URI:"https://production-digital.greggs.co.uk"`.

TRAP — `filterByDayPart=true` is what the site sends, and it silently halves
       the menu
    The Click + Collect menu page calls
    `/api/v1.0/menus/{shop}?availableAt={slot}&filterByDayPart=true`. Copying
    that faithfully returns 328 articles at 06:47 instead of 376 — every
    lunch- and evening-only line is missing, with HTTP 200 and no hint that
    anything was dropped. This module omits both parameters and gets the whole
    price list regardless of the hour it runs.

TRAP — `priceListId` looks like the key to a price-list endpoint; it isn't
    The shop record advertises a `priceListId` and it is genuinely meaningful
    (three London shops sharing priceListId "19" return byte-identical prices;
    Sutton on list "10" is £1.35 for a Sausage Roll against their £1.60), but
    there is no `/pricelists/{id}` route anywhere in the bundle. The menu is
    keyed on **shopCode**, so the id is only useful for reasoning about which
    shops will agree. A bad shopCode gives an honest 404 ("An item with a
    'ShopCode' of '9999' was not found"), not an empty list.

TRAP — zero-priced rows are modifiers, not free food
    `isCustomisation` articles ("(2 Slices) BBQ Crispy Chicken Pizza", extra
    shots) carry `eatOutPrice: 0` because they are priced inside their parent.
    Every non-customisation article has a real price, so dropping
    customisations is exactly equivalent to dropping the zeroes — and if that
    ever stops being true, a zero would be a bug worth seeing, not a bargain.

TRAP — meal deals repeat once per day part
    "Bake & Drink Deal" appears three times (Breakfast / Lunch / Evening) at
    the same £3.75. Rows are de-duplicated on name+price.

PRICE BASIS
    `eatOutPrice` is the takeaway price and is what the Click + Collect basket
    sums (`eatOutPrice + modificationParts…` in the basket store), so rows are
    labelled ``collection``. `eatInPrice` is captured too: at every shop
    checked in 2026-08 the two are identical, but the field exists per shop, so
    passing ``basis="eat_in"`` reads it rather than assuming parity. Greggs
    delivery goes through Just Eat / Uber Eats and is not in this API — there
    is no delivery basis to report here.
"""
from __future__ import annotations

import json
import math
import re

from ..base import fetch_protected

CHAIN = "greggs"

HOME = "https://www.greggs.com/"
FALLBACK_BASE = "https://production-digital.greggs.co.uk"
STORYBLOK_DATASOURCE = ("https://api.storyblok.com/v2/cdn/datasource_entries/"
                        "?datasource=category-ids&version=published&token={token}")

#: Sutton, 74 High St (SM1 1EZ), priceListId 10 — the shop this was verified
#: against, chosen to match the Nando's/Popeyes adapters' branch.
DEFAULT_SHOP_CODE = "6350"

_runtime_config: dict[str, str] | None = None


def _get(url: str, referer: str = HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"greggs: GET {url} failed (no response)")
    return r


def runtime_config() -> dict[str, str]:
    """`GREGGS_BASE_URI` / `STORYBLOK_TOKEN` out of the live Nuxt payload.

    Read once per process. Falls back to the known base URI if the homepage
    layout changes, so a cosmetic edit to the shell cannot break pricing.
    """
    global _runtime_config
    if _runtime_config is not None:
        return _runtime_config
    cfg: dict[str, str] = {}
    try:
        html = _get(HOME).text
        for key in ("GREGGS_BASE_URI", "STORYBLOK_TOKEN", "STORYBLOK_VERSION"):
            m = re.search(key + r':"([^"]+)"', html)
            if m:
                cfg[key] = m.group(1)
    except RuntimeError:
        pass
    cfg.setdefault("GREGGS_BASE_URI", FALLBACK_BASE)
    _runtime_config = cfg
    return cfg


def _base() -> str:
    return runtime_config()["GREGGS_BASE_URI"].rstrip("/")


def shops(lat: float, lng: float, radius_m: int = 8000) -> list[dict]:
    """Shops near a point. `distanceInMeters` is METRES, not miles."""
    url = (f"{_base()}/api/v1.0/shops?latitude={lat}&longitude={lng}"
           f"&distanceInMeters={radius_m}")
    r = _get(url)
    if r.status_code != 200:
        raise RuntimeError(f"greggs: shop search failed ({r.status_code})")
    return r.json()


def nearest_shop(lat: float, lng: float, radius_m: int = 8000) -> dict | None:
    """The closest shop to a point, by great-circle distance."""
    best, best_km = None, None
    for s in shops(lat, lng, radius_m):
        addr = s.get("address") or {}
        slat, slng = addr.get("latitude"), addr.get("longitude")
        if slat is None or slng is None:
            continue
        dlat, dlng = math.radians(slat - lat), math.radians(slng - lng)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(slat))
             * math.sin(dlng / 2) ** 2)
        km = 6371.0 * 2 * math.asin(math.sqrt(a))
        if best_km is None or km < best_km:
            best, best_km = s, km
    return best


def categories() -> dict[str, str]:
    """articleCategoryId -> display name, from the site's Storyblok datasource."""
    token = runtime_config().get("STORYBLOK_TOKEN")
    if not token:
        return {}
    try:
        r = _get(STORYBLOK_DATASOURCE.format(token=token), referer=HOME)
        entries = r.json().get("datasource_entries") or []
    except (RuntimeError, ValueError):
        return {}
    return {str(e.get("value")): e.get("name") for e in entries if e.get("value")}


def shop(shop_code: str) -> dict | None:
    """One shop record by code — used only to label rows with the shop's name."""
    try:
        r = _get(f"{_base()}/api/v1.0/shops/{shop_code}")
        return r.json() if r.status_code == 200 else None
    except (RuntimeError, ValueError):
        return None


def menu(shop_code: str) -> list[dict]:
    """Raw priced menu for one shop — the whole list, all day parts."""
    url = f"{_base()}/api/v1.0/menus/{shop_code}"
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"greggs: shop {shop_code} not found ({r.text[:120]})")
    if r.status_code != 200:
        raise RuntimeError(f"greggs: menu for {shop_code} failed ({r.status_code})")
    try:
        return r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"greggs: menu for {shop_code} was not JSON — "
                           f"check the base URI ({exc})") from None


def _kcal(article: dict):
    for n in article.get("nutritionalValues") or []:
        if (n.get("name") or "").lower().startswith("calor"):
            try:
                return float(n.get("value"))
            except (TypeError, ValueError):
                return None
    return None


_PRICE_FIELD = {"collection": "eatOutPrice", "eat_in": "eatInPrice"}


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 lat: float | None = None, lng: float | None = None) -> list[dict]:
    """Priced Click + Collect menu for one shop.

    Give a `store_id` (Greggs shopCode), or a `lat`/`lng` to use the nearest
    shop. `basis` is "collection" (takeaway, the default) or "eat_in".
    """
    field = _PRICE_FIELD.get(basis)
    if field is None:
        raise ValueError(f"greggs: unknown basis {basis!r} "
                         f"(this API has no delivery prices — Greggs delivery "
                         f"is sold through Just Eat / Uber Eats)")

    record = None
    if lat is not None and lng is not None:
        record = nearest_shop(lat, lng)
        if record is None:
            raise RuntimeError(f"greggs: no shop near {lat},{lng}")
    shop_code = str(record["shopCode"] if record else (store_id or DEFAULT_SHOP_CODE))

    articles = menu(shop_code)
    if not articles:
        # A wrong shopCode 404s loudly, so an empty 200 means the route or the
        # payload shape moved — never that the shop sells nothing.
        raise RuntimeError(f"greggs: menu for shop {shop_code} came back empty; "
                           f"the /api/v1.0/menus route has changed")

    record = record or shop(shop_code)
    label = (f"Greggs {record['shopName']}" if record and record.get("shopName")
             else f"Greggs #{shop_code}")

    cats = categories()
    out: list[dict] = []
    seen: set[tuple[str, float]] = set()
    for a in articles:
        if a.get("isCustomisation"):
            continue                       # priced inside its parent article
        price = a.get(field)
        name = (a.get("articleName") or "").strip()
        if not name or not price:
            continue
        key = (name.lower(), float(price))
        if key in seen:
            continue                       # meal deals repeat once per day part
        seen.add(key)
        row = {
            "name": name,
            "price_gbp": round(float(price), 2),
            "basis": basis,
            "store": label,
            "category": cats.get(str(a.get("articleCategoryId"))),
            "kcal": _kcal(a),
        }
        if a.get("isMealDeal"):
            row["meal_deal"] = True
        out.append(row)

    if not out:
        raise RuntimeError(f"greggs: {len(articles)} articles for {label} but none "
                           f"priced — the {field} field has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:20]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
