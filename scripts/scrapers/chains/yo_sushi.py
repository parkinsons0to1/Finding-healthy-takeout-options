"""YO! Sushi — live Tenkites allergen/nutrition menu (HTML), PDF as fallback.

Discovery
---------
Search first surfaced an official PDF:

    https://yosushi.com/getattachment/1542b7f9-5733-4588-8297-21c764126bad/
    Allergen-and-Nutritional-Report-December-2022.pdf?lang=en-GB

It parses (111 items) but is dated **December 2022**. The current page,
`https://yosushi.com/legal/allergen-information`, instead links three live
Tenkites menus:

    menus.tenkites.com/yosushi/allergenpageyosushi   (restaurants)
    menus.tenkites.com/yosushi/kiosk02               (Tesco kiosks)
    menus.tenkites.com/yoireland03                   (Ireland kiosks)

Tenkites is a third-party allergen-menu platform, and — usefully — it renders
everything SERVER-SIDE. No JSON API is needed and no browser is needed; the
GB menu is a single ~14 MB HTML document containing every recipe card.

So this adapter reads the live Tenkites menus and falls back to the 2022 PDF
only if they return nothing.

Parsing the Tenkites HTML
-------------------------
Each recipe card contains, in order:

    <span class="k10-w-recipe__name">chicken katsu curry large</span>
    ...
    <div class="k10-recipe__nutrients-table">
      <div class="...-row">  <span class="k10-recipe__nutrient-name">Energy (kJ)</span> ... </div>
      <div class="...-row">  <span class="k10-recipe__nutrient-value">3,825</span>   ... </div>

i.e. a header row of names then a row of values, positionally aligned. The
name and its table are NOT in the same container, so the card's product name
is recovered by taking the last `k10-w-recipe__name` occurring BEFORE each
nutrients table offset. Values carry thousands separators ("3,825"), which
must be stripped before float() — otherwise every four-digit kJ/kcal is lost.
Note the header is "Energy (kCal)" with a lowercase k and capital C.

Names are lowercase in the source; they are title-cased here for display.

Politeness: 2 requests (GB restaurant + Tesco kiosk menus), each large.

The PDF fallback
----------------
`generic_pdf.parse_pdf` returns 0 on it: the pages are text but pdfplumber
finds no table objects (the layout is whitespace-aligned, not ruled). It is
parsed by regex — a name followed by exactly 12 numbers, columns being
Energy(kcal), Energy(kJ), Fat, saturates, mono, poly, Carb, Starch, Sugars,
Protein, Fibre, Sodium(mg), so kcal is index 0 and protein is index 9.
"""
from __future__ import annotations

import html as _html
import re

from ..base import fetch_protected, item, session, to_float

CHAIN = "yo_sushi"
SOURCE = "YO! Sushi allergen & nutrition menu (Tenkites)"
SOURCE_URL = "https://menus.tenkites.com/yosushi/allergenpageyosushi"

#: GB menus linked from yosushi.com/legal/allergen-information. The Ireland
#: kiosk menu is deliberately excluded — this pipeline is UK.
MENUS = (
    ("https://menus.tenkites.com/yosushi/allergenpageyosushi", "Restaurant"),
    ("https://menus.tenkites.com/yosushi/kiosk02", "Tesco kiosk"),
)

PDF_FALLBACK_URL = (
    "https://yosushi.com/getattachment/1542b7f9-5733-4588-8297-21c764126bad/"
    "Allergen-and-Nutritional-Report-December-2022.pdf?lang=en-GB")

_NAME_RE = re.compile(r'class="k10-w-recipe__name">(.*?)</span>', re.S)
_TABLE_RE = re.compile(r'class="k10-recipe__nutrients-table"')
_NUT_NAME_RE = re.compile(r'k10-recipe__nutrient-name[^>]*>(.*?)</span>', re.S)
_NUT_VAL_RE = re.compile(r'k10-recipe__nutrient-value[^>]*>(.*?)</span>', re.S)

#: A card's nutrient table sits within this many chars of its marker.
_CARD_WINDOW = 9000


def _num(text: str) -> float | None:
    """Parse a Tenkites value: strips thousands separators ('3,825')."""
    return to_float(str(text).replace(",", "").strip())


def _clean(text: str) -> str:
    return " ".join(_html.unescape(text).split())


def _parse_menu(page: str, category: str, url: str) -> list[dict]:
    names = [(m.start(), _clean(m.group(1))) for m in _NAME_RE.finditer(page)]
    rows: list[dict] = []
    for m in _TABLE_RE.finditer(page):
        offset = m.start()
        preceding = [n for pos, n in names if pos < offset]
        if not preceding:
            continue
        name = preceding[-1]
        chunk = page[offset:offset + _CARD_WINDOW]
        labels = [_clean(x) for x in _NUT_NAME_RE.findall(chunk)]
        values = [_clean(x) for x in _NUT_VAL_RE.findall(chunk)]
        if not labels or len(values) < len(labels):
            continue
        data = dict(zip(labels, values[:len(labels)]))

        kcal = _num(data.get("Energy (kCal)", ""))
        protein = _num(data.get("Protein (g)", ""))
        if not name or kcal is None or protein is None:
            continue
        if kcal <= 0 or protein * 4 > kcal * 1.15:
            continue
        rows.append(item(
            CHAIN, name.title(), SOURCE, url,
            item_id=name, category=category, serving_desc="per serving",
            kcal=kcal, protein_g=protein,
            carbs_g=_num(data.get("Carb (g)", "")),
            fat_g=_num(data.get("Fat (g)", "")),
            salt_g=_num(data.get("Salt (g)", "")),
        ))
    return rows


def _from_pdf() -> list[dict]:
    """2022 brand PDF: 12 whitespace-aligned numeric columns per line."""
    import io

    import pdfplumber

    s = session()
    raw = None
    try:
        r = s.get(PDF_FALLBACK_URL, timeout=120)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            raw = r.content
    except Exception:
        pass
    if raw is None:
        r = fetch_protected(PDF_FALLBACK_URL, timeout=150)
        raw = r.content if r is not None and r.content[:4] == b"%PDF" else None
    if raw is None:
        return []

    line_re = re.compile(r"^(.+?)\s+((?:-?\d+\.?\d*\s+){11}-?\d+\.?\d*)\s*$")
    rows: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").split("\n"):
                m = line_re.match(line.strip())
                if not m:
                    continue
                name = m.group(1).strip()
                nums = [float(x) for x in m.group(2).split()]
                kcal, protein = nums[0], nums[9]
                if len(name) < 3 or kcal <= 0 or protein * 4 > kcal * 1.15:
                    continue
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                rows.append(item(
                    CHAIN, name, "YO! Sushi Allergen and Nutritional Report (PDF)",
                    PDF_FALLBACK_URL, item_id=name,
                    serving_desc="per typical serving",
                    kcal=kcal, protein_g=protein,
                    fat_g=nums[2], carbs_g=nums[6],
                    salt_g=round(nums[11] * 2.5 / 1000, 2),   # sodium mg -> salt g
                ))
    return rows


def fetch() -> list[dict]:
    s = session()
    rows: list[dict] = []
    seen: set[str] = set()
    for url, category in MENUS:
        try:
            r = s.get(url, timeout=180)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        for row in _parse_menu(r.text, category, url):
            key = str(row["name"]).lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows or _from_pdf()
