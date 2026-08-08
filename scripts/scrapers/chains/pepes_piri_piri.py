"""Pepe's Piri Piri — static HTML nutrition cards.

Discovery notes:
  * https://pepes.co.uk/nutrition-allergens-uk/ renders every product
    server-side as a card: <div data-adam="adam" data-title="..."> containing
    `.ntc-item` blocks labelled Kcal, Fat, Saturated Fat, Carbohydrates,
    Sugars, Protein, Salt. No JS needed.
  * The page holds ~162 cards; roughly 129 carry both Kcal and Protein. The
    rest have those cells blank **at source** — they are skipped rather than
    defaulted, since a zero would read as a real measurement.
  * Note the catalogue's guessed domain (pepespiripiri.com) is wrong; the live
    site is pepes.co.uk.

Dietary flag source
--------------------
Each card carries its own `data-category="..."` attribute, and one value,
``pepes-veggie-table``, is Pepe's own "Vegetarian Collection" menu section
(named as such in the page's own allergen-disclaimer prose: "Items from our
Vegetarian Collection menu are cooked and prepared alongside our chicken
and meat products..."). Checked, not assumed: every item in that category
is feta/paneer/veggie-burger -- no meat/fish name anywhere in it. Used as
the sole source of `vegetarian=True`; there is no equivalent vegan category
or column anywhere on the page, so `vegan` is never set here.
"""
from __future__ import annotations

import html
import re

from ..base import item, session, to_float

CHAIN = "pepes_piri_piri"
SOURCE = "brand nutrition page (Pepe's Piri Piri UK)"
SOURCE_URL = "https://pepes.co.uk/nutrition-allergens-uk/"
#: Pepe's own "Vegetarian Collection" menu section -- see "Dietary flag
#: source" above.
_VEGETARIAN_CATEGORY = "pepes-veggie-table"

_CARD = re.compile(r'<div[^>]*data-title="([^"]*)"(.*?)(?=<div[^>]*data-title="|\Z)', re.S)
_ITEM = re.compile(r'class="[^"]*ntc-item[^"]*"[^>]*>(.*?)</div>', re.S)
_CATEGORY_RE = re.compile(r'data-category="([^"]*)"')


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _nutrients(card_html: str) -> dict[str, float]:
    found: dict[str, float] = {}
    text = _text(card_html)
    for label, key in (("Kcal", "kcal"), ("Protein", "protein_g"),
                       ("Fat", "fat_g"), ("Carbohydrates", "carbs_g"),
                       ("Salt", "salt_g")):
        m = re.search(rf"\b{label}\b[^0-9-]{{0,20}}([\d.]+)", text, re.I)
        if m:
            value = to_float(m.group(1))
            if value is not None:
                found[key] = value
    return found


def fetch() -> list[dict]:
    s = session()
    r = s.get(SOURCE_URL, timeout=60)
    r.raise_for_status()

    out: list[dict] = []
    seen: set[str] = set()
    for title, body in _CARD.findall(r.text):
        name = _text(title)
        if not name:
            continue
        nut = _nutrients(body)
        kcal, protein = nut.get("kcal"), nut.get("protein_g")
        if kcal is None or protein is None or kcal <= 0:
            continue
        if protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cat_m = _CATEGORY_RE.search(body)
        vegetarian = True if cat_m and cat_m.group(1) == _VEGETARIAN_CATEGORY else None
        out.append(item(CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
                        serving_desc="per serving",
                        vegetarian=vegetarian, **nut))
    return out
