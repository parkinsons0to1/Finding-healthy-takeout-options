"""GAIL's Bakery — `window.allergenProducts`, a theme-global JS array.

Discovery
---------
gailsbread.co.uk 301-redirects to gails.com, which is Shopify. Two dead ends
worth recording so nobody repeats them:

* `https://gails.com/products.json?limit=250` returns the catalogue but has
  NO nutrition — `body_html` is marketing copy only.
* `https://gailsbread.co.uk/GAILs_Nutrition_&_Allergen_Info.pdf` looks like a
  nutrition PDF but serves an HTML page (the SPA shell), not a PDF.

The real data is a Shopify *theme* global: every page rendered by the theme
inlines `window.allergenProducts = [ ... ]`, an array of ~885 EPOS rows keyed
by PLU. Because it is a theme global and not page-specific, ANY themed
gails.com URL works; a product page is used here as a stable anchor.

Row shape
---------
    {"PLU": 1239, "PLUDescription": "Salmon fishcakes", "InUse": false,
     "MajorGroupName": "Salads", "SalesGroupName": "Medium Salad",
     "AllergenId": "183,184,...", "Energy (kcal)": null, "Protein (g)": null,
     "Total Fat (g)": ..., "Carbohydrate": ..., "Salt (mg)": ..., ...}

Traps
-----
* Many rows have null macros — roughly 469 of 885 carry both kcal and protein.
* `InUse` marks the live menu. Delisted rows survive in the array, often with
  a "DNU" (do not use) name prefix. We keep only `InUse` rows so the pipeline
  does not surface discontinued products; drop that filter to get ~469.
* Extracting the array needs BRACE MATCHING. A non-greedy `\\[.*?\\]` regex
  stops at the first `]` inside the data and yields nothing parseable.
* Note `Salt (mg)`, not grams — converted below.

Politeness: one request for the whole catalogue.
"""
from __future__ import annotations

import json

from ..base import item, session, to_float

CHAIN = "gails"
SOURCE = "GAIL's Bakery website (window.allergenProducts inline JSON)"
SOURCE_URL = "https://gails.com/products/gails-sourdough-650g"

_MARKER = "window.allergenProducts"


def _extract_array(html: str) -> list[dict]:
    """Pull the brace-matched JSON array out of the inline script."""
    start = html.find(_MARKER)
    if start < 0:
        return []
    try:
        open_at = html.index("[", start)
    except ValueError:
        return []
    depth = 0
    for i in range(open_at, len(html)):
        c = html[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[open_at:i + 1])
                except json.JSONDecodeError:
                    return []
    return []


def fetch(include_delisted: bool = False) -> list[dict]:
    s = session()
    r = s.get(SOURCE_URL, timeout=90)
    if r.status_code != 200:
        return []

    rows: list[dict] = []
    seen: set[str] = set()
    for rec in _extract_array(r.text):
        if not include_delisted and not rec.get("InUse"):
            continue
        name = (rec.get("PLUDescription") or "").strip()
        kcal = to_float(rec.get("Energy (kcal)"))
        protein = to_float(rec.get("Protein (g)"))
        if not name or kcal is None or protein is None:
            continue
        if kcal <= 0 or protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        salt_mg = to_float(rec.get("Salt (mg)"))
        rows.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=str(rec.get("PLU") or name),
            category=rec.get("MajorGroupName") or rec.get("SalesGroupName"),
            serving_desc="per item",
            kcal=kcal, protein_g=protein,
            carbs_g=to_float(rec.get("Carbohydrate")),
            fat_g=to_float(rec.get("Total Fat (g)")),
            salt_g=round(salt_mg / 1000, 3) if salt_mg is not None else None,
        ))
    return rows
