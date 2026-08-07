"""Burger King UK — REAL per-store prices from the RBI ordering gateway.

burgerking.co.uk is an RBI (Restaurant Brands International) white-label React
app. Its data is split in two, which is the whole trick:

* **Sanity CMS** (`czqk28jt`, dataset `prod_bk_gb`) holds the *content* — item
  names, descriptions, images. No prices anywhere in it.
* **The RBI gateway** (`https://euc1-prod-bk-gateway.rbictg.com/graphql`) holds
  the *money* — per-store price and availability keyed only by Sanity `_id`.

Neither half is useful alone. Joining them on `_id` is what produces a real
priced menu.

Handshake
---------
No auth at all. No cookie, no bearer, no basket. Three unauthenticated POSTs
plus one GET:

1. Find stores (either gateway or `euc1-prod-bk.rbictg.com` works)::

       query GetRestaurants($input: RestaurantsInput) {
         restaurants(input: $input) { totalCount nodes { storeId name ... } } }
       variables: {"input": {"coordinates": {"userLat": .., "userLng": ..,
                                             "searchRadius": 20000}, "first": 5}}

   `coordinates` is mandatory — omitting it returns COORDINATES_REQUIRED.

2. Priced menu for that store::

       query storeMenu($region:String!, $channel:Channel!, $storeId:ID!,
                       $serviceMode:PosDataServiceMode) {
         storeMenu(region:$region channel:$channel storeId:$storeId
                   serviceMode:$serviceMode) {
           id isAvailable price { default max min overrides { key price } }
           calories { default min max } } }
       variables: {"region":"GB","channel":"whitelabel","storeId":"30309",
                   "serviceMode":"pickup"}

3. Names for the returned `_id`s, from the Sanity CDN::

       GET https://czqk28jt.apicdn.sanity.io/v2023-08-01/data/query/prod_bk_gb
           ?query=*[_id in [...]]{_id,_type,"name":name.en}

Headers `x-ui-region: GB` and `x-ui-platform: web` are sent by the app; the
gateway answers without them but they are kept so the request looks like the
one BK's own client makes.

TRAP — the @gateway / @useCache directives are CLIENT-side
    The queries are stored in the bundle as
    `query storeMenu(...)@gateway@useCache{...}`. Those directives tell Apollo
    which transport to use and are stripped before the wire. Send them and the
    server replies `Unknown directive "@gateway"`. Strip them.

TRAP — enum values are lower-case
    `serviceMode: "PICKUP"` and `channel: "WHITELABEL"` are rejected. The real
    values are `pickup` / `delivery` and `whitelabel`.

TRAP — prices are in PENCE and 0 means "not sold here"
    301 entities come back for Sutton; only 223 have both `isAvailable` and a
    non-zero price under pickup. Zero-priced rows are modifiers or items the
    store does not carry — they are dropped, not reported as free.

PRICE BASIS — pickup by default, and delivery is genuinely different
    Of the 139 items priced under both service modes at Sutton High Street,
    133 differ: Bacon Butty £3.79 pickup vs £4.49 delivery, Breakfast King
    £6.99 vs £7.99 — a ~16% delivery uplift. Ask for it explicitly with
    `service_mode="delivery"`; the returned rows are labelled either way.
"""
from __future__ import annotations

import json
import os
import urllib.parse

CHAIN = "burger_king"

GATEWAY = "https://euc1-prod-bk-gateway.rbictg.com/graphql"
SANITY = ("https://czqk28jt.apicdn.sanity.io/v2023-08-01/data/query/prod_bk_gb"
          "?query=")

HEADERS = {
    "Content-Type": "application/json",
    "x-ui-region": "GB",
    "x-ui-platform": "web",
    "x-ui-language": "en",
    "Origin": "https://www.burgerking.co.uk",
    "Referer": "https://www.burgerking.co.uk/",
}

#: 17 High St, Sutton SM1 1DF — the store used to verify this adapter.
DEFAULT_STORE_ID = "30309"

RESTAURANTS_QUERY = """
query GetRestaurants($input: RestaurantsInput) {
  restaurants(input: $input) {
    totalCount
    nodes { _id storeId number name hasMobileOrdering hasTakeOut hasDelivery
            latitude longitude
            physicalAddress { address1 city postalCode } }
  }
}
"""

STORE_MENU_QUERY = """
query storeMenu($region: String!, $channel: Channel!, $storeId: ID!,
                $serviceMode: PosDataServiceMode) {
  storeMenu(region: $region, channel: $channel, storeId: $storeId,
            serviceMode: $serviceMode) {
    id
    isAvailable
    price { default max min }
    calories { default }
  }
}
"""


def _request(method, url, payload=None, headers=None):
    from curl_cffi import requests as cffi_requests

    kwargs = {"timeout": 90, "headers": headers or HEADERS}
    if payload is not None:
        kwargs["json"] = payload
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
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
    raise RuntimeError(f"burger_king: all TLS profiles failed for {url}: {last}")


def _gql(query: str, variables: dict) -> dict:
    r = _request("POST", GATEWAY, {"query": query, "variables": variables})
    if r.status_code != 200:
        raise RuntimeError(f"burger_king: gateway HTTP {r.status_code} {r.text[:200]}")
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"burger_king: gateway errors {payload['errors']}")
    return payload["data"]


def find_stores(lat: float, lon: float, radius_m: int = 20000,
                limit: int = 10) -> list[dict]:
    data = _gql(RESTAURANTS_QUERY, {"input": {
        "coordinates": {"userLat": lat, "userLng": lon, "searchRadius": radius_m},
        "first": limit,
    }})
    return data["restaurants"]["nodes"]


def _sanity_names(ids: list[str]) -> dict[str, dict]:
    """Resolve Sanity _ids to names, chunked to keep the GROQ URL sane."""
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 120):
        chunk = ids[i:i + 120]
        groq = ("*[_id in " + json.dumps(chunk).replace(" ", "") +
                ']{_id,_type,"name":name.en}')
        r = _request("GET", SANITY + urllib.parse.quote(groq),
                     headers={"Accept": "application/json"})
        if r.status_code != 200:
            raise RuntimeError(f"burger_king: sanity HTTP {r.status_code}")
        for doc in r.json().get("result") or []:
            out[doc["_id"]] = doc
    return out


def fetch_prices(store_id: str | None = None,
                 service_mode: str = "pickup") -> list[dict]:
    """Priced menu for one BK store. `service_mode` is "pickup" or "delivery"."""
    store_id = str(store_id or DEFAULT_STORE_ID)
    if service_mode not in ("pickup", "delivery"):
        raise ValueError("service_mode must be 'pickup' or 'delivery'")

    entities = _gql(STORE_MENU_QUERY, {
        "region": "GB", "channel": "whitelabel",
        "storeId": store_id, "serviceMode": service_mode,
    })["storeMenu"]

    priced = []
    for e in entities:
        price = ((e.get("price") or {}).get("default")) or 0
        if not e.get("isAvailable") or price <= 0:
            continue
        priced.append((e["id"], price, ((e.get("calories") or {}).get("default"))))

    names = _sanity_names([pid for pid, _, _ in priced])

    basis = "collection" if service_mode == "pickup" else "delivery"
    out: list[dict] = []
    for pid, pence, kcal in priced:
        doc = names.get(pid) or {}
        name = (doc.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "price_gbp": round(pence / 100.0, 2),
            "basis": basis,
            "store": f"Burger King #{store_id}",
            "category": doc.get("_type"),
            "kcal": kcal,
        })
    if not out:
        raise RuntimeError(f"burger_king: no priced items for store {store_id}")
    return out


if __name__ == "__main__":  # pragma: no cover
    for row in fetch_prices()[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
