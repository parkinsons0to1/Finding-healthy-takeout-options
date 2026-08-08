"""PAUL UK — REAL prices from PAUL's own Magento 2 GraphQL storefront.

WHICH PLATFORM
    `www.paul-uk.com` runs Magento 2 (Hyvä theme — visible in the page's own
    JS bundle comments and `mage-init` data attributes) with `/order-online`
    as its click-and-collect/delivery storefront. Magento 2's GraphQL
    endpoint is public by design (it powers the storefront's own PDP/PLP
    fetches) — `POST https://www.paul-uk.com/graphql` answers plain
    `requests` with no auth, no token, no TLS-impersonation needed.

Handshake
---------
One unauthenticated POST, no discovery step needed:

    ``POST /graphql`` with a `categoryList(filters: {ids: {eq: "<id>"}})
    { products(pageSize: 200) { items { name sku price_range {
    minimum_price { regular_price { value } } } } } } }`` query.

    PAUL's whole orderable catalogue is a single flat pool of 88 products
    (verified: querying every leaf/parent category id in the site's own
    nav tree — Cakes, Platters, Breakfast, Lunch, Catering's eight
    sub-categories, Party/Picnic/Birthday Food, etc — and de-duplicating by
    `sku` converges on exactly 88 unique products no matter how many
    category ids are queried; `_CATEGORY_IDS` below is deliberately a
    superset for that reason, not a precise map). This module walks that id
    list and unions the results rather than depending on one catch-all
    category, because "Order Online" (id 353, product_count 88) undercounts
    products that are catering/party-only and not tagged under it.

TRAP — every product name comes back with a literal ``&quot;`` instead of
       a real ``"`` character
    Magento's GraphQL layer does not HTML-decode its own stored product
    names — `Charlotte Framboise Cake 7&quot;` is meant to read `7"`. Left
    as-is this breaks the nutrition-table join on every inch-sized cake
    (`data/db/paul.json` spells them with a real `"`). Decoded with
    `html.unescape` before emitting.

NAME DRIFT — `data/db/paul.json` (nutrition) vs. the Magento catalogue
    `_ALIASES` pairs 9 nutrition rows to the Magento product with the same
    dish, verified by there being exactly one plausible same-dish candidate
    each (no kcal field is exposed by this GraphQL schema to cross-check
    against, unlike the Just Eat-backed adapters in this directory) — e.g.
    nutrition "Mille Feuille Cake" is the catalogue's single-word
    "Millefeuille Cake", nutrition "Pain de Campagne 400gr" is the
    catalogue's "Pain De Campagne 400G" (unit-suffix spelling only).

NOT ALIASED, HONESTLY — no confident single candidate
    "Decorated Fraisier Cake" (the catalogue's plain "Fraisier Cake" is
    already claimed by the nutrition table's own undecorated "Fraisier
    Cake" row), "Pastel De Nata Platter x12" (catalogue only lists x15, a
    genuinely different portion count, not aliased), "Strawberry Cheesecake
    Delivery in London" and "French Apple Tart - Tarte Normande" (no
    catalogue product name resembles either closely enough to be confident)
    are left unmatched rather than guessed.

PRICE BASIS — collection
    PAUL's own site labels this storefront's checkout "Click & Collect /
    Delivery" per-store; Magento prices once per SKU with no visible
    channel split, matching this project's convention for a single-price
    catalogue (`gdk.py`, `wimpy.py`).

STORE — none; this is a nationwide online-shop price, not a branch till
    Like `gails.py`, PAUL's own storefront does not ask which café you're
    near before pricing a product — see that module's STORE section for
    why a specific-branch label would misrepresent this.
"""
from __future__ import annotations

import html
import re

from ..base import session

CHAIN = "paul"

GRAPHQL = "https://www.paul-uk.com/graphql"

#: Every category id in the site's own nav tree with a nonzero product
#: count, deliberately overlapping — de-duplicated by SKU at fetch time.
#: See "WHICH PLATFORM" for why a superset is used instead of one id.
_CATEGORY_IDS = [313, 183, 210, 356, 134, 189, 192, 305, 207, 136, 146, 138,
                 39, 77, 78, 88, 93, 51, 52, 159, 293, 300, 296, 297, 353]

_QUERY = """
query {{
  categoryList(filters: {{ids: {{eq: "{cid}"}}}}) {{
    id
    name
    products(pageSize: 200, currentPage: 1) {{
      items {{
        name
        sku
        price_range {{ minimum_price {{ regular_price {{ value currency }} }} }}
      }}
    }}
  }}
}}
"""

#: Catalogue product name (lowercased) -> `data/db/paul.json` nutrition-row
#: name for the SAME dish. See the module docstring's NAME DRIFT section for
#: how each was verified.
_ALIASES = {
    "charlotte fraise cake 7\"": "Charlotte Cake",
    'craquant 7" - 14" for 6-8 to 25-30': "Craquant Cake",
    "vegan puy lentil & artichoke salad platter": "Lentil & Artichoke Salad Platter",
    "millefeuille cake": "Mille Feuille Cake",
    "mini meat sandwich platter x24": "Meat Sandwich Platter (24 Pieces)",
    "pain au chocolate & croissant platter":
        "Breakfast Platter - Pain au Chocolat & Croissant",
    "pain de campagne 400g": "Pain de Campagne 400gr",
    "pain multigrain 400g": "Multigrain Bread Loaf 400gr",
    "pain multigrain 800g": "Large Multigrain Bread 800gr",
}


def _fetch_category(s, cid: int) -> dict | None:
    r = s.post(GRAPHQL, json={"query": _QUERY.format(cid=cid)}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"paul: HTTP {r.status_code} for category {cid}")
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"paul: GraphQL error for category {cid}: "
                           f"{data['errors'][0].get('message')}")
    cl = (data.get("data") or {}).get("categoryList") or []
    return cl[0] if cl else None


def fetch_prices() -> list[dict]:
    """PAUL UK's priced catalogue, straight off paul-uk.com's own Magento
    GraphQL. No store parameter — see the module docstring's STORE section.
    """
    s = session()
    s.headers["Content-Type"] = "application/json"

    by_sku: dict[str, tuple[str, float]] = {}
    for cid in _CATEGORY_IDS:
        cat = _fetch_category(s, cid)
        if not cat:
            continue
        for p in (cat.get("products") or {}).get("items") or []:
            sku = p.get("sku")
            price = ((p.get("price_range") or {}).get("minimum_price") or {}) \
                .get("regular_price", {}).get("value")
            name = p.get("name")
            if not sku or price is None or not name:
                continue
            by_sku.setdefault(sku, (name, float(price)))

    if not by_sku:
        raise RuntimeError("paul: no products returned from any category — "
                           "the GraphQL handshake broke, not that the shop "
                           "is bare")

    out: list[dict] = []
    seen: set[str] = set()
    for name, price in by_sku.values():
        clean = html.unescape(re.sub(r"\s+", " ", name)).strip()
        if not clean:
            continue
        names = [clean]
        alias = _ALIASES.get(clean.lower())
        if alias:
            names.append(alias)

        for row_name in names:
            key = row_name.lower()
            if not row_name or key in seen:
                continue
            seen.add(key)
            out.append({
                "name": row_name,
                "price_gbp": round(price, 2),
                "basis": "collection",
                "store": "PAUL online shop (nationwide catalogue price — "
                        "no per-branch pricing exists on this platform)",
                "category": None,
            })

    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} priced rows")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  {row['name']}")
