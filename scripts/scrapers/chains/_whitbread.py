"""Shared parser for Whitbread pub-brand allergy & nutrition guides.

Private helper (leading underscore => the chains registry skips it). Used by
beefeater and brewers_fayre.

Discovery
---------
Whitbread publishes one static HTML guide per menu, linked from each brand's
``/en-gb/allergy-nutrition`` index page:

    https://www.beefeater.co.uk/en-gb/allergy-nutrition/bg-<id>-web
    https://www.brewersfayre.co.uk/en-gb/allergy-nutrition/bf-<id>-web

Older menus are PDFs; the current ones are these "-web" pages. Both brands use
an identical template, hence one parser. The index page also lists sibling
menus (breakfast, NGCI/gluten-free, meeting rooms, Christmas, and for Brewers
Fayre a separate Northern Ireland set) in the same format — see
``resolve_menu_urls`` for picking up the current core menu automatically.

Format
------
Each dish is a ``<div class="dish_Content">`` containing:

* ``<label ...>DISH NAME</label>`` inside ``div.dishDetails_P`` (names are
  upper-case in the source), followed by dietary badge divs whose text is
  literally "V" or "VE",
* ``div.dish_Description_Allergen`` with Contains / May Contain,
* ``table.NandATable`` — a two-column key/value table (NOT a grid): rows are
  Energy ("576 kJ / 139 kcal"), Fat, Saturates, Carbohydrates, Sugars,
  Protein, Salt, with a header row reading "Per | Portion:".

Categories come from ``<p class="subMenu_P">`` headings that precede runs of
dishes ("Starters", "Mains - Chargrills", ...).

Trap
----
The header says which basis the table uses. Only "Per Portion" tables are
accepted; anything else is skipped rather than mixed in, because a per-100g
table silently rescales every number.
"""
from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")

_FIELDS = {
    "fat": "fat_g",
    "saturates": "sat_g",
    "carbohydrate": "carbs_g",
    "sugars": "sugars_g",
    "protein": "protein_g",
    "salt": "salt_g",
}

_DISH_SPLIT = '<div class="dish_Content">'
_SUBMENU = re.compile(r'<p class="subMenu_P">(.*?)</p>', re.S)
_LABEL = re.compile(r"<label[^>]*>(.*?)</label>", re.S)
_NAND_TABLE = re.compile(r'<table class="NandATable">.*?</table>', re.S)
#: dietary badge: a small styled div whose entire content is "V" or "VE"
_BADGE = re.compile(r"<div[^>]*>\s*(VE|V)\s*</div>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).replace("\xa0", " ").split())


def _num(cell: str):
    """First number; commas are thousands separators, so strip them."""
    m = re.search(r"-?\d+(?:\.\d+)?", cell.replace(",", ""))
    return float(m.group(0)) if m else None


def parse_guide(raw: str) -> list[dict]:
    """Parse one Whitbread "-web" guide into raw dicts.

    Returns what the page states; the plausibility gate is applied by the
    calling chain adapter so the rejection stays visible there.
    """
    out: list[dict] = []
    seen: set[str] = set()
    category = ""

    for idx, chunk in enumerate(raw.split(_DISH_SPLIT)):
        if idx:
            rec = _parse_dish(chunk)
            if rec and rec["name"].lower() not in seen:
                seen.add(rec["name"].lower())
                rec["category"] = category or None
                out.append(rec)
        # A subMenu_P heading in this chunk applies to the dishes that follow.
        for m in _SUBMENU.finditer(chunk):
            t = _text(m.group(1))
            if t:
                category = t
    return out


def _parse_dish(chunk: str) -> dict | None:
    label = _LABEL.search(chunk)
    table = _NAND_TABLE.search(chunk)
    if not label or not table:
        return None
    name = _text(label.group(1))
    if not name:
        return None

    block = table.group(0)
    if not re.search(r"Portion", block, re.I):
        return None            # per-100g or unlabelled basis: do not mix in

    rec: dict = {"name": name}
    for row in re.findall(r"<tr>(.*?)</tr>", block, re.S):
        cells = [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 2:
            continue
        key, val = cells[0].lower(), cells[1]
        if key == "energy":
            m = re.search(r"(\d+(?:\.\d+)?)\s*kcal", val.replace(",", ""), re.I)
            if m:
                rec["kcal"] = float(m.group(1))
            continue
        for prefix, field in _FIELDS.items():
            if key.startswith(prefix):
                n = _num(val)
                if n is not None:
                    rec[field] = n
                break

    # Dietary badges sit in the header strip, before the expandable content.
    header = chunk.split('<div class="ExColContent">')[0]
    badges = set(_BADGE.findall(header))
    if "VE" in badges:
        rec["vegetarian"], rec["vegan"] = True, True
    elif "V" in badges:
        rec["vegetarian"], rec["vegan"] = True, False

    if "kcal" not in rec or "protein_g" not in rec:
        return None
    return rec


def resolve_menu_urls(index_url: str, body: str, prefix: str) -> list[str]:
    """Current "-web" guide links on a brand's /en-gb/allergy-nutrition page.

    Whitbread renames these every menu cycle (the id is a content-management
    number, e.g. ``bg-1482392-web``), so pinning one filename guarantees a
    silent break within months. The chain adapters use this to re-find the
    live core menu and fall back to their pinned URL only if the lookup fails.
    """
    from urllib.parse import urljoin

    links = re.findall(r'href="([^"]*/allergy-nutrition/[^"]*-web)"', body)
    seen: list[str] = []
    for href in links:
        if prefix not in href:
            continue
        full = urljoin(index_url, html.unescape(href))
        if full not in seen:
            seen.append(full)
    return seen
