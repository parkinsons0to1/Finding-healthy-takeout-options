"""Subway UK & ROI — official nutrition PDF, link discovered from the
nutrition page (the filename changes with each revision).

Discovery notes (2026-07-28):
  * https://www.subway.com/en-gb/menunutrition/nutrition embeds the current
    PDF path, e.g. /en-gb/media/emea/europe/uk/nutrition/2026/
    UKI_IngredientsNutritionalInformationJune2026.pdf
  * Table columns: [name, serving_g, kJ, kcal, fat, sat, carbs, sugars,
    fibre, protein, salt]. Values are per 6-inch sub / per listed serving.
  * Historic note: Subway has published separate "Standard" and "Halal"
    nutrition PDFs (halal stores swap some meats) — per-store halal status.
"""
from __future__ import annotations

import io
import re

from .base import item, session, to_float

PAGE_URL = "https://www.subway.com/en-gb/menunutrition/nutrition"
CHAIN = "subway"
SOURCE = "brand-published PDF (Subway UK nutrition)"

_SECTION_NAMES = ("subs", "salads", "wraps", "sides", "breakfast", "drinks",
                  "extras", "cookies")


def _find_pdf_url(s) -> str:
    html = s.get(PAGE_URL, timeout=30).text
    m = re.search(r'"(/en-gb/media/[^"]*[Nn]utritional[^"]*\.pdf)"', html)
    if not m:
        raise RuntimeError("Subway nutrition PDF link not found on page")
    return "https://www.subway.com" + m.group(1)


def fetch() -> list[dict]:
    import pdfplumber
    s = session()
    pdf_url = _find_pdf_url(s)
    raw = s.get(pdf_url, timeout=60).content
    out, section = [], None
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for pg in pdf.pages:
            for tbl in pg.extract_tables():
                for r in tbl:
                    if not r or not r[0]:
                        continue
                    name = r[0].replace("\n", " ").strip()
                    if name.lower() in _SECTION_NAMES:
                        section = name
                        continue
                    kcal = to_float(r[3]) if len(r) > 9 else None
                    prot = to_float(r[9]) if len(r) > 9 else None
                    if kcal is None or prot is None:
                        continue
                    out.append(item(
                        CHAIN, name, SOURCE, pdf_url,
                        item_id=f"{section or 'menu'}:{name}", category=section,
                        serving_desc=f"{r[1]}g serving" if r[1] else None,
                        kcal=kcal, protein_g=prot,
                        fat_g=to_float(r[4]), carbs_g=to_float(r[6]),
                        salt_g=to_float(r[10]) if len(r) > 10 else None,
                    ))
    return out
