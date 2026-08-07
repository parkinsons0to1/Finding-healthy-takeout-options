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
"""
from __future__ import annotations

import html
import re

from ..base import item, session, to_float

CHAIN = "pepes_piri_piri"
SOURCE = "brand nutrition page (Pepe's Piri Piri UK)"
SOURCE_URL = "https://pepes.co.uk/nutrition-allergens-uk/"

_CARD = re.compile(r'<div[^>]*data-title="([^"]*)"(.*?)(?=<div[^>]*data-title="|\Z)', re.S)
_ITEM = re.compile(r'class="[^"]*ntc-item[^"]*"[^>]*>(.*?)</div>', re.S)


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
        out.append(item(CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
                        serving_desc="per serving", **nut))
    return out
