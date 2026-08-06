"""Taco Bell UK — the Nutritionix-hosted portal their own site embeds.

Discovery
---------
tacobell.co.uk/nutrition-information/ has no macros in it at all. Its entire
content is an iframe:

    <iframe src="https://www.nutritionix.com/taco-bell-uk/menu/premium">

That iframe URL is the brand's official nutrition portal (Nutritionix hosts it
for Taco Bell UK) and it renders server-side as a plain HTML table — no JS, no
API key. Note the `-uk` suffix: /taco-bell/ is the US menu with different
products and US serving sizes.

Shape
-----
One `<tr>` per product. Cells are identified by their `headers` attribute
rather than position, which is what keeps this robust if a column is added:

    inmGrid_c0 name  c1 Energy kJ  c2 Energy kcal  c3 fat  c4 saturates
    c5 carbohydrate  c6 sugars     c7 fibre        c8 protein  c9 salt

Traps
-----
* Column *order* is not the same as the printed order elsewhere: kcal is c2,
  not c1 (c1 is kJ). Indexing positionally is how you end up publishing
  kilojoules as calories.
* bs4 is not a dependency of this project, so the table is parsed with regex
  over those `headers` attributes.
* 518 rows; the plausibility gate legitimately drops "Jalapenos, Single
  Portion" (1 kcal / 0.5 g protein), a rounding artefact on a near-zero item.
"""
from __future__ import annotations

import re

from ..base import item, session, to_float

CHAIN = "taco_bell"
SOURCE = "Taco Bell UK nutrition portal (Nutritionix, embedded by tacobell.co.uk)"
SOURCE_URL = "https://www.nutritionix.com/taco-bell-uk/menu/premium"
BRAND_PAGE = "https://www.tacobell.co.uk/nutrition-information/"

_ROW = re.compile(r'<tr class="(?:odd|even)">(.*?)</tr>', re.S)
_NAME = re.compile(r'<a class="nmItem"[^>]*>(.*?)</a>', re.S)
_CELL = re.compile(r'<td[^>]*headers="(inmGrid_c\d+)"[^>]*>(.*?)</td>', re.S)
_TAGS = re.compile(r"<[^>]+>")

COL_KCAL, COL_PROTEIN = "inmGrid_c2", "inmGrid_c8"
COL_FAT, COL_CARBS, COL_SALT = "inmGrid_c3", "inmGrid_c5", "inmGrid_c9"


def _text(html: str) -> str:
    return _TAGS.sub("", html).replace("&nbsp;", " ").replace("&amp;", "&").strip()


def _num(raw):
    return to_float(re.sub(r"[^0-9.]", "", raw or "")) if raw else None


def fetch() -> list[dict]:
    body = session().get(SOURCE_URL, timeout=90).text
    out: list[dict] = []
    seen: set[str] = set()
    for row in _ROW.findall(body):
        m = _NAME.search(row)
        if not m:
            continue
        name = _text(m.group(1))
        cells = {k: _text(v) for k, v in _CELL.findall(row)}
        kcal, protein = _num(cells.get(COL_KCAL)), _num(cells.get(COL_PROTEIN))
        if not name or not kcal or protein is None:
            continue
        if protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name, serving_desc="per serving",
            kcal=kcal, protein_g=protein,
            fat_g=_num(cells.get(COL_FAT)), carbs_g=_num(cells.get(COL_CARBS)),
            salt_g=_num(cells.get(COL_SALT)),
        ))
    return out
