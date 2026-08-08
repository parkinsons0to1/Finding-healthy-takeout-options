"""LEON — per-portion macros from the Sanity CMS payload in __NEXT_DATA__.

Discovery
---------
leon.co/allergens talks about nutrition and links a Google-Drive "Foodie Fact
Sheet", which is a dead end for automation. The real data is on the menu page:

    https://leon.co/menu/

leon.co is a Next.js site backed by Sanity. The server-rendered
``<script id="__NEXT_DATA__" type="application/json">`` blob contains every
menu item, each with a ``nutritionInfo`` array::

    "nutritionInfo":[
      {"name":"Energy","unit":"Kcal per portion","amount":565},
      {"name":"Protein","unit":"grams per portion","amount":15},
      {"name":"Carbohydrate","unit":"","amount":63},
      {"name":"Carbs of which sugar","unit":"grams per portion","amount":4.7},
      {"name":"Fat",...},{"name":"Saturated fat",...},
      {"name":"Mono-unsaturated fat",...},{"name":"Salt",...},{"name":"Fibre",...}]

No API key, no JS execution, one request for the whole menu (Breakfast /
All Day / Drinks / Kids all appear on this single page).

Traps
-----
* The energy entry is named "Energy", not "kcal" — the unit string carries the
  "Kcal per portion" part. Match on the entry ``name``, and read ``amount``.
* Nutrient entries are matched by exact normalized name. "Carbohydrate" and
  "Carbs of which sugar" both begin with "carb", so a prefix match would let
  sugars overwrite carbohydrate depending on order.
* A handful of items legitimately state 0 kcal (still water and similar). They
  are dropped by the gate below since a 0-kcal row carries no usable macro
  ratio, so this adapter reports slightly fewer items than the page lists.

Dietary flag source
--------------------
The SAME node carries a ``dietary`` array (siblings: ``allergens``, a
separate 14-allergen tag list) -- structured Sanity references, each with a
``slug``, curated by the brand: ``{'title': 'Vegan', 'slug': 'vegan', ...}``.
The full vocabulary seen across the whole menu is ``{vegetarian, vegan,
gluten-free, high-in-protein, source-of-protein, good-for-your-gut,
plant-variety}`` -- ``vegetarian`` and ``vegan`` are used here, the rest
aren't dietary-safety claims.

Some items carry ``vegan`` but not ``vegetarian`` (e.g. "Hash Browns"; other
items, like "Charred Broccoli with Preserved Lemon", carry both) -- since
every vegan dish is by definition vegetarian too, ``vegetarian`` is set
True whenever EITHER tag is present, not just when LEON's own tagging
happens to include both.

A dish with no ``vegetarian``/``vegan`` tag is not necessarily non-veg (the
tagging isn't proven exhaustive -- e.g. plenty of drinks carry no ``dietary``
array at all), so absence of a tag is left unset UNLESS the name itself
contains an unambiguous meat/fish word (chicken, bacon, sausage, fish,
salmon, chorizo -- checked against every word actually appearing in this
menu's item names), in which case ``vegetarian=False`` is recorded directly
(the safe direction -- see the project's non-negotiable rule).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected, item, session

_MEAT_WORD_RE = re.compile(
    r"\b(chicken|bacon|sausage|fish|salmon|chorizo)\b", re.I)

CHAIN = "leon"
SOURCE = "brand site (LEON menu, Sanity CMS payload)"
SOURCE_URL = "https://leon.co/menu/"

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

#: Exact nutritionInfo entry name (lower-cased) -> normalized field.
_FIELDS = {
    "protein": "protein_g",
    "carbohydrate": "carbs_g",
    "fat": "fat_g",
    "salt": "salt_g",
    "fibre": "fibre_g",
    "carbs of which sugar": "sugars_g",
    "saturated fat": "sat_g",
}


def _get(url: str) -> str | None:
    s = session()
    try:
        r = s.get(url, timeout=90)
        if r.status_code == 200 and r.content:
            return r.content.decode(r.encoding or "utf-8", errors="replace")
    except Exception:
        pass
    pr = fetch_protected(url, timeout=120)
    if pr is not None and pr.content:
        return pr.content.decode("utf-8", errors="replace")
    return None


def _collect(node, found: list[dict]) -> None:
    """Walk the Sanity payload for any node carrying nutritionInfo."""
    if isinstance(node, dict):
        if node.get("nutritionInfo") and node.get("name"):
            found.append(node)
        for value in node.values():
            _collect(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect(value, found)


def _macros(entries) -> dict:
    out: dict = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().lower()
        amount = entry.get("amount")
        if amount is None:
            continue
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            continue
        if name == "energy":
            out["kcal"] = amount
        elif name in _FIELDS:
            out[_FIELDS[name]] = amount
    return out


def fetch() -> list[dict]:
    raw = _get(SOURCE_URL)
    if not raw:
        return []
    blob = _NEXT_DATA.search(raw)
    if not blob:
        return []
    try:
        payload = json.loads(blob.group(1))
    except Exception:
        return []

    nodes: list[dict] = []
    _collect(payload, nodes)

    out: list[dict] = []
    seen: set[str] = set()
    for node in nodes:
        name = str(node.get("name") or "").strip()
        macros = _macros(node.get("nutritionInfo"))
        kcal = macros.get("kcal")
        protein = macros.get("protein_g")
        # Plausibility gate: reject rows missing a name, kcal or protein, and
        # rows where protein alone would exceed the stated calories.
        if not name or not kcal or protein is None:
            continue
        if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        menu = node.get("menuType") or {}
        submenu = node.get("submenuType") or {}
        parts = [str(menu.get("name") or "").strip(), str(submenu.get("name") or "").strip()]
        category = " / ".join(p for p in parts if p) or None

        dietary_slugs = {str(d.get("slug") or "") for d in (node.get("dietary") or [])
                         if isinstance(d, dict)}
        vegan = True if "vegan" in dietary_slugs else None
        if "vegetarian" in dietary_slugs or "vegan" in dietary_slugs:
            vegetarian = True
        elif _MEAT_WORD_RE.search(name):
            vegetarian = False
        else:
            vegetarian = None

        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name,
            category=category,
            serving_desc="per portion",
            kcal=kcal,
            protein_g=protein,
            carbs_g=macros.get("carbs_g"),
            fat_g=macros.get("fat_g"),
            salt_g=macros.get("salt_g"),
            vegetarian=vegetarian,
            vegan=vegan,
        ))
    return out
