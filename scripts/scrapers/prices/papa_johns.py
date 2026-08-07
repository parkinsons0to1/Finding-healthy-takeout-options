"""Papa John's UK — REAL per-store prices from their own ordering API.

Handshake
---------
No session, no token, no cookie. Papa John's UK web app (jQuery, not a SPA
framework) ships `/js/pj_main.js`, whose webpack module 10 defines::

    const apiSubdomain = "api2";
    const API = `https://${apiSubdomain}.papajohns.co.uk/`;

Every menu call in that bundle is a plain `$.ajax` GET with a single custom
header, `X-PJ-Platform: Web`. Three endpoints are all that is needed:

1. ``GET /api/v1/Store/collection/{postcode}``  -> stores near a postcode, each
   with a numeric ``id`` (Carshalton = 268), ``deliveryCharge`` and
   ``minimumSpend``. A sibling ``/api/v1/Store/delivery/{postcode}`` exists and
   returns the same store records.
2. ``GET /api/v1/Menu``                        -> the national product
   catalogue: id, name, section, category, veg/vegan flags. NO prices.
3. ``GET /api/v1/Menu/{storeId}``              -> that store's *price list*:
   ``[{"id": <productId>, "variations": [{"name": "Large Original",
   "price": 23.99, "priceModifier": 2.99, ...}]}]``

TRAP — ``priceModifier`` is already baked into ``price``, do NOT add it
    A Large Original Spicy Sausage is ``price=23.99, priceModifier=0``; the
    Large Stuffed Crust variation of the same pizza is ``price=26.98,
    priceModifier=2.99`` — i.e. 23.99 + the 2.99 crust upcharge. ``price`` is
    the final charge; ``priceModifier`` is the upcharge component, reported so
    the UI can show "+£2.99 for stuffed crust". Summing them inflates every
    stuffed-crust line by £2.99.

Toppings appear as products with an empty ``section``; they carry a per-size
surcharge in the same shape, which is why this adapter keeps only the named
menu sections by default.

PRICE BASIS — collection/list
    ``/api/v1/Menu/{storeId}`` takes no shipment-method argument: passing
    ``?shipmentMethod=1``, ``?shipmentMethod=2``, ``?collection=true`` or
    ``?shipmentType=Collection`` returns a byte-identical body. There is one
    price list per store and delivery is charged separately via the store's
    ``deliveryCharge`` field (£1.99 at Carshalton). So these are menu list
    prices with NO delivery inflation — collection basis — and a delivery quote
    is this price plus the store's delivery charge.

Traps
-----
* The store list is franchise-specific: prices genuinely differ store to
  store, so ``store_id`` matters. Do not cache one store's list nationally.
* ``name`` fields contain HTML entities (``The Works&trade;``); they are
  unescaped here.
* Money arrives as 4-dp decimals (``1.7000``); rounded to pence.
"""
from __future__ import annotations

import html

from ..base import fetch_protected

CHAIN = "papa_johns"

API = "https://api2.papajohns.co.uk/"
HEADERS = {
    "X-PJ-Platform": "Web",
    "Accept": "application/json",
    "Origin": "https://www.papajohns.co.uk",
    "Referer": "https://www.papajohns.co.uk/order/menu",
}

#: Carshalton (SM5 1AG) — the store used to verify this adapter.
DEFAULT_STORE_ID = "268"

#: Sections that are real menu lines. The empty section holds toppings and
#: crust surcharges, which are modifiers rather than orderable items.
MENU_SECTIONS = ("Pizzas", "Sides", "Desserts", "Drinks", "Dips")


def _get(path: str):
    r = fetch_protected(API + path, referer=HEADERS["Referer"])
    if r is None or r.status_code != 200:
        raise RuntimeError(f"papa_johns: GET {path} failed "
                           f"({r.status_code if r is not None else 'no response'})")
    return r.json()


def find_stores(postcode: str) -> list[dict]:
    """Stores near a postcode, nearest first. `id` is what fetch_prices wants."""
    return _get(f"api/v1/Store/collection/{postcode.replace(' ', '')}").get("data", [])


def fetch_prices(store_id: str | None = None) -> list[dict]:
    store_id = str(store_id or DEFAULT_STORE_ID)

    catalogue = {p["id"]: p for p in _get("api/v1/Menu").get("data", [])}
    price_list = _get(f"api/v1/Menu/{store_id}").get("data", [])

    out: list[dict] = []
    for entry in price_list:
        product = catalogue.get(entry.get("id"))
        if not product:
            continue
        if product.get("section") not in MENU_SECTIONS:
            continue
        base_name = html.unescape(product.get("name") or "").strip()
        for var in entry.get("variations") or []:
            price = var.get("price") or 0
            if not price:
                continue
            variant = html.unescape(var.get("name") or "").strip()
            name = f"{base_name} - {variant}" if variant else base_name
            out.append({
                "name": name,
                "price_gbp": round(float(price), 2),
                "basis": "collection",
                "store": f"Papa John's #{store_id}",
                "category": product.get("section"),
            })
    if not out:
        raise RuntimeError(f"papa_johns: no priced items for store {store_id}")
    return out


if __name__ == "__main__":  # pragma: no cover
    for row in fetch_prices()[:20]:
        print(f"{row['price_gbp']:>7.2f}  {row['name']}")
