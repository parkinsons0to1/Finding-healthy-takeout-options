"""KFC UK — official Allergen & Nutrition PDF at a stable URL.

Discovery notes (2026-07-28):
  * https://brand-uk.assets.kfc.co.uk/nutrition-allergens.pdf is the current
    brand-published guide (June 2026 V2 at time of writing) and the URL is
    stable across revisions. kfc.co.uk HTML endpoints are JS-rendered/blocked,
    the PDF is not.
  * pdfplumber table extraction works: columns are
    [name, contains, may-contain, kJ, kcal, fat, sat, carbs, sugars, protein,
     salt, vegetarian, vegan?].
  * Halal: KFC serves halal (HFA-approved) in ~200 of ~1000 branches; the
    branch list lives at https://www.kfc.co.uk/halal (per-outlet data, not
    handled here).
"""
from __future__ import annotations

import io

from .base import item, session, to_float

PDF_URL = "https://brand-uk.assets.kfc.co.uk/nutrition-allergens.pdf"
CHAIN = "kfc"
SOURCE = "brand-published PDF (KFC UK nutrition-allergens.pdf)"


def fetch() -> list[dict]:
    import pdfplumber
    s = session()
    raw = s.get(PDF_URL, timeout=60).content
    out = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for pg in pdf.pages:
            for tbl in pg.extract_tables():
                if len(tbl) < 3:
                    continue
                for r in tbl:
                    if not r or not r[0]:
                        continue
                    kcal = to_float(r[4]) if len(r) > 9 else None
                    prot = to_float(r[9]) if len(r) > 9 else None
                    if kcal is None or prot is None:
                        continue
                    name = r[0].replace("\n", " ").strip()
                    out.append(item(
                        CHAIN, name, SOURCE, PDF_URL,
                        item_id=name,
                        kcal=kcal, protein_g=prot,
                        fat_g=to_float(r[5]), carbs_g=to_float(r[7]),
                        salt_g=to_float(r[10]) if len(r) > 10 else None,
                        vegetarian=(len(r) > 11 and (r[11] or "").strip() == "✔"),
                        allergens=sorted((r[1] or "").split()),
                    ))
    return out
