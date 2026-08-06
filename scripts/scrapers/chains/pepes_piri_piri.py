"""Pepe's Piri Piri UK — server-rendered nutrition cards on their own site.

Discovery
---------
https://pepes.co.uk/nutrition-allergens-uk/ is plain WordPress HTML: no JS, no
API, no PDF. Every product is a card

    <div data-adam="adam" data-title="1/4 Chicken"
         data-allergens="Wheat" data-category="pepes-grilled-collection" ...>

whose `.ntc-item` children are labelled Kcal, Fat (g), Saturated Fat (g),
Carbohydrates (g), Sugars (g), Protein (g), Salt (g) and sometimes
"Add Flavour (ml)". The filter UI on the page is client-side only, so the full
catalogue is in the initial response.

Traps
-----
* There is a separate Ireland page (/nutrition-allergens-ireland/) with a
  different menu — don't mix them.
* Labels carry a zero-width joiner before the value (`Protein (g)<br>\\u200d`),
  so a naive `>Protein \\(g\\)</strong>` match fails; match up to `</strong>`.
* Names are HTML entities at source ("Fountain &#8211; LRG"); unescaped here.
* 162 cards exist, 129 have both Kcal and Protein filled in — the rest have
  blank cells at source and are dropped rather than zero-filled.
"""
from __future__ import annotations

import html
import re

from ..base import fetch_protected, item, session, to_float

CHAIN = "pepes_piri_piri"
SOURCE = "Pepe's Piri Piri UK nutrition & allergens page"
SOURCE_URL = "https://pepes.co.uk/nutrition-allergens-uk/"

_CARD = re.compile(r'<div data-adam="adam"(.*?)<div class="nutrition-table-footer">', re.S)
_TITLE = re.compile(r'data-title="([^"]*)"')
_CATEGORY = re.compile(r'data-category="([^"]*)"')
_KCAL = re.compile(r">Kcal</strong><br>\s*([\d.]+)")


def _macro(card: str, label: str):
    m = re.search(r">%s<br>[^<]*</strong>\s*([\d.]+)" % re.escape(label), card)
    return to_float(m.group(1)) if m else None


def fetch() -> list[dict]:
    r = session().get(SOURCE_URL, timeout=90)
    body = r.text if r.status_code == 200 else None
    if body is None:
        pr = fetch_protected(SOURCE_URL)
        body = pr.text if pr is not None else ""

    out: list[dict] = []
    seen: set[str] = set()
    for card in _CARD.findall(body):
        tm, km = _TITLE.search(card), _KCAL.search(card)
        if not (tm and km):
            continue
        name = html.unescape(tm.group(1)).strip()
        kcal = to_float(km.group(1))
        protein = _macro(card, "Protein (g)")
        if not name or not kcal or protein is None:
            continue
        if protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cm = _CATEGORY.search(card)
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name, category=cm.group(1) if cm else None,
            serving_desc="per serving", kcal=kcal, protein_g=protein,
            fat_g=_macro(card, "Fat (g)"),
            carbs_g=_macro(card, "Carbohydrates (g)"),
            salt_g=_macro(card, "Salt (g)"),
        ))
    return out
