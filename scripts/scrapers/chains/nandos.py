"""Nando's UK — the menu page's Gatsby data payload.

Discovery
---------
nandos.co.uk/food/menu is a Gatsby build. The served HTML is 2.4 MB and
contains the word "protein" exactly zero times, so scraping the page is a dead
end. Gatsby, though, ships the props of every page as JSON next to it:

    https://www.nandos.co.uk/food/menu/page-data/index/page-data.json

That single request carries the whole menu with full nutrition.

Trap: the `page-data` path is a Gatsby build artefact. `/food/menu/page-data/
page-data.json` and `/page-data/food/menu/page-data.json` both 404 — only the
`.../page-data/index/page-data.json` form works, and a future Gatsby version
could move it. If it 404s, load /food/menu and look for the `page-data.json`
reference rather than patching the path by hand.

Shape
-----
Products are nested at unpredictable depths inside the payload, so it is
walked recursively looking for `nutritionalInfo.factsForPortionSizes[0]`.
That object is in **milligrams** for macros: `proteinMg`, `fatMg`,
`totalCarbsMg`, `saltMg`, alongside `energyKcal` / `energyKj`. Forgetting the
mg -> g conversion is the obvious way to get 27,100 g of protein.

183 nutrition blocks resolve to 148 distinct product names (menus repeat
products across sections); deduped on name.
"""
from __future__ import annotations

from ..base import item, session, to_float

CHAIN = "nandos"
SOURCE = "Nando's UK menu page Gatsby data (nutritionalInfo.factsForPortionSizes)"
SOURCE_URL = "https://www.nandos.co.uk/food/menu/page-data/index/page-data.json"


def _mg(v):
    f = to_float(v)
    return round(f / 1000.0, 2) if f is not None else None


def _walk(node, out: list):
    if isinstance(node, dict):
        info = node.get("nutritionalInfo")
        if isinstance(info, dict) and info.get("factsForPortionSizes"):
            out.append((node, info["factsForPortionSizes"][0] or {}))
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def fetch() -> list[dict]:
    payload = session().get(SOURCE_URL, timeout=90).json()
    found: list = []
    _walk(payload, found)

    out: list[dict] = []
    seen: set[str] = set()
    for node, facts in found:
        name = (node.get("name") or node.get("displayName") or "").strip()
        kcal = to_float(facts.get("energyKcal"))
        protein = _mg(facts.get("proteinMg"))
        if not name or not kcal or protein is None:
            continue
        if protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        diets = node.get("diets") or []
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name, serving_desc="per portion",
            kcal=kcal, protein_g=protein,
            carbs_g=_mg(facts.get("totalCarbsMg")), fat_g=_mg(facts.get("fatMg")),
            salt_g=_mg(facts.get("saltMg")),
            vegetarian="VEGETARIAN" in diets or "VEGAN" in diets,
            vegan="VEGAN" in diets,
        ))
    return out
