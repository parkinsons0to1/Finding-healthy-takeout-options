"""Miller & Carter (Mitchells & Butlers) — per-portion macros from the M&B guide.

Discovery
---------
Macros come from the Mitchells & Butlers group host, not millerandcarter.co.uk:

    https://allergens.mbplc.io/AllergenGuideMillerandCarterEstate.html

The trap: the page is *titled* "Allergen Guide" and the host is called
``allergens.mbplc.io``, yet every dish carries a full per-portion nutrition
table (kJ/kcal, fat, saturates, carbohydrate, sugars, protein, salt). No
separate M&B nutrition PDF exists to hunt for. See ``_mbplc.py`` for the
format; Harvester and Toby Carvery come off the same portal.

Static HTML, no JS and no bot protection.

Rows deliberately dropped
-------------------------
This brand's guide includes menu "swap" rows — e.g. "Burger Swap" states
28 kcal against 35 g protein, with negative fat/carbs/sugars/salt. Those are
*deltas* for substituting one component for another, not dishes, and the
figures are meaningless on their own. The plausibility gate rejects them
(35 * 4 = 140 > 28 * 1.15), which is exactly what should happen. If a future
change makes this adapter's count jump by a handful of items, check whether
swap rows started passing the gate before trusting them.
"""
from __future__ import annotations

from ..base import fetch_protected, item, session
from . import _mbplc

CHAIN = "miller_carter"
SOURCE = "brand site (Mitchells & Butlers allergen & nutrition guide)"
SOURCE_URL = "https://allergens.mbplc.io/AllergenGuideMillerandCarterEstate.html"


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
        # Plausibility gate — drops the negative-delta "swap" rows described
        # in the module docstring, plus anything missing name/kcal/protein.
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
