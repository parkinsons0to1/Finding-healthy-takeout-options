"""PizzaExpress UK — REAL per-branch prices from PizzaExpress's OWN ordering site.

WHICH BUSINESS
    `www.pizzaexpress.com` links every "Order" call to action to
    `order.pizzaexpress.com` — a first-party React storefront (Zonal-hosted
    menu data, Dojo/Braintree for payment) offering both collection AND
    delivery from the same site, no account needed to browse. Just Eat also
    lists PizzaExpress branches with both service types, but that marketplace
    was not needed here — the first-party site is a full, public substitute.

Handshake
---------
The storefront is a client-rendered React app; its JS bundle was read to
find these calls, not guessed. Plain `requests` — no Cloudflare/TLS
obstacle, no auth token of any kind.

1. ``GET https://order.pizzaexpress.com/api/restaurant/LookupName/{postcode}/{isDelivery}``
   — nearest branches to a postcode, each with a numeric `id` (e.g. "3457"),
   `isCollectionDisabled`/`isDeliveryDisabled` flags.
2. ``GET https://order.pizzaexpress.com/api/application?restaurantId={id}&menuEtag=``
   — the full priced menu for that branch, plus site config (payment keys,
   feature flags — ignored here).

MENU SHAPE — deeply nested, but the price you want is at the top
    `menu.categories[].subCategories[].subProducts[]` is a recursive
    "customise your dish" tree (choose a base, then toppings, each its own
    `subProducts` layer many levels deep). This module does NOT walk into
    that tree: every top-level `subProducts[]` entry already carries its own
    correct, fully-computed `displayPrice` for the default configuration
    (e.g. "Margherita" → `displayPrice: 19.9`, its "Classic" base) — checked
    exhaustively at Sutton High Street: all 119 top-level products had a
    nonzero `displayPrice`, none needed a fallback into the nested tree.
    Deeper nodes (`cost` on a "Choose your base" option, a topping's own
    `cost`) are upsell deltas for customisation, not separate purchasable
    items, and are not read.

PRICE BASIS — this module reports collection; delivery was checked and is
              priced identically at every item checked
    `getApplicationState` takes no channel parameter — one `menu` serves
    both service types, and checkout (not read here) is where delivery adds
    its own separate charge, the same shape `pizza_hut.py` documents for
    Pizza Hut Delivery. So every row is labelled "collection", which is also
    correct for delivery at the item level.

NAME DRIFT — Gluten-Free naming is reversed between the site and the book
    The order site prefixes gluten-free pizzas ("Gluten-Free American",
    "Gluten-Free Margherita"); `data/db/pizza_express.json` (the nutrition
    book) suffixes them instead ("American GF", not always with a space
    before "GF", and some rows carry an additional "(Dine Out)"/"Gluten
    Free" spelled-out variant this module does not attempt to disambiguate).
    For every item whose name starts "Gluten-Free ", this module emits a
    SECOND row aliased to `"{rest} GF"` (e.g. "Gluten-Free American" also
    becomes "American GF") alongside the original name, rather than
    replacing it — both may be useful, and only the well-known GF-suffix
    convention is applied, not a guess about which of the book's several
    GF-variant spellings is meant.

PER STORE
    PizzaExpress - Sutton High Street, SM1 1DJ (restaurant id "3457") is the
    default, matching every other adapter's south-London default.
"""
from __future__ import annotations

import re

from ..base import session

_POSTCODE_RE = re.compile(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")

CHAIN = "pizza_express"

LOOKUP_URL = "https://order.pizzaexpress.com/api/restaurant/LookupName/{postcode}/{is_delivery}"
APPLICATION_URL = "https://order.pizzaexpress.com/api/application"

#: PizzaExpress - Sutton High Street, SM1 1DJ.
DEFAULT_RESTAURANT_ID = "3457"
DEFAULT_LABEL_HINT = "Sutton High Street"


def _get(url: str, **params):
    s = session()
    return s.get(url, params=params, timeout=30)


def find_restaurants(postcode: str, is_delivery: bool = False) -> list[dict]:
    """Nearest PizzaExpress branches to a UK postcode, per the order site."""
    url = LOOKUP_URL.format(postcode=postcode.replace(" ", "").upper(),
                            is_delivery=str(bool(is_delivery)).lower())
    s = session()
    r = s.get(url, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"pizza_express: restaurant lookup HTTP {r.status_code} "
                           f"for {postcode!r}")
    return (r.json() or {}).get("restaurants") or []


def _walk_top_level(menu: dict):
    for cat in menu.get("categories") or []:
        cat_name = cat.get("name")
        for sc in cat.get("subCategories") or []:
            sub_name = sc.get("name")
            for p in sc.get("subProducts") or []:
                yield cat_name, sub_name, p


def fetch_prices(restaurant_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced menu for one PizzaExpress branch.

    Give a `restaurant_id` (from `find_restaurants`), or a `postcode` to use
    the nearest branch. `basis` is always reported "collection" — see the
    module docstring's PRICE BASIS note.
    """
    if basis != "collection":
        raise ValueError(f"pizza_express: unknown basis {basis!r} (this module "
                         f"only reports 'collection' — verified identical to "
                         f"delivery at the item level)")

    label_hint = None
    if restaurant_id is None and postcode:
        found = find_restaurants(postcode)
        if not found:
            raise RuntimeError(f"pizza_express: no branch found for {postcode!r}")
        restaurant_id = found[0]["id"]
        label_hint = found[0].get("name")
    else:
        restaurant_id = restaurant_id or DEFAULT_RESTAURANT_ID
        label_hint = DEFAULT_LABEL_HINT if restaurant_id == DEFAULT_RESTAURANT_ID else None

    r = _get(APPLICATION_URL, restaurantId=restaurant_id, menuEtag="")
    if r.status_code != 200:
        raise RuntimeError(f"pizza_express: application API HTTP {r.status_code} "
                           f"for restaurant {restaurant_id!r}")
    payload = r.json() or {}
    menu = payload.get("menu")
    if not menu:
        raise RuntimeError(f"pizza_express: no menu in application payload for "
                           f"restaurant {restaurant_id!r} — the response shape "
                           f"has moved")
    categories = menu.get("categories") or []
    if not categories:
        raise RuntimeError(f"pizza_express: menu for restaurant {restaurant_id!r} "
                           f"had zero categories")

    restaurant = payload.get("restaurant") or {}
    addr = restaurant.get("fullAddress") or ""
    m = _POSTCODE_RE.search(addr.strip().upper())
    town = m.group(0) if m else None
    name = restaurant.get("name") or label_hint or f"restaurant {restaurant_id}"
    label = f"PizzaExpress - {name} ({town})" if town else f"PizzaExpress - {name}"

    out: list[dict] = []
    for cat_name, sub_name, p in _walk_top_level(menu):
        price = p.get("displayPrice")
        item_name = (p.get("name") or "").strip()
        if not item_name or not price:
            continue
        row = {
            "name": item_name,
            "price_gbp": round(float(price), 2),
            "basis": "collection",
            "store": label,
            "category": f"{cat_name} - {sub_name}" if sub_name and sub_name != cat_name else cat_name,
        }
        cal = p.get("calories")
        if cal:
            digits = "".join(ch for ch in cal.split("Serves")[0] if ch.isdigit())
            if digits:
                row["kcal"] = float(digits)
        out.append(row)
        if item_name.lower().startswith("gluten-free "):
            alias = item_name[len("gluten-free "):].strip() + " GF"
            out.append({**row, "name": alias})

    if not out:
        raise RuntimeError(f"pizza_express: restaurant {restaurant_id!r} had "
                           f"{len(categories)} categories but zero priced items "
                           f"— the item shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
