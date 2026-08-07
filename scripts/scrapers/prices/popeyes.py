"""Popeyes UK — REAL per-restaurant collection prices, straight from the app API.

Popeyes' ordering backend serves the priced menu to anonymous callers: no
guest token, no service token, no basket. One GET returns every category with
`price`, `calories` and the vegetarian/vegan flags already attached.

Handshake
---------
1. **Restaurants** (`/api/v2/restaurants`) — the whole national list in one
   response, each entry carrying `id` (GUID), `storeName`, `storeAddress`,
   `storeLocation.coordinates` and, crucially, a `menus` array::

       "menus": [{"id": "Order Now", "orderingFlow": "Collection", ...},
                 {"id": "Delivery",  "orderingFlow": "Delivery",   ...}]

2. **The priced menu**::

       GET /en/restaurants/{restaurantId}/menus/{menuId}
       -> {"data": {"categories": [{"categoryShortName": ...,
                                    "items": [{"productName", "price",
                                               "calories", ...}]}]}}

TRAP — a wrong `menuId` returns success, not an error
    `menus/en`, `menus/Order%20Now.` and every other guess answer
    ``{"data":{"categories":[]},"errors":[],"hasErrors":false}``. An empty
    category list is the *only* signal that the id was wrong, so this module
    treats zero items as a hard failure rather than "this store has no menu",
    and always takes the id from the restaurant record instead of hardcoding
    it. (The list-of-all-stores response has ids with a trailing full stop for
    some stores — "Order Now." — which is exactly why it must be read, not
    guessed.)

TRAP — the restaurant record only lists the menu that is live *right now*
    Fetch at 08:00 and Sutton advertises exactly one menu, "Order Brekkie"
    (65 items). Fetch at noon and it advertises the main menu instead. Taking
    the restaurant's `menus` array at face value therefore silently prices a
    quarter of the range and drops every chicken item — the whole reason to
    scrape Popeyes. The menu *route*, though, ignores trading hours: "Order
    Now" still returns the full 252-item main menu at breakfast. So this
    module keeps a candidate list of ids seen anywhere in the estate and tries
    them per menu type, taking the first that answers with categories.

TRAP — the menu route ignores `lastOrderTime`, the basket route does not
    Creating a basket for the same store answers `MenuLastOrderTimePassed`
    outside trading hours. The read-only menu route keeps working, which is
    all this adapter needs — it never creates a basket.

TRAP — menu ids are per store and differ by a full stop
    Some stores name their main menu "Order Now.", others "Order Now" or
    "Order Lunch". For Sutton, "Order Now" and "Order Lunch" both resolve to
    the same 252-item menu while "Order Now." returns nothing. Candidates are
    tried in estate-frequency order rather than assumed.

PRICE BASIS
    The Collection menus are fetched by default, so every row is a genuine
    collection price for that branch. Passing ``basis="delivery"`` selects the
    Delivery menus instead; rows are labelled either way.
"""
from __future__ import annotations

import math

from ..base import fetch_protected

CHAIN = "popeyes"

API = "https://pe-uk-ordering-api-fd-eecsdkg6btfeg0cc.z01.azurefd.net"
RESTAURANTS = API + "/api/v2/restaurants"
ORIGIN = "https://popeyesuk.com"

#: Sutton, SM1 — the branch this adapter was verified against.
DEFAULT_STORE_ID = "4a5149ea-fdc9-47a5-848d-faf7ed027cf2"

_FLOW = {"collection": "Collection", "delivery": "Delivery"}


def _get_json(url: str):
    r = fetch_protected(url, referer=ORIGIN + "/")
    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else "no response"
        raise RuntimeError(f"popeyes: GET {url} failed ({code})")
    return r.json()


def restaurants() -> list[dict]:
    """Every Popeyes UK restaurant, with its menu ids and coordinates."""
    return _get_json(RESTAURANTS).get("data") or []


def nearest_store(lat: float, lng: float,
                  estate: list[dict] | None = None) -> dict | None:
    """The closest restaurant to a point, by great-circle distance."""
    best, best_km = None, None
    for r in (estate if estate is not None else restaurants()):
        coords = ((r.get("storeLocation") or {}).get("coordinates") or {})
        rlat, rlng = coords.get("latitude"), coords.get("longitude")
        if rlat is None or rlng is None:
            continue
        dlat = math.radians(rlat - lat)
        dlng = math.radians(rlng - lng)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(rlat))
             * math.sin(dlng / 2) ** 2)
        km = 6371.0 * 2 * math.asin(math.sqrt(a))
        if best_km is None or km < best_km:
            best, best_km = r, km
    return best


def _store(store_id: str | None, lat: float | None, lng: float | None,
           estate: list[dict] | None = None) -> dict:
    estate = estate if estate is not None else restaurants()
    if lat is not None and lng is not None:
        found = nearest_store(lat, lng, estate)
        if found:
            return found
    wanted = store_id or DEFAULT_STORE_ID
    for r in estate:
        if r.get("id") == wanted:
            return r
    raise RuntimeError(f"popeyes: restaurant {wanted} not in the national list")


def menu_id_candidates(store: dict, flow: str, menu_type: str,
                       estate: list[dict]) -> list[str]:
    """Menu ids worth trying for one store, most-likely first.

    The store's own advertised ids come first (they are certainly valid for
    *some* hour of the day), then every id the rest of the estate uses for the
    same flow and menu type, ordered by how many stores use it.
    """
    ordered: list[str] = [m["id"] for m in store.get("menus") or []
                          if m.get("orderingFlow") == flow
                          and m.get("menuType") == menu_type]
    counts: dict[str, int] = {}
    for r in estate:
        for m in r.get("menus") or []:
            if m.get("orderingFlow") == flow and m.get("menuType") == menu_type:
                counts[m["id"]] = counts.get(m["id"], 0) + 1
    for mid in sorted(counts, key=lambda k: -counts[k]):
        if mid not in ordered:
            ordered.append(mid)
    return ordered


def _menu_categories(store_id: str, menu_id: str) -> list[dict]:
    from urllib.parse import quote

    data = _get_json(f"{API}/en/restaurants/{store_id}/menus/{quote(menu_id)}")
    return ((data.get("data") or {}).get("categories")) or []


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 lat: float | None = None, lng: float | None = None,
                 menu_types: tuple[str, ...] = ("Dinner", "Breakfast")) -> list[dict]:
    """Priced menu for one branch.

    Give a `store_id`, or a `lat`/`lng` to use whichever branch is nearest.
    Both the main and breakfast menus are fetched by default and merged, since
    which one the API advertises depends on the hour you happen to run this.
    """
    flow = _FLOW.get(basis)
    if flow is None:
        raise ValueError(f"popeyes: unknown basis {basis!r}")
    estate = restaurants()
    store = _store(store_id, lat, lng, estate)
    label = f"Popeyes {store.get('storeName')}"

    out: list[dict] = []
    seen: set[str] = set()
    tried: list[str] = []
    for menu_type in menu_types:
        for menu_id in menu_id_candidates(store, flow, menu_type, estate):
            tried.append(menu_id)
            categories = _menu_categories(store["id"], menu_id)
            if not categories:
                continue          # wrong id for this store — try the next
            for cat in categories:
                for item in cat.get("items") or []:
                    price = item.get("price")
                    name = (item.get("productName") or "").strip()
                    if not name or price in (None, 0) or name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    kcal = item.get("calories")
                    try:
                        kcal = float(kcal) if kcal not in (None, "") else None
                    except (TypeError, ValueError):
                        kcal = None
                    out.append({
                        "name": name,
                        "price_gbp": round(float(price), 2),
                        "basis": basis,
                        "store": label,
                        "category": cat.get("categoryShortName"),
                        "kcal": kcal,
                        "vegetarian": bool(item.get("isSuitableForVegetarians")),
                        "vegan": bool(item.get("isSuitableForVegans")),
                    })
            break                 # this menu type is covered
    if not out:
        # An unknown menu id yields an empty category list with no error, so
        # "no items" means the handshake broke — never that the shop is bare.
        raise RuntimeError(
            f"popeyes: no menu for {label} — tried {tried}; the route or the "
            f"menu id scheme has changed")
    return out


if __name__ == "__main__":  # pragma: no cover
    for row in fetch_prices()[:20]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
