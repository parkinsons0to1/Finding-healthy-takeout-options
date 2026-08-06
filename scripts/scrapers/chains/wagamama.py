"""wagamama — per-dish macros from the Tenkites allergen & nutrition matrix.

Discovery
---------
wagamama.com/allergen-information is a DatoCMS page that renders no nutrition
itself; it links out to a Tenkites-hosted matrix:

    https://menus.tenkites.com/wagamamauk/wagamamainternalallergymatrix

That page IS server-rendered — the whole matrix is in the initial HTML, no JS
execution and no API needed. Every recipe row carries energy (kcal), protein,
carb, fat, salt and fibre.

Traps
-----
* The sibling URL ``wagamamauk/wagamamaallergentablet``, which also appears in
  search results and in the page source, returns a Tenkites 404. Only the
  ``...internalallergymatrix`` path serves data.
* Tenkites is a shared platform (Frankie & Benny's and TGI Fridays UK are on
  it too) but each tenant exposes macros differently. wagamama renders them as
  ``data-nutrient-name`` attributes in the HTML grid; Frankie & Benny's puts
  them only in schema.org JSON-LD. Do not assume one Tenkites parser fits all
  — see ``frankie_bennys.py``.
* Nutrient columns are identified by their ``data-nutrient-name`` text
  ("energy (kcal)", "protein (g)", ...), never by position, because the grid
  also contains an "Energy (kj)" column immediately beside the kcal one.

Format
------
Each recipe block is ``<div class="k10-recipe ...">`` holding the dish name in
``<span class="k10-w-recipe__name">`` and a run of::

    <div ... data-nutrient-id="2" data-nutrient-name="energy (kcal)">780</div>
    <div ... data-nutrient-id="3" data-nutrient-name="protein (g)">68.6</div>

Values may carry thousands separators ("4,845"), so commas are stripped rather
than treated as decimal points.
"""
from __future__ import annotations

import html
import re

from ..base import fetch_protected, item, session

CHAIN = "wagamama"
SOURCE = "brand site (wagamama allergen & nutrition matrix, Tenkites)"
SOURCE_URL = "https://menus.tenkites.com/wagamamauk/wagamamainternalallergymatrix"

_TAG = re.compile(r"<[^>]+>")
#: Split on the start of each recipe block.
_RECIPE_SPLIT = re.compile(r'(?=<div class="k10-recipe [^"]*"\s)')
_NAME = re.compile(r'<span class="k10-w-recipe__name">(.*?)</span>', re.S)
_NUTRIENT = re.compile(r'data-nutrient-name="([^"]+)"[^>]*>\s*([-0-9.,]+)\s*<', re.S)
_COURSE = re.compile(r'<div class="k10-course__name[^"]*">(.*?)</div>', re.S)
#: Dietary flags. TRAP: the label div's ``k10-recipe__label_suitable`` CSS class
#: is static styling on the vegan column and is present on every recipe —
#: keying off it marks meat dishes vegan (it flagged 171 of 172 rows once).
#: The real answer is the nested icon span's data-label-name, which is
#: "LabelValueYes" or "LabelValueNo" per dish.
_DIET_LABEL = re.compile(
    r'<div class="[^"]*k10-recipe__label[^"]*"\s+data-label-id="\d+"\s+'
    r'data-label-name="(vegan|vegetarian)"[^>]*>(.*?)</div>', re.S)
_LABEL_VALUE = re.compile(r'data-label-name="LabelValue(\w+)"')

#: Nutrient name prefix -> normalized field. "energy (kj)" is deliberately
#: absent so the kJ column can never be mistaken for kcal.
_FIELDS = {
    "protein": "protein_g",
    "carb": "carbs_g",
    "fat": "fat_g",
    "salt": "salt_g",
    "fibre": "fibre_g",
    "of which sugars": "sugars_g",
}


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).replace("\xa0", " ").split())


def _get(url: str) -> str | None:
    s = session()
    try:
        r = s.get(url, timeout=120)
        if r.status_code == 200 and r.content:
            return r.content.decode(r.encoding or "utf-8", errors="replace")
    except Exception:
        pass
    pr = fetch_protected(url, timeout=150)
    if pr is not None and pr.content:
        return pr.content.decode("utf-8", errors="replace")
    return None


def fetch() -> list[dict]:
    raw = _get(SOURCE_URL)
    if not raw:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    course = ""

    for chunk in _RECIPE_SPLIT.split(raw):
        # Course headings precede the recipes they contain.
        for m in _COURSE.finditer(chunk):
            t = _text(m.group(1))
            if t:
                course = t

        name_m = _NAME.search(chunk)
        if not name_m:
            continue
        name = _text(name_m.group(1))
        if not name:
            continue

        rec: dict = {}
        for label, value in _NUTRIENT.findall(chunk):
            label = label.lower().strip()
            try:
                val = float(value.replace(",", ""))
            except ValueError:
                continue
            if "kcal" in label:
                rec["kcal"] = val
                continue
            if "(kj)" in label:
                continue
            for prefix, field in _FIELDS.items():
                if label.startswith(prefix):
                    rec.setdefault(field, val)
                    break

        kcal = rec.get("kcal")
        protein = rec.get("protein_g")
        # Plausibility gate: reject rows missing a name, kcal or protein, and
        # rows where protein alone would exceed the stated calories.
        if not kcal or protein is None:
            continue
        if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        diet: dict[str, bool] = {}
        for label, inner in _DIET_LABEL.findall(chunk):
            value = _LABEL_VALUE.search(inner)
            if value:
                diet[label] = value.group(1).lower() == "yes"
        vegan = diet.get("vegan")
        vegetarian = diet.get("vegetarian")
        if vegan:
            vegetarian = True

        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name,
            category=course or None,
            serving_desc="per portion",
            kcal=kcal,
            protein_g=protein,
            carbs_g=rec.get("carbs_g"),
            fat_g=rec.get("fat_g"),
            salt_g=rec.get("salt_g"),
            vegetarian=vegetarian,
            vegan=vegan,
        ))
    return out
