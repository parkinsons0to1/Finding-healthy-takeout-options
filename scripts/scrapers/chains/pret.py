"""Pret A Manger — Next.js `_next/data` category JSON.

Discovery
---------
pret.co.uk is a Next.js site. Product pages are client-rendered, but every
page that Next.js server-side-props renders also exposes its props as JSON at

    /_next/data/<buildId>/en-GB/products/categories/<slug>.json

`<buildId>` is baked into the HTML at build time and CHANGES ON EVERY DEPLOY,
so it must be read from the homepage rather than hard-coded — that is the one
trap here. It appears both in `__NEXT_DATA__` and in the `_buildManifest.js`
script src, and we scrape the latter because it is a stable, simple pattern.

Shape
-----
`pageProps.selectedCategory` is a tree: `.products[]` plus `.subcategories[]`
which recurse the same way, so products must be collected recursively (most
of them live one or two levels down, not at the top).

Each product carries `nutritionals`: a list of rows, each row a list of
`{"name": ..., "value": ...}` cells with names `nutrient` / `per100g` /
`perServing`. We take `perServing` — Pret publishes both, and mixing bases
would halve or double everything. Nutrient labels are e.g. "Energy (Kcal)"
and "Protein (g)"; matching is case-insensitive prefix matching because the
capitalisation of "Kcal" is not consistent across the catalogue.

Allergens, `suitableForVegans` / `suitableForVegetarians` and `averageWeight`
come free in the same payload.

Politeness: 8 requests total (one per category), not one per product.
"""
from __future__ import annotations

import re

from ..base import item, session, to_float

CHAIN = "pret"
SOURCE = "Pret A Manger website (_next/data category JSON)"
HOME = "https://www.pret.co.uk/"

#: Category slugs linked from the homepage nav.
CATEGORIES = (
    "breakfast",
    "cold-drinks",
    "fruit-and-fruit-pots",
    "hot-drinks",
    "hot-food",
    "sandwiches-baguettes-wraps-and-flatbreads",
    "super-plates-salads-and-protein-pots",
    "sweet-and-savoury-snacks",
)

_BUILD_ID = re.compile(r"/_next/static/([A-Za-z0-9_\-]{8,})/_buildManifest\.js")


def _build_id(s) -> str | None:
    """Read the current Next.js build id off the homepage.

    Hard-coding this is the single most likely way for this adapter to rot:
    the id changes on every deploy and stale ids 404.
    """
    r = s.get(HOME, timeout=60)
    if r.status_code != 200:
        return None
    m = _BUILD_ID.search(r.text)
    return m.group(1) if m else None


def _nutrient(product: dict, prefix: str) -> float | None:
    """Per-serving value of the first nutrient whose label starts with `prefix`."""
    for row in product.get("nutritionals") or []:
        cells = {c.get("name"): c.get("value") for c in row if isinstance(c, dict)}
        label = str(cells.get("nutrient") or "").lower()
        if label.startswith(prefix):
            return to_float(cells.get("perServing"))
    return None


def _walk(node: dict, out: list[dict]) -> None:
    """Collect products from a category tree (products nest in subcategories)."""
    for p in node.get("products") or []:
        out.append(p)
    for sub in node.get("subcategories") or []:
        _walk(sub, out)


def fetch() -> list[dict]:
    s = session()
    build = _build_id(s)
    if not build:
        return []

    rows: list[dict] = []
    seen: set[str] = set()
    for slug in CATEGORIES:
        url = (f"https://www.pret.co.uk/_next/data/{build}"
               f"/en-GB/products/categories/{slug}.json")
        try:
            r = s.get(url, timeout=60)
            if r.status_code != 200:
                continue
            cat = r.json()["pageProps"]["selectedCategory"]
        except Exception:
            continue

        products: list[dict] = []
        _walk(cat, products)
        for p in products:
            name = (p.get("name") or "").strip()
            kcal = _nutrient(p, "energy (kcal")
            protein = _nutrient(p, "protein")
            if not name or kcal is None or protein is None:
                continue
            if kcal <= 0 or protein * 4 > kcal * 1.15:
                continue                      # misread / implausible row
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(item(
                CHAIN, name, SOURCE, url,
                item_id=p.get("sku") or p.get("id") or name,
                category=cat.get("name") or slug,
                serving_desc="per serving",
                kcal=kcal, protein_g=protein,
                carbs_g=_nutrient(p, "carbohydrate"),
                fat_g=_nutrient(p, "fat"),
                salt_g=_nutrient(p, "salt"),
                vegetarian=p.get("suitableForVegetarians"),
                vegan=p.get("suitableForVegans"),
                allergens=[a.get("label") for a in (p.get("allergens") or [])
                           if isinstance(a, dict)],
            ))
    return rows
