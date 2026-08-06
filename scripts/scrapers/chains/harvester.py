"""Harvester (Mitchells & Butlers) — per-portion macros from the M&B brand guide.

Discovery
---------
Searching for "Harvester nutrition PDF" only turns up menu PDFs on
harvester.co.uk that print kcal alone. The macros live on the Mitchells &
Butlers group host instead:

    https://allergens.mbplc.io/AllergenGuideHarvesterEstate.html

That page is *titled* "Allergen Guide", which is the trap — it carries a full
per-portion nutrition table for every dish (kJ/kcal, fat, saturates,
carbohydrate, sugars, protein, salt). See ``_mbplc.py`` for the format notes;
the same host serves Toby Carvery and Miller & Carter from sibling URLs, so
one group portal covers three of our chains.

Static HTML, no JS and no bot protection — a plain ``requests`` GET works.
"""
from __future__ import annotations

from ..base import fetch_protected, item, session
from . import _mbplc

CHAIN = "harvester"
SOURCE = "brand site (Mitchells & Butlers allergen & nutrition guide)"
SOURCE_URL = "https://allergens.mbplc.io/AllergenGuideHarvesterEstate.html"


def _fetch_html(url: str) -> str | None:
    s = session()
    try:
        r = s.get(url, timeout=90)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    pr = fetch_protected(url, timeout=120)
    return pr.text if pr is not None else None


def fetch() -> list[dict]:
    raw = _fetch_html(SOURCE_URL)
    if not raw:
        return []

    out: list[dict] = []
    for rec in _mbplc.parse_guide(raw):
        kcal = rec.get("kcal")
        protein = rec.get("protein_g")
        name = rec.get("name")
        # Plausibility gate: no name/kcal/protein, or protein-derived calories
        # exceeding the stated calories, means the row was misread or is not a
        # dish (M&B "swap" rows carry negative deltas). Never emit it.
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
