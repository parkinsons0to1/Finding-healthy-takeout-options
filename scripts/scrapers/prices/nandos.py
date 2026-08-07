"""Nando's UK — REAL per-restaurant prices, with COLLECTION and DELIVERY split.

This is the cleanest source of the nine: Nando's own menu service returns both
price bases side by side, tagged, so the delivery uplift is measured rather
than guessed (Chicken Butterfly, Sutton High Street: £10.25 collection vs
£12.00 delivery — 17%).

Handshake
---------
Two tokens, both harvested from public artefacts; no account, no basket.

1. **Restaurant search** (`www.nandos.co.uk/order/api/restaurant/search`) needs
   an anonymous *guest* session::

       POST https://api.nandos.services/guest-api/new
       Content-Type: application/json
       {"visitorId": null, "email": null, "marketingConsent": false}
       -> {"session": "<JWT, ~3h>"}

   Send it as `Authorization: Bearer <session>` to::

       GET /order/api/restaurant/search
           ?fulfilmentType=collection&latitude=..&longitude=..&radius=..&limit=..

   `radius` is in METRES and the route 400s outside 100..100000 — the value is
   not a mile count. Results carry `id` ("14035"), `slug`
   ("sutton-high-street"), address, hours and orderability.

2. **The menu itself** is a separate GraphQL service,
   `https://api.nandos.services/menu-v2/query`, which does NOT accept the guest
   token — it answers `401 Jwt issuer is not configured`, and answers
   `403 RBAC: access denied` with no auth at all. It accepts the app's own
   service token, which Nando's ships in cleartext in the ordering bundle
   (`/order/_next/static/chunks/pages/_app-*.js`) as
   `NEXT_PUBLIC_PLATFORM_API_DEV_TOKEN`. This module re-reads that constant
   from the live bundle at run time rather than pinning a copy, so a rotation
   is picked up automatically. (The embedded JWT's `exp` is in 2121.)

Schema (from introspection, which the endpoint allows)::

    Query.menu(market: Market, restaurant: ID, restaurantSlug: String,
               asOfUtc: DateTimeUtc, activeMealtime: Boolean): Menu
    Menu.sections(displayName: String, features: String): [Section]
    MenuItem.priceList: [PriceListItem]
    PriceListItem { kind, displayName, price: Money, fulfilmentTypes }

PRICE BASIS — both, labelled per row
    Each item's `priceList` holds one entry per (variant, fulfilment channel).
    `fulfilmentTypes` is one of COLLECTION / DELIVERY / EAT_IN / AT_TABLE, and
    the same variant appears twice with different money. This adapter emits
    `basis="collection"` for entries containing COLLECTION and
    `basis="delivery"` for DELIVERY, and by default returns collection only.

TRAP — EAT_IN can be cheaper than COLLECTION and is not the same thing
    Kids' meals price at £6.08 EAT_IN / £6.95 COLLECTION / £7.95 DELIVERY. An
    entry whose `fulfilmentTypes` is EAT_IN/AT_TABLE only is dropped, never
    treated as a collection price.

TRAP — `price.value` is in PENCE (integer), not pounds.

TRAP — one item yields several rows
    `displayName` on the PriceListItem is the variant ("On its own",
    "+2 regular sides", "With Chicken Thighs"). The bare item price is the
    `ON_ITS_OWN` kind; meal upgrades are separate rows. Names are emitted as
    "Item - Variant" with the ON_ITS_OWN variant left bare.
"""
from __future__ import annotations

import re

from ..base import fetch_protected

CHAIN = "nandos"

GUEST_TOKEN_URL = "https://api.nandos.services/guest-api/new"
MENU_GRAPHQL = "https://api.nandos.services/menu-v2/query"
ORDER_BASE = "https://www.nandos.co.uk/order"
BUNDLE_INDEX = "https://www.nandos.co.uk/order/search"

#: Sutton - High Street (SM1 1DF) — the restaurant used to verify this adapter.
DEFAULT_RESTAURANT_ID = "14035"

MENU_QUERY = """
query Menu($restaurant: ID) {
  menu(restaurant: $restaurant) {
    id
    sections {
      displayName
      items {
        displayName
        plu
        nutritionalInfo { factsForPortionSizes { energyKcal } }
        priceList { kind displayName price { value currencyCode } fulfilmentTypes }
      }
    }
  }
}
"""


def _request(method, url, headers=None, payload=None):
    """Plain HTTP with browser TLS impersonation, trying each profile in turn.

    Profile order matters here exactly as in base.fetch_protected: "chrome"
    gets its connection reset through the sandbox proxy on some hosts while
    "safari" succeeds, so never pin a single profile.
    """
    import os
    from curl_cffi import requests as cffi_requests

    kwargs = {"timeout": 90}
    if headers:
        kwargs["headers"] = headers
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
        except Exception as exc:  # noqa: BLE001 - profile-specific transport failure
            last = exc
            continue
    raise RuntimeError(f"nandos: all TLS profiles failed for {url}: {last}")


def _post(url, payload, headers):
    return _request("POST", url, headers=headers, payload=payload)


def guest_token() -> str:
    """Anonymous session JWT — needed for the restaurant search route only."""
    r = _post(GUEST_TOKEN_URL,
              {"visitorId": None, "email": None, "marketingConsent": False},
              {"Content-Type": "application/json",
               "Origin": "https://www.nandos.co.uk"})
    if r is None or r.status_code != 200:
        raise RuntimeError("nandos: guest token request failed")
    return r.json()["session"]


def platform_token() -> str:
    """Read NEXT_PUBLIC_PLATFORM_API_DEV_TOKEN out of the live ordering bundle."""
    page = fetch_protected(BUNDLE_INDEX)
    if page is None:
        raise RuntimeError("nandos: could not load /order/search")
    chunks = re.findall(r'src="(/order/_next/static/chunks/pages/_app-[^"]+\.js)"',
                        page.text)
    if not chunks:
        chunks = re.findall(r'src="(/order/_next/static/[^"]+\.js)"', page.text)
    for path in chunks:
        js = fetch_protected("https://www.nandos.co.uk" + path)
        if js is None:
            continue
        m = re.search(r'NEXT_PUBLIC_PLATFORM_API_DEV_TOKEN:"([^"]+)"', js.text)
        if m:
            return m.group(1)
    raise RuntimeError("nandos: platform token not found in ordering bundle")


def find_restaurants(lat: float, lon: float, radius_m: int = 8000,
                     fulfilment: str = "collection", limit: int = 10) -> list[dict]:
    """Nearby restaurants. `radius_m` is METRES and must be 100..100000."""
    tok = guest_token()
    url = (f"{ORDER_BASE}/api/restaurant/search?fulfilmentType={fulfilment}"
           f"&latitude={lat}&longitude={lon}&radius={radius_m}&limit={limit}")
    r = _request("GET", url, headers={"Accept": "application/json",
                                      "Authorization": "Bearer " + tok,
                                      "Referer": f"{ORDER_BASE}/search"})
    if r.status_code != 200:
        raise RuntimeError(f"nandos: restaurant search failed "
                           f"({r.status_code}) {r.text[:200]}")
    return r.json()["data"]["results"]


def fetch_prices(store_id: str | None = None, basis: str = "collection") -> list[dict]:
    """Priced menu for one restaurant.

    `basis` is "collection" (default), "delivery", or "all" to get both — every
    row is labelled either way.
    """
    store_id = str(store_id or DEFAULT_RESTAURANT_ID)
    token = platform_token()
    r = _post(MENU_GRAPHQL,
              {"query": MENU_QUERY, "variables": {"restaurant": store_id}},
              {"Content-Type": "application/json",
               "Authorization": "Bearer " + token,
               "Origin": "https://www.nandos.co.uk"})
    if r is None or r.status_code != 200:
        raise RuntimeError(f"nandos: menu-v2 query failed "
                           f"({r.status_code if r is not None else 'no response'})")
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"nandos: menu-v2 errors {payload['errors']}")
    menu = (payload.get("data") or {}).get("menu")
    if not menu:
        raise RuntimeError(f"nandos: no menu for restaurant {store_id}")

    out: list[dict] = []
    for section in menu.get("sections") or []:
        for it in section.get("items") or []:
            base_name = (it.get("displayName") or "").strip()
            facts = ((it.get("nutritionalInfo") or {}).get("factsForPortionSizes")
                     or [{}])
            kcal = (facts[0] or {}).get("energyKcal")
            for entry in it.get("priceList") or []:
                types = set(entry.get("fulfilmentTypes") or [])
                if "COLLECTION" in types:
                    row_basis = "collection"
                elif "DELIVERY" in types:
                    row_basis = "delivery"
                else:
                    continue  # EAT_IN / AT_TABLE only — not a takeaway price
                if basis != "all" and row_basis != basis:
                    continue
                pence = ((entry.get("price") or {}).get("value"))
                if pence is None:
                    continue
                variant = (entry.get("displayName") or "").strip()
                name = base_name
                if variant and entry.get("kind") != "ON_ITS_OWN":
                    name = f"{base_name} - {variant}"
                out.append({
                    "name": name,
                    "price_gbp": round(pence / 100.0, 2),
                    "basis": row_basis,
                    "store": f"Nando's #{store_id}",
                    "category": section.get("displayName"),
                    "kcal": kcal,
                })
    if not out:
        raise RuntimeError(f"nandos: no priced items for restaurant {store_id}")
    return out


if __name__ == "__main__":  # pragma: no cover
    for row in fetch_prices()[:20]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
