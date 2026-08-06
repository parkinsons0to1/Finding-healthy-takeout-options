"""Taco Bell UK — brand menu served through a Nutritionix-hosted table.

Discovery notes:
  * tacobell.co.uk/nutrition-information/ carries no macros itself. Its only
    content is an <iframe> pointing at Nutritionix, so probing the brand
    domain finds a page that mentions nutrition and contains no numbers —
    another instance of "the obvious page isn't the source".
  * The iframe URL serves the whole brand menu as a **static HTML table**, no
    JS required. Columns are positional:
        c0 name, c1 energy kJ, c2 energy kcal, c3 fat, c4 saturates,
        c5 carbohydrate, c6 sugars, c7 fibre, c8 protein, c9 salt
    Note kcal is the *second* energy column — taking the first would report
    kilojoules as calories and quadruple every item's energy.
  * Values are per serving.
"""
from __future__ import annotations

import html
import re

from ..base import item, session, to_float

CHAIN = "taco_bell"
SOURCE = "brand menu via Nutritionix (Taco Bell UK)"
SOURCE_URL = "https://www.nutritionix.com/taco-bell-uk/menu/premium"

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def fetch() -> list[dict]:
    s = session()
    r = s.get(SOURCE_URL, timeout=60)
    r.raise_for_status()

    out: list[dict] = []
    seen: set[str] = set()
    for row_html in _ROW.findall(r.text):
        cells = [_text(c) for c in _CELL.findall(row_html)]
        if len(cells) < 9:
            continue
        name = re.sub(r"\s+", " ", cells[0])
        kcal = to_float(cells[2])
        protein = to_float(cells[8])
        if not name or kcal is None or protein is None:
            continue
        if kcal <= 0 or protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
            serving_desc="per serving", kcal=kcal, protein_g=protein,
            fat_g=to_float(cells[3]), carbs_g=to_float(cells[5]),
            salt_g=to_float(cells[9]) if len(cells) > 9 else None))
    return out
