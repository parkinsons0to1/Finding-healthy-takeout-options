"""Shared parser for the Mitchells & Butlers brand guides (allergens.mbplc.io).

Private helper (leading underscore => the chains registry skips it). Used by
the three M&B brands in this package: harvester, toby_carvery, miller_carter.

THE TRAP, and why this file exists
----------------------------------
These pages are titled "Allergen Guide" and live on a host called
``allergens.mbplc.io``. Every signal says allergen-only. They are not: each
dish carries a complete per-portion nutrition table — kJ/kcal, Fat, Saturates,
Carbohydrate, Sugars, Protein, Salt. Searching for a separate "M&B nutrition
PDF" finds nothing and invites the wrong conclusion that M&B publishes
allergens only. The nutrition is inside the allergen guide. Do not "fix" a
future breakage by going looking for a different, better-named source.

They are plain static HTML — no JS, no API, no Cloudflare — so a single
``requests`` GET is enough. One page per brand estate:

    https://allergens.mbplc.io/AllergenGuideHarvesterEstate.html
    https://allergens.mbplc.io/AllergenGuideTobyEstate.html
    https://allergens.mbplc.io/AllergenGuideMillerandCarterEstate.html

Format
------
Each dish is a ``<div class="recipe-card">`` holding:

* the name in the first ``<b>`` (description follows after a ``<br>``),
* allergen pills,
* a ``<div class="nutrition">`` table whose FIRST row is the header
  (kJ/kcal, Fat, Saturates, Carbohydrate, Sugars, Protein, Salt) and whose
  "Per Portion:" row holds the values.

Columns are mapped by reading that header row rather than by fixed index —
the brands do not all order the table identically, and a fixed index is how
column-misalignment bugs get shipped.

Section headings (``<p class="sectionContainerH">``) give the category;
menu-level headings (``role="heading" aria-level="2"``) are folded in as a
prefix so "STARTERS" from the main menu and "STARTERS" from the
vegetarian/vegan menu stay distinguishable.

Known bad rows
--------------
Miller & Carter includes menu "swap" rows (e.g. "Burger Swap") whose figures
are *deltas* and therefore partly negative: 28 kcal against 35 g protein. The
plausibility gate in the calling adapter rejects these, which is the intended
outcome — they are not dishes.
"""
from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")

#: Header cell text -> canonical field. Matched by prefix against the cleaned
#: header, so "Carbohydrate" and "Carbohydrates" both land on carbs_g.
_FIELDS = {
    "protein": "protein_g",
    "fat": "fat_g",
    "saturates": "sat_g",
    "carbohydrate": "carbs_g",
    "sugars": "sugars_g",
    "salt": "salt_g",
}

_RECIPE_SPLIT = '<div class="recipe-card">'
_SECTION = re.compile(r'<p class="sectionContainerH"[^>]*>(.*?)</p>', re.S)
_MENU_HEADING = re.compile(
    r'role="heading"\s+aria-level="2"\s*>(.*?)</p>', re.S)


def _text(fragment: str) -> str:
    """Strip tags/entities and collapse whitespace."""
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).replace("\xa0", " ").split())


def _num(cell: str):
    """First number in a cell. Commas are thousands separators here, not
    decimal points, so they are removed rather than converted to '.'
    (base.to_float would turn '1,192' into 1.192)."""
    m = re.search(r"-?\d+(?:\.\d+)?", cell.replace(",", ""))
    return float(m.group(0)) if m else None


def _diet(name: str) -> tuple[bool | None, bool | None]:
    """M&B tag dishes in the name itself: (V) vegetarian, (VE) vegan."""
    upper = name.upper()
    if re.search(r"\(VE\)", upper):
        return True, True          # vegan implies vegetarian
    if re.search(r"\(V\)", upper):
        return True, False
    return None, None


def parse_guide(raw: str) -> list[dict]:
    """Parse a brand guide into raw dicts.

    Returns every row the page states, WITHOUT applying the plausibility gate —
    each chain adapter applies that itself so the rejection is visible at the
    adapter level.
    """
    out: list[dict] = []
    seen: set[str] = set()

    # Walk the document once, remembering the most recent menu/section heading
    # so each recipe card can be attributed to a category.
    menu_heading = ""
    section = ""
    pos = 0
    for chunk_idx, chunk in enumerate(raw.split(_RECIPE_SPLIT)):
        if chunk_idx:
            card = chunk
            name_m = re.search(r"<b>(.*?)</b>", card, re.S)
            nut_m = re.search(r'<div class="nutrition".*?</table>', card, re.S)
            if name_m and nut_m:
                name = _text(name_m.group(1))
                rec = _parse_card(name, nut_m.group(0))
                if rec and rec["name"].lower() not in seen:
                    seen.add(rec["name"].lower())
                    rec["category"] = " / ".join(p for p in (menu_heading, section) if p)
                    out.append(rec)
        # Headings that appear in this chunk apply to the NEXT card.
        for m in _MENU_HEADING.finditer(chunk):
            t = _text(m.group(1))
            if t:
                menu_heading = t
        for m in _SECTION.finditer(chunk):
            t = _text(m.group(1))
            if t:
                section = t
        pos += len(chunk)
    return out


def _parse_card(name: str, table_html: str) -> dict | None:
    if not name:
        return None
    rows = re.findall(r"<tr>(.*?)</tr>", table_html, re.S)
    if len(rows) < 2:
        return None
    header = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", rows[0], re.S)]

    data = None
    for row in rows[1:]:
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if cells and re.search(r"per\s*portion", cells[0], re.I):
            data = cells
            break
    if data is None:
        # Only per-portion rows are usable; a per-100g row silently rescales
        # everything, so it is dropped rather than mixed in.
        return None

    veg, vegan = _diet(name)
    rec: dict = {"name": name, "vegetarian": veg, "vegan": vegan}
    for idx, head in enumerate(header):
        if idx >= len(data):
            break
        low = head.lower()
        if "kcal" in low:
            m = re.search(r"(\d+(?:\.\d+)?)\s*kcal", data[idx].replace(",", ""), re.I)
            if m:
                rec["kcal"] = float(m.group(1))
            continue
        for key, field in _FIELDS.items():
            if low.startswith(key):
                val = _num(data[idx])
                if val is not None:
                    rec[field] = val
                break
    if "kcal" not in rec or "protein_g" not in rec:
        return None
    return rec
