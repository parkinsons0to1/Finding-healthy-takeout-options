"""Toby Carvery (Mitchells & Butlers) — per-portion macros from the M&B guide.

Discovery
---------
tobycarvery.co.uk publishes menu PDFs with kcal only, and both
``/nutrition`` and ``/nutritional-information`` 404. The macros are on the
Mitchells & Butlers group host:

    https://allergens.mbplc.io/AllergenGuideTobyEstate.html

The trap: that page is *titled* "Allergen Guide" and sits on a host named
``allergens.mbplc.io``, but every dish carries a full per-portion nutrition
table (kJ/kcal, fat, saturates, carbohydrate, sugars, protein, salt). There is
no separate M&B nutrition PDF to go looking for. Format details and the
column-mapping rationale are in ``_mbplc.py``; the same portal serves Harvester
and Miller & Carter.

Static HTML, no JS and no bot protection.

Note on dropped rows: the Toby guide contains placeholder rows that state all
zeros (e.g. "Slice of Toast ... refer to your choice of white or wholemeal"),
which are cross-references rather than dishes. The gate below drops them via
the ``kcal <= 0`` check.
"""
from __future__ import annotations

from ..base import item
from . import _mbplc

CHAIN = "toby_carvery"
SOURCE = "brand site (Mitchells & Butlers allergen & nutrition guide)"
SOURCE_URL = "https://allergens.mbplc.io/AllergenGuideTobyEstate.html"


def fetch() -> list[dict]:
    raw = _mbplc.fetch_guide(SOURCE_URL)
    if not raw:
        return []

    out: list[dict] = []
    for rec in _mbplc.parse_guide(raw):
        kcal = rec.get("kcal")
        protein = rec.get("protein_g")
        name = rec.get("name")
        # Plausibility gate — see module docstring. A row without a name, kcal
        # or protein, an all-zero placeholder row, or one whose protein alone
        # would exceed the stated calories, is never emitted.
        if not name or not kcal or protein is None:
            continue
        if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
            continue
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name,
            category=rec.get("category"),
            serving_desc="per portion",
            kcal=kcal,
            protein_g=protein,
            carbs_g=rec.get("carbs_g"),
            fat_g=rec.get("fat_g"),
            salt_g=rec.get("salt_g"),
            vegetarian=rec.get("vegetarian"),
            vegan=rec.get("vegan"),
        ))
    return out
