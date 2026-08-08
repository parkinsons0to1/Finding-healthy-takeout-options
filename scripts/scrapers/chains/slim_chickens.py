"""Slim Chickens UK — schema.org Menu embedded as JSON-LD.

Discovery notes:
  * slimchickens.co.uk's "Dietary Information" footer link goes to
    menus.tenkites.com/brg/slimchickensall, which is only a **location
    picker**. The actual core menu lives at /brg/slimscore?sitecode=SLM.
  * That page embeds one <script type="application/ld+json"> schema.org Menu
    covering the whole estate, each MenuItem carrying NutritionInformation
    (calories, proteinContent, fatContent, carbohydrateContent).
  * Tenkites hosts several UK chains but exposes macros differently per
    brand — Wagamama uses data-nutrient attributes, Frankie & Benny's uses
    JSON-LD, and some templates carry empty NutritionInformation objects. So
    "it's Tenkites" does not imply "parse it this way".
  * Values like "43 g" need the unit stripped; calories arrive as "303 kcal".

Dietary flag source
--------------------
Some (not all) `MenuItem` nodes carry a schema.org `suitableForDiet` string,
e.g. `"http://schema.org/VegetarianDiet"` — an explicit structured field, not
inferred from the name. 214 occurrences in the live document, all
`VegetarianDiet`; no `VeganDiet` value was found anywhere in the page (search
for both "VeganDiet" case-sensitive and lower-cased came back empty), so
`vegan` is left unset rather than assumed False for everything (schema.org
lets a menu mark vegetarian without ever using the vegan term, and Slim
Chickens genuinely may have zero vegan items — a fried-chicken menu — but
that's not something this field can positively confirm either way, so it's
left unset rather than guessed).
"""
from __future__ import annotations

import json
import re

from ..base import item, session, to_float

CHAIN = "slim_chickens"
SOURCE = "brand menu JSON-LD via Tenkites (Slim Chickens UK)"
SOURCE_URL = "https://menus.tenkites.com/brg/slimscore?sitecode=SLM"

_LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


def _number(value) -> float | None:
    if value is None:
        return None
    m = re.search(r"[\d.]+", str(value))
    return to_float(m.group(0)) if m else None


def _walk(node, out: list[dict]) -> None:
    """schema.org Menus nest sections arbitrarily deep, so recurse."""
    if isinstance(node, list):
        for child in node:
            _walk(child, out)
        return
    if not isinstance(node, dict):
        return
    if node.get("@type") == "MenuItem" or "nutrition" in node:
        out.append(node)
    for value in node.values():
        if isinstance(value, (dict, list)):
            _walk(value, out)


def fetch() -> list[dict]:
    s = session()
    r = s.get(SOURCE_URL, timeout=60)
    r.raise_for_status()

    nodes: list[dict] = []
    for block in _LD.findall(r.text):
        try:
            _walk(json.loads(block), nodes)
        except Exception:
            continue

    out: list[dict] = []
    seen: set[str] = set()
    for node in nodes:
        name = (node.get("name") or "").strip()
        nutrition = node.get("nutrition") or {}
        kcal = _number(nutrition.get("calories"))
        protein = _number(nutrition.get("proteinContent"))
        if not name or kcal is None or protein is None or kcal <= 0:
            continue
        if protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        diet = node.get("suitableForDiet") or ""
        vegetarian = True if diet.endswith("VegetarianDiet") else None
        vegan = True if diet.endswith("VeganDiet") else None
        if vegan:
            vegetarian = True   # vegan implies vegetarian
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
            serving_desc="per serving", kcal=kcal, protein_g=protein,
            fat_g=_number(nutrition.get("fatContent")),
            carbs_g=_number(nutrition.get("carbohydrateContent")),
            vegetarian=vegetarian, vegan=vegan))
    return out
