"""Pizza Hut DELIVERY UK — REAL per-store prices from the Yum! storefront API.

WHICH BUSINESS
    These are **Pizza Hut Delivery** prices (`www.pizzahut.co.uk`), the
    franchised delivery/collection estate. They are NOT Pizza Hut Restaurants
    (`pizzahut.co.uk/restaurants`), which is a separate company (Heart With
    Smart) on a different ordering platform with a different menu and different
    money — a Restaurants buffet price would be meaningless next to these. The
    nutrition rows in ``data/db/pizza_hut.json`` come from the Pizza Hut
    Delivery allergens booklet, so the two halves match.

Handshake
---------
Plain `requests` — no TLS impersonation needed, no cookie, no account.

1. **Guest token** — the site's own OIDC endpoint mints one for anybody::

       POST https://www.pizzahut.co.uk/v1/oidc/oauth2/token
       originatingAppId: ph_uk_web
       grant_type=guest&client_id=ph_uk_web
       -> {"access_token": "<JWT>", ...}

2. **Everything else** is one federated GraphQL endpoint,
   ``https://www.pizzahut.co.uk/ph_uk/storefront/graphql``, with
   ``Authorization: Bearer <token>`` and ``originatingAppId: ph_uk_web``.
   It permits introspection, which is how the queries below were derived::

       Query.storesNearPoint(point: GeoJSONPointInput, occasion: DiningOccasion,
                             maxDistance: DistanceInput, first: PositiveInt)
       Query.storeByNumber(storeNumber: ExternalID) -> Store
       Store.menuByChannel(channel: SalesChannel) -> Menu
       Menu.products(first:, after:) -> ProductConnection    # priced variants
       Menu.bundles(first:, after:)  -> BundleConnection     # the deals

TRAP — `GeoJSONPointInput` has NO `type` field
    Sending the textbook GeoJSON ``{"type":"Point","coordinates":[lng,lat]}``
    does not fail validation at the gateway. It is forwarded, and the
    `store-menu` subgraph answers 422 with the gnomically unhelpful pair
    ``"Internal Server Error. This is not normal behavior, alert the Yum.dev
    Platform team."`` + ``"unknown field"``, naming no field and no path. The
    input takes ``{"coordinates": [lng, lat]}`` and nothing else. Longitude
    first.

TRAP — `DistanceUnit` is `MI`/`KM`, not `MILE`.

TRAP — `PageInfo` has `hasNextPage` but NO `endCursor`
    Paging is by the last edge's own ``cursor``. Asking for ``endCursor`` is a
    hard validation error, and a menu is ~200 products, so a single unpaged
    ``first: 50`` silently returns a quarter of the range.

TRAP — variant names are stale marketing copy; the PRODUCT name is the truth
    Product "Tuna Melt" has the single variant *"Melts Pepperoni Feast |
    Single"*. "Red Bull Sugar Free" ships variant "Red Bull Original | 250ml".
    "Loaded Garlic Bread Bacon" ships "Loaded Garlic Bread Pepperoni". Naming
    non-pizza rows from the variant therefore prices tuna as pepperoni. Only
    pizzas take size/crust from the variant name, and even then the pizza's own
    name comes from the product.

TRAP — "Handcrafted" in the ordering menu means NO garlic sprinkle
    The booklet lists both "Large Handcrafted" and "Large Handcrafted (No
    Garlic Sprinkle)". The menu's crust segments are "Handcrafted with garlic"
    and "Handcrafted" — the opposite way round from what the words suggest.
    Verified on calories, which both sides publish: Chicken Supreme Small
    "Handcrafted with garlic" = 729 kcal = booklet "Small Handcrafted"; Small
    "Handcrafted" = 714 kcal = booklet "Small Handcrafted (No Garlic
    Sprinkle)". Getting this backwards mislabels 358 of 636 pizza rows.

TRAP — a third of the variants are priced 0
    Variants whose name ends "| MyBox" (and some "| undefined") are the
    components a bundle draws from, not orderable lines; they carry
    ``price.amount == 0``. They are dropped, not emitted as free pizza.

PRICE BASIS — collection, and delivery costs the same for the item
    ``menuByChannel`` takes no occasion argument, and every product and variant
    in the estate returns an EMPTY ``availability.schedule`` — i.e. no item is
    gated to one occasion. Checked across all 205 products / 792 variants at
    Carshalton. So one price list serves both, and each row here is a genuine
    collection price that also happens to be the delivery item price (delivery
    adds a separate charge at checkout, not an item uplift).

    The occasion difference lives entirely in the **deals**, which DO carry
    ``availability.schedule[].occasion``: "My Medium Meal 1299 (collection)"
    against "My Medium Meal 1499 Delivery", "Any Size £9.99" gated to CARRYOUT,
    "Mybox 1499" gated to DELIVERY. Bundle rows are therefore labelled from
    their own schedule and are worth having — a collection deal is often the
    cheapest route to a whole pizza.

NAME DRIFT — the booklet and the till do not agree, so aliases are emitted
    The allergens booklet says "The Meaty One", "Vegetable Supreme", "Meat
    Supreme"; the ordering menu says "Meaty One", "Veg Supreme", "Supreme".
    Every alias in ``_BOOKLET_ALIASES`` was confirmed by joining on calories
    at matching size+crust (e.g. all 9 sizes of booklet "Meat Supreme" carry
    exactly the calories of menu "Supreme"), never by eyeballing the words.
    Aliased rows repeat the same price under the booklet's spelling so the
    nutrition join lands; ``"Chicken Feast"`` legitimately maps to two booklet
    rows (with and without sweetcorn) at one price.

PER STORE — prices really do differ
    Of the 98 variants Carshalton and the (halal) Bradford Otley Road store
    both sell, 17 are priced differently. Do not treat one store's list as
    national.
"""
from __future__ import annotations

import re

from ..base import session

CHAIN = "pizza_hut"

TOKEN_URL = "https://www.pizzahut.co.uk/v1/oidc/oauth2/token"
GRAPHQL = "https://www.pizzahut.co.uk/ph_uk/storefront/graphql"
APP_ID = "ph_uk_web"

#: Carshalton, SM5 2DW — the branch this adapter was verified against, chosen
#: to sit alongside the other adapters' south-London default.
DEFAULT_STORE_NUMBER = "8232"

_OCCASION = {"collection": "CARRYOUT", "delivery": "DELIVERY"}
_BASIS_OF = {"CARRYOUT": "collection", "DELIVERY": "delivery"}

#: Menu crust segment -> the booklet's spelling. See the garlic-sprinkle trap.
_CRUSTS = {
    "handcrafted": "Handcrafted (No Garlic Sprinkle)",
    "handcrafted with garlic": "Handcrafted",
    "pan": "Pan",
    "stuffed crust": "Stuffed Crust",
    "cheesy bites": "Cheesy Bites",
    "gluten free": "Gluten Free",
    "bny": "Big New Yorker",
    "bny without garlic": "Big New Yorker (No Garlic Sprinkle)",
}

#: Ordering-menu pizza name -> the name(s) the nutrition booklet uses for the
#: same recipe. Each pairing verified on calories at matching size and crust.
_BOOKLET_ALIASES = {
    "meaty one": ["The Meaty One"],
    "veg supreme": ["Vegetable Supreme"],
    "veg sizzler": ["Veggie Sizzler"],
    "supreme": ["Meat Supreme"],
    "chicken bacon club": ["Chicken & Bacon Club"],
    "bbq meatfeast": ["BBQ Meat Feast"],
    "hot honey pepperoni feast": ["Hot Honey Pepperoni"],
    "chicken pepperoni": ["NEW - Hot Honey Sriracha Chicken & Pepperoni"],
    # One priced product, two booklet nutrition rows.
    "chicken feast": ["Chicken Feast (With Sweetcorn)",
                      "Chicken Feast (Without Sweetcorn)"],
    # The booklet calls the plant-based range "Plant-Based"; the till "Vegan".
    "vegan margherita": ["Plant-Based Margherita"],
    "vegan veg supreme": ["Plant-Based Veg Supreme"],
    "vegan veg sizzler": ["Plant-Based Veg Sizzler"],
}

#: Chicken portions: the booklet prefixes a share size the till does not use.
_PORTION_PREFIX = {"4": "Single", "5": "Single", "7": "Duo", "10": "Duo",
                   "14": "Group"}


def _api():
    """A requests session already carrying a fresh anonymous guest token."""
    s = session()
    r = s.post(TOKEN_URL,
               data={"grant_type": "guest", "client_id": APP_ID},
               headers={"originatingAppId": APP_ID}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"pizza_hut: guest token failed ({r.status_code}) "
                           f"{r.text[:200]}")
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("pizza_hut: guest token response had no access_token")
    s.headers.update({"Authorization": "Bearer " + token,
                      "originatingAppId": APP_ID})
    return s


def _query(s, query: str, variables: dict | None = None) -> dict:
    r = s.post(GRAPHQL, json={"query": query, "variables": variables or {}},
               timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"pizza_hut: graphql HTTP {r.status_code} "
                           f"{r.text[:300]}")
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"pizza_hut: graphql errors {payload['errors']}")
    return payload.get("data") or {}


_STORE_SEARCH = """
query Near($p: GeoJSONPointInput!, $o: DiningOccasion!, $d: Float!, $n: PositiveInt!) {
  storesNearPoint(point: $p, occasion: $o, first: $n,
                  maxDistance: {value: $d, unit: MI}) {
    edges { node {
      distance { value unit }
      store { storeNumber name acceptingOnlineOrders
              address { address1 city postalCode } } } }
  }
}
"""

_PRODUCTS = """
query Menu($s: ExternalID!, $after: String) {
  storeByNumber(storeNumber: $s) {
    storeNumber name address { city postalCode }
    menuByChannel(channel: WEB) {
      menuCode
      products(first: 50, after: $after) {
        pageInfo { hasNextPage }
        edges { cursor node {
          productCode name
          categories { name }
          variants { name price { amount } nutritionInformation
                     availability { schedule { occasion } } } } }
      }
    }
  }
}
"""

_BUNDLES = """
query Deals($s: ExternalID!, $after: String) {
  storeByNumber(storeNumber: $s) {
    menuByChannel(channel: WEB) {
      bundles(first: 50, after: $after) {
        pageInfo { hasNextPage }
        edges { cursor node {
          bundleCode name price { amount } promoTags
          categories { name }
          availability { schedule { occasion } } } }
      }
    }
  }
}
"""


def find_stores(lat: float, lng: float, basis: str = "collection",
                radius_miles: float = 10.0, limit: int = 10) -> list[dict]:
    """Nearby Pizza Hut Delivery stores, nearest first.

    Note the coordinate order: `point` is ``[longitude, latitude]``, and the
    input object must not carry a ``type`` key (see the module docstring).
    """
    occasion = _OCCASION.get(basis)
    if occasion is None:
        raise ValueError(f"pizza_hut: unknown basis {basis!r}")
    data = _query(_api(), _STORE_SEARCH,
                  {"p": {"coordinates": [lng, lat]}, "o": occasion,
                   "d": float(radius_miles), "n": int(limit)})
    return [e["node"] for e in
            ((data.get("storesNearPoint") or {}).get("edges") or [])]


def _paged(s, query: str, store_number: str, path: tuple[str, ...]) -> list[dict]:
    """Walk a Relay connection using each edge's own cursor (no endCursor)."""
    after, nodes, store = None, [], None
    while True:
        data = _query(s, query, {"s": store_number, "after": after})
        node = data.get("storeByNumber")
        if not node:
            raise RuntimeError(f"pizza_hut: no store {store_number}")
        store = store or node
        menu = node.get("menuByChannel")
        if not menu:
            raise RuntimeError(f"pizza_hut: store {store_number} has no WEB menu")
        conn = menu
        for key in path:
            conn = conn.get(key) or {}
        for edge in conn.get("edges") or []:
            nodes.append(edge["node"])
            after = edge["cursor"]
        if not (conn.get("pageInfo") or {}).get("hasNextPage"):
            return nodes, store


def _kcal(nutrition_information) -> float | None:
    for fact in nutrition_information or []:
        if str(fact).startswith("calories:"):
            try:
                return float(str(fact).split(":", 1)[1])
            except ValueError:
                return None
    return None


def _basis_from(availability, default: str) -> str:
    occasions = {slot.get("occasion")
                 for slot in ((availability or {}).get("schedule") or [])}
    if len(occasions) == 1:
        return _BASIS_OF.get(occasions.pop(), default)
    return default


def _halal_split(product_name: str) -> tuple[str, bool]:
    """Halal stores suffix the recipe (\"Chicken Feast Halal\"); the booklet
    prefixes it (\"Halal Chicken Feast\"). Split so the alias table, which is
    keyed on the plain recipe, still applies."""
    stripped = re.sub(r"\s+halal\b", "", product_name, flags=re.I).strip()
    return (stripped, stripped.lower() != product_name.strip().lower())


def _pizza_names(product_name: str, variant_name: str) -> list[str]:
    """Booklet-style names for one priced pizza variant.

    ``"Chicken Supreme | Large | Stuffed crust | Default"`` becomes
    ``["Chicken Supreme — Large Stuffed Crust"]``; a recipe the booklet spells
    differently yields one name per booklet spelling.
    """
    parts = [p.strip() for p in (variant_name or "").split("|")]
    if len(parts) < 3:
        return [product_name.strip()]
    size, crust = parts[1], _CRUSTS.get(parts[2].lower(), parts[2])
    base, halal = _halal_split(product_name)
    bases = _BOOKLET_ALIASES.get(base.lower(), [base])
    if halal:
        bases = [f"Halal {b}" for b in bases]
    # Gluten-free comes in one size only and the booklet omits it.
    suffix = "Gluten Free" if crust == "Gluten Free" else f"{size} {crust}"
    return [f"{b} — {suffix}" for b in bases]


def _side_names(product_name: str, variant_name: str) -> list[str]:
    """Names for a non-pizza line, taken from the PRODUCT (see the stale-variant
    trap) plus the booklet's share-size spelling where the variant states a
    piece count."""
    name = (product_name or "").strip()
    names = [name]
    parts = [p.strip() for p in (variant_name or "").split("|")]
    if len(parts) >= 2:
        m = re.fullmatch(r"(\d+)\s*(strips?|pieces?|wings?|chunks?|tenders?)",
                         parts[1], flags=re.I)
        if m:
            count, unit = m.group(1), m.group(2).title()
            core = re.sub(r"\s*\b(single|four|five|seven|ten|fourteen|duo|group)\b",
                          "", name, flags=re.I).strip()
            portion = f"{core} ({count} {unit})"
            names.append(portion)
            prefix = _PORTION_PREFIX.get(count)
            if prefix:
                names.append(f"{prefix} - {portion}")
    return names


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 lat: float | None = None, lng: float | None = None,
                 include_deals: bool = True) -> list[dict]:
    """Priced menu for one Pizza Hut Delivery branch.

    Give a `store_id` (the store number, e.g. "8232"), or a `lat`/`lng` to use
    the nearest branch. Item prices are occasion-independent, so `basis` only
    selects which deals are kept; item rows are always labelled "collection".
    """
    if basis not in _OCCASION:
        raise ValueError(f"pizza_hut: unknown basis {basis!r}")
    s = _api()

    if store_id is None and lat is not None and lng is not None:
        near = find_stores(lat, lng, basis=basis, limit=1)
        if not near:
            raise RuntimeError(f"pizza_hut: no store near {lat},{lng}")
        store_id = near[0]["store"]["storeNumber"]
    store_number = str(store_id or DEFAULT_STORE_NUMBER)

    products, store = _paged(s, _PRODUCTS, store_number, ("products",))
    label = (store.get("name") or f"Pizza Hut #{store_number}").strip()
    town = ((store.get("address") or {}).get("postalCode") or "").strip()
    label = f"{label} ({town})" if town else label

    out: list[dict] = []
    seen: set[str] = set()

    def emit(names, pence, category, kcal, row_basis):
        for name in names:
            key = name.strip().lower()
            if not name.strip() or key in seen:
                continue
            seen.add(key)
            out.append({"name": name.strip(),
                        "price_gbp": round(pence / 100.0, 2),
                        "basis": row_basis, "store": label,
                        "category": category, "kcal": kcal})

    for product in products:
        is_pizza = str(product.get("productCode") or "").startswith("pizza.")
        category = ((product.get("categories") or [{}])[0] or {}).get("name")
        for variant in product.get("variants") or []:
            pence = (variant.get("price") or {}).get("amount")
            if not pence:
                continue          # MyBox / bundle-component rows price at 0
            names = (_pizza_names(product["name"], variant.get("name"))
                     if is_pizza else
                     _side_names(product["name"], variant.get("name")))
            emit(names, pence, category, _kcal(variant.get("nutritionInformation")),
                 _basis_from(variant.get("availability"), "collection"))

    if include_deals:
        bundles, _ = _paged(s, _BUNDLES, store_number, ("bundles",))
        for bundle in bundles:
            pence = (bundle.get("price") or {}).get("amount")
            if not pence:
                continue
            tags = bundle.get("promoTags") or []
            if any(str(t).startswith("hidden.") for t in tags):
                continue          # loyalty rewards, not a price anyone pays
            deal_basis = _basis_from(bundle.get("availability"), "collection")
            if deal_basis != basis:
                continue
            emit([bundle.get("name") or ""], pence, "Deals", None, deal_basis)

    if not out:
        raise RuntimeError(
            f"pizza_hut: no priced items for store {store_number} — an empty "
            f"menu means the handshake broke, not that the shop is bare")
    return out


if __name__ == "__main__":  # pragma: no cover
    for row in fetch_prices()[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
