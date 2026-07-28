"""Greggs — fully open product API (no auth).

Discovery notes (2026-07-28):
  * https://production-digital.greggs.co.uk/api/v1.0/articles/masters
    -> ~4900 articles with full nutritionalValues, ingredients, veg flags,
    and Greggs' own isSourceOfProtein / isTaggedForProtein tags.
  * /api/v1.0/shops -> every shop with coordinates and opening times.
  * Catalog includes unpublished/internal rows ("Do Not Use ...", premixes);
    filter on isPublished and not isHiddenInMenu.
"""
from __future__ import annotations

from .base import item, session, to_float

BASE = "https://production-digital.greggs.co.uk/api/v1.0"
ARTICLES_URL = f"{BASE}/articles/masters"

CHAIN = "greggs"
SOURCE = "live-scrape Greggs production-digital API"

_NUT_MAP = {"Calories": "kcal", "Protein": "protein_g",
            "Carbohydrates": "carbs_g", "Fat": "fat_g", "Salt": "salt_g"}


def fetch() -> list[dict]:
    s = session()
    arts = s.get(ARTICLES_URL, timeout=60).json()
    out = []
    for a in arts:
        if not a.get("isPublished") or a.get("isHiddenInMenu"):
            continue
        if not a.get("nutritionalValues"):
            continue
        name = (a.get("articleName") or "").strip()
        if name.lower().startswith("do not use"):
            continue
        nut = {}
        for nv in a["nutritionalValues"]:
            key = _NUT_MAP.get(nv.get("name"))
            if key:
                nut[key] = to_float(nv.get("value"))
        flags = []
        if a.get("isSourceOfProtein") or a.get("isTaggedForProtein"):
            flags.append("greggs-protein-tag")
        out.append(item(
            CHAIN, name, SOURCE, ARTICLES_URL,
            item_id=a.get("articleCode"), category=str(a.get("articleCategoryId")),
            serving_desc=a.get("articleSize"),
            vegetarian=None, vegan=None,   # Greggs flags vegan in the name, not a field
            quality_flags=flags, **nut,
        ))
    return out
