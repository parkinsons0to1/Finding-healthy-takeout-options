"""Taco Bell UK — REAL per-store prices from the Yum! storefront API.

SAME PLATFORM AS PIZZA HUT
    `order.tacobell.co.uk` runs the identical federated Yum! storefront
    GraphQL stack as Pizza Hut Delivery (see `pizza_hut.py`): a guest OIDC
    token, one `storefront/graphql` endpoint, `Query.storesNearPoint` /
    `Query.storeByNumber` / `Menu.products` / `Menu.bundles`. The org changes
    (`tb_uk` instead of `ph_uk`) and so does the app id (`tb_uk_web` instead
    of `ph_uk_web`), but the schema shapes, the paging-by-cursor rule and the
    `GeoJSONPointInput` quirk are all identical — confirmed by introspecting
    this endpoint directly rather than assumed from the sibling chain.

TRAP — `order.tacobell.co.uk` hangs plain `requests`, every request
    Unlike Pizza Hut's host, this one doesn't reject a bad handshake with a
    4xx — it accepts the TCP connection and then never answers, so `requests`
    sits until it times out. `curl_cffi` impersonating a real browser TLS
    fingerprint (`base.post_protected` / `fetch_protected`) gets an immediate
    200. This applies to *every* call including the guest-token POST, not
    just the GraphQL body — token requests via plain `requests` hang too.

TRAP — ad hoc GraphQL variables silently vanish on `__type` introspection
    A variabled introspection query (`query($t: String!){ __type(name: $t) }`)
    comes back "missing value for non-null variable" even though the exact
    same variables argument works for `storesNearPoint`/`storeByNumber`
    queries. Hardcoding the type name as a string literal in the query text
    works fine. Only matters for exploring the schema, not for this adapter.

TRAP — "Loyalty Reward" bundles are not a price a guest can pay
    A handful of bundles ("Loyalty Reward - Birthday", "Loyalty Reward - 250
    Points - Lg Drink") carry a real `price.amount` — but that price is what
    you pay *in addition to* redeeming loyalty points you don't have as an
    anonymous guest. Unlike Pizza Hut's `hidden.` promoTag, there is no
    machine-readable flag; they are recognised and dropped by name.

TRAP — a handful of variants price at 0
    ("20x Chicken Bites" as a component of "20x Chicken Nachos", "2x Churros
    + Dip", "3x Crispy Chicken Tenders + Dip") — bundle-component rows, same
    pattern as Pizza Hut's MyBox variants. Dropped, not emitted as free food.

NAME DRIFT — menu vs. the Nutritionix-hosted booklet
    `data/db/taco_bell.json` (see that scraper's docstring) is built from a
    Nutritionix table whose names disagree with the ordering menu in three
    ways, each verified by matching calories rather than guessed from the
    words:

    1. **Protein is a menu-picker, not a separate product** — the till sells
       one "BBQ Habanero Burrito" at one price; Nutritionix lists nutrition
       for "BBQ Habanero Burrito - Beef" / "- Chicken" / "- Black Beans"
       separately (verified: all three share the till's £6.19). Every priced
       row is therefore aliased under every known protein suffix.
    2. **"Supreme" is sometimes only on one side.** "Grilled Cheese Crunchwrap
       Supreme®" (till) is 614 kcal; Nutritionix's 614-kcal row is "Grilled
       Cheese Crunchwrap" (no Supreme) — confirmed by calories, since the
       token sets don't overlap enough to catch this generically.
    3. **"Side "-prefixed sauces/extras** ("Side Nacho Cheese Sauce", "Side
       Sour Cream") are Nutritionix's plain "Nacho Cheese Sauce", "Sour
       Cream" — the till's "Side " prefix is dropped as an alias.
    4. **Drink/fries/nachos sizing** — the till's variant suffix is "Reg"/
       "Lg" ("Seasoned Fries Lg"); the booklet spells sizes out in
       parentheses ("Seasoned Fries (Large)").

    Aliases are additive (the original name is always kept too), so a change
    upstream can only add matches, never silently drop the literal name.

PRICE BASIS — collection
    Every product variant's `availability.schedule` was empty at Wimbledon
    (94 products / >100 variants checked); the one bundle that does carry a
    schedule ("Cravings Lunch Deal") includes CARRYOUT in it. So, as with
    Pizza Hut, one price list serves both occasions and every row here is
    labelled "collection".

STORE — Wimbledon, SW19 1RF (094006)
    `storesNearPoint` was queried from Wimbledon Broadway; store number
    094006 ("London Wimbledon") came back 0.1mi away and is the default.
"""
from __future__ import annotations

import json
import re

from ..base import post_protected

CHAIN = "taco_bell"

TOKEN_URL = "https://order.tacobell.co.uk/v1/oidc/oauth2/token"
GRAPHQL = "https://order.tacobell.co.uk/tb_uk/storefront/graphql"
APP_ID = "tb_uk_web"

#: Wimbledon, SW19 1RF — the branch this adapter was verified against.
DEFAULT_STORE_NUMBER = "094006"

_OCCASION = {"collection": "CARRYOUT", "delivery": "DELIVERY"}
_BASIS_OF = {"CARRYOUT": "collection", "DELIVERY": "delivery"}

#: Proteins Taco Bell UK lets you swap for free; the till prices the dish
#: once and Nutritionix lists nutrition once per protein (see NAME DRIFT #1).
_PROTEINS = ("Beef", "Chicken", "Grilled Chicken", "Black Beans", "Black Bean")

#: Verified by matching calories exactly (NAME DRIFT #2) — the Nutritionix
#: name for a till product whose own name doesn't contain it.
_EXPLICIT_ALIASES = {
    "grilled cheese crunchwrap supreme": ["Grilled Cheese Crunchwrap"],
}

_SIZE_SUFFIX = {"reg": "(Regular)", "lg": "(Large)", "xl": "(XL)"}


def _graphql(headers: dict, query: str, variables: dict) -> dict:
    r = post_protected(GRAPHQL, data=json.dumps(
        {"query": query, "variables": variables}).encode("utf-8"),
        headers=headers)
    if r is None:
        raise RuntimeError("taco_bell: every TLS profile failed for graphql")
    if r.status_code != 200:
        raise RuntimeError(f"taco_bell: graphql HTTP {r.status_code} "
                           f"{r.text[:300]}")
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"taco_bell: graphql errors {payload['errors']}")
    return payload.get("data") or {}


def _token() -> str:
    r = post_protected(TOKEN_URL,
                       data={"grant_type": "guest", "client_id": APP_ID},
                       headers={"originatingAppId": APP_ID,
                                "Content-Type": "application/x-www-form-urlencoded"})
    if r is None or r.status_code != 200:
        raise RuntimeError("taco_bell: guest token request failed "
                           f"({r.status_code if r else 'no response'})")
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("taco_bell: guest token response had no access_token")
    return token


def _headers(token: str) -> dict:
    return {"Authorization": "Bearer " + token, "originatingAppId": APP_ID,
            "Content-Type": "application/json"}


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
    """Nearby Taco Bell UK stores, nearest first.

    Coordinate order is ``[longitude, latitude]``, and the point object must
    not carry a ``type`` key — same `GeoJSONPointInput` quirk as Pizza Hut.
    """
    occasion = _OCCASION.get(basis)
    if occasion is None:
        raise ValueError(f"taco_bell: unknown basis {basis!r}")
    token = _token()
    return _stores_near(token, lat, lng, occasion, radius_miles, limit)


def _stores_near(token, lat, lng, occasion, radius_miles, limit):
    data = _graphql(_headers(token), _STORE_SEARCH,
                    {"p": {"coordinates": [lng, lat]}, "o": occasion,
                     "d": float(radius_miles), "n": int(limit)})
    edges = ((data.get("storesNearPoint") or {}).get("edges")) or []
    return [e["node"] for e in edges]


def _paged(token: str, query: str, store_number: str,
          path: tuple[str, ...]) -> tuple[list[dict], dict]:
    """Walk a Relay connection using each edge's own cursor (no endCursor,
    same as Pizza Hut)."""
    after, nodes, store = None, [], None
    headers = _headers(token)
    while True:
        data = _graphql(headers, query, {"s": store_number, "after": after})
        node = data.get("storeByNumber")
        if not node:
            raise RuntimeError(f"taco_bell: no store {store_number}")
        store = store or node
        menu = node.get("menuByChannel")
        if not menu:
            raise RuntimeError(f"taco_bell: store {store_number} has no WEB menu")
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


def _names(product_name: str, variant_name: str) -> list[str]:
    """Booklet-style aliases for one priced variant. Additive: the literal
    till name always comes first."""
    base = re.sub(r"\s+", " ", (product_name or "").strip())
    if not base:
        return []
    # Strip trademark marks before any alias-key lookup, or a menu name that
    # only the till decorates with "®" never finds its lookup key.
    clean = re.sub(r"[®™]", "", base).strip()
    names = [base] if clean == base else [base, clean]

    # "Side Nacho Cheese Sauce" -> also "Nacho Cheese Sauce", "Dip Pot -
    # Nacho Cheese Sauce", "Nacho Cheese Sauce Single Portion" — all names
    # the booklet uses for the same 49p-99p side.
    stripped_side = re.sub(r"^side\s+", "", clean, flags=re.I).strip()
    if stripped_side.lower() != clean.lower():
        names.append(stripped_side)
        names.append(f"Dip Pot - {stripped_side}")
        names.append(f"{stripped_side} Single Portion")

    # "3x Chicken Bites" -> also "Chicken Bites (3)", the booklet's spelling
    # for a portion count.
    m = re.match(r"^(\d+)x\s+(.+)$", clean, flags=re.I)
    if m:
        names.append(f"{m.group(2).strip()} ({m.group(1)})")

    # Explicit, calorie-verified aliases (NAME DRIFT #2).
    for root in list(names):
        names.extend(_EXPLICIT_ALIASES.get(root.lower(), []))

    # Reg/Lg/XL variant suffix -> booklet's parenthesised size.
    vparts = [p.strip() for p in (variant_name or "").split()]
    if vparts:
        last = vparts[-1].lower()
        size = _SIZE_SUFFIX.get(last)
        if size:
            for root in list(names):
                names.append(f"{root} {size}")

    # Protein swap is priced once; nutrition lists it once per protein.
    for root in list(names):
        for protein in _PROTEINS:
            names.append(f"{root} - {protein}")

    return names


#: Free dip choices on a "+ Dip" bundle — verified against
#: `data/db/taco_bell.json`, which lists Crispy Chicken Tenders separately
#: per sauce (same portion, different dip calories) at no price difference,
#: since the bundle itself has one price regardless of which dip is picked.
_DIPS = ("Nacho Cheese Sauce", "Cali Ranch Sauce",
        "Creamy Jalapeno Sauce", "Lava Sauce")


#: The booklet's word for the till's "Seasoned Nachos" (the ordinary tortilla
#: chips product, as distinct from the "Seasoned Rice" or a whole nacho dish).
_BUNDLE_WORD_ALIASES = {"seasoned nachos": "nacho chips"}


def _bundle_names(name: str) -> list[str]:
    """Booklet-style aliases for one priced bundle. Additive."""
    clean = re.sub(r"[®™]", "", name or "").strip()
    names = [name] if clean == name else [name, clean]

    m = re.match(r"^(\d+)x\s+(.+?)\s*\+\s*Dip$", clean, flags=re.I)
    if m:
        count, item_name = m.group(1), m.group(2).strip()
        portion = f"{item_name} ({count})"
        names.append(portion)
        for dip in _DIPS:
            names.append(f"{portion} with {dip}")

    # "Seasoned Fries + Nacho Cheese Sauce" / "Large Seasoned Nachos +
    # Nacho Cheese Sauce" -> "Seasoned Fries with Cheese Sauce (Regular)" /
    # "Nacho Chips with Cheese Sauce (Large)".
    m = re.match(r"^(Large\s+)?(.+?)\s*\+\s*Nacho Cheese Sauce$", clean,
                flags=re.I)
    if m:
        size = "Large" if m.group(1) else "Regular"
        base = m.group(2).strip()
        for word, alias in _BUNDLE_WORD_ALIASES.items():
            if base.lower() == word:
                base = alias.title()
        names.append(f"{base} with Cheese Sauce ({size})")

    return names


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 lat: float | None = None, lng: float | None = None,
                 include_deals: bool = True) -> list[dict]:
    """Priced menu for one Taco Bell UK branch.

    Give a `store_id` (the store number, e.g. "094006"), or a `lat`/`lng` to
    use the nearest branch. Item prices are occasion-independent, so `basis`
    only selects which deals are kept; item rows are always "collection".
    """
    if basis not in _OCCASION:
        raise ValueError(f"taco_bell: unknown basis {basis!r}")
    token = _token()

    if store_id is None and lat is not None and lng is not None:
        near = _stores_near(token, lat, lng, _OCCASION[basis], 10.0, 1)
        if not near:
            raise RuntimeError(f"taco_bell: no store near {lat},{lng}")
        store_id = near[0]["store"]["storeNumber"]
    store_number = str(store_id or DEFAULT_STORE_NUMBER)

    products, store = _paged(token, _PRODUCTS, store_number, ("products",))
    label = (store.get("name") or f"Taco Bell #{store_number}").strip()
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
        category = ((product.get("categories") or [{}])[0] or {}).get("name")
        for variant in product.get("variants") or []:
            pence = (variant.get("price") or {}).get("amount")
            if not pence:
                continue          # bundle-component rows price at 0
            names = _names(product.get("name"), variant.get("name"))
            emit(names, pence, category, _kcal(variant.get("nutritionInformation")),
                 _basis_from(variant.get("availability"), "collection"))

    if include_deals:
        bundles, _ = _paged(token, _BUNDLES, store_number, ("bundles",))
        for bundle in bundles:
            pence = (bundle.get("price") or {}).get("amount")
            if not pence:
                continue
            name = bundle.get("name") or ""
            if name.lower().startswith("loyalty reward"):
                continue          # points redemption, not a price a guest can pay
            category = ((bundle.get("categories") or [{}])[0] or {}).get("name")
            deal_basis = _basis_from(bundle.get("availability"), "collection")
            if deal_basis != basis:
                continue
            emit(_bundle_names(name), pence, category or "Deals", None, deal_basis)

    if not out:
        raise RuntimeError(
            f"taco_bell: no priced items for store {store_number} — an empty "
            f"menu means the handshake broke, not that the shop is bare")
    return out


if __name__ == "__main__":  # pragma: no cover
    for row in fetch_prices()[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
