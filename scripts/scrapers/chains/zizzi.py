"""Zizzi — "Nutrition Guide 2026 UK" (PDF).

Discovery
---------
https://www.zizzi.co.uk/allergens (needs ``fetch_protected``) links five
Sanity-hosted PDFs under ``cdn.sanity.io/files/ysupxjc9/production/``. The
filenames are content hashes, so each has to be opened to be identified:

    a7bddad7…  NUTRITION GUIDE 2026 UK V2          <- this one, 24 pages
    486ec2f5…  NUTRITION GUIDE 2026 ROI.BEL V1     <- Ireland/Belgium, NOT UK
    f5d15b49…  ZIZZI UK ALLERGEN GUIDE 2026 V5
    3928fa3e…  ZIZZI ROI ALLERGEN GUIDE 2026 V2
    e2da64ee…  FULL INGREDIENT DECLARATION 2026 UK V2

The ROI/Belgium guide parses just as cleanly as the UK one and differs only in
a cover line, so picking by "first PDF that yields rows" would silently ship
Irish data. Identify by the cover text, not by parse success.

TRAP 1 — the "macros are in the HTML" lead is only half true
    zizzi.co.uk/allergens does server-render schema.org ``MenuItem`` blocks,
    but their ``NutritionInformation`` carries **calories only** — no protein.
    (The word "protein" appears ~52 times on that page purely inside marketing
    copy, e.g. "Over 50g of protein".) Protein comes from this PDF.

TRAP 2 — per-100g block comes FIRST, unlike PizzaExpress
    Each table is 17 columns:
        col 0      Menu Item Name
        cols 1-8   Per 100g Nutrition   (kJ, kcal, fat, sat, carb, sugar,
                                         protein, salt)
        cols 9-16  Per Portion Nutrition (same eight, repeated)
    The generic parser binds the FIRST kcal/protein pair and so returns
    **per 100 g** values. For meal-level macros that is the wrong basis, and it
    is the opposite convention to PizzaExpress's PDF — do not assume the two
    Azzurri brands share a layout. This adapter reads the header row, finds the
    SECOND kcal and SECOND protein column, and emits per-portion figures.
    Cross-check: Complimentary Pasta Crisps = 346 kcal/3.7 g protein per 100 g
    but 38 kcal/0 g per portion.

TRAP 3 — the "Per Portion" spanning header is not on the value columns
    Row 0 of each table is a spanning header (``'APERITIVO', 'Per 100g
    Nutrition', None…, 'Per Portion Nutrition', None…``) and row 1 holds the
    real column names, which repeat verbatim between the two blocks. So the
    blocks can only be told apart by ORDER, not by wording: take the second
    occurrence of each field. If a future revision drops one block, the second
    occurrence will not exist and this adapter falls back to the first — which
    is why ``serving_desc`` is derived from which occurrence was actually used
    rather than hard-coded.
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session, to_float
from ..generic_pdf import _header_variants

CHAIN = "zizzi"
SOURCE = "Zizzi Nutrition Guide 2026 UK V2"
SOURCE_URL = ("https://cdn.sanity.io/files/ysupxjc9/production/"
              "a7bddad7ab274475b481e054916a0f8208c4d24e.pdf")

_SYNONYMS = {
    "kcal": ("energy kcal", "kcal", "calories"),
    "protein_g": ("protein", "protein g"),
    "fat_g": ("fat", "fat g"),
    "carbs_g": ("carbohydrate", "carbs", "carbohydrates"),
    "salt_g": ("salt",),
}
_NOT_A_PRODUCT = re.compile(
    r"^(kcal|kj|g|per|total|energy|nutrition|allergen|contains|values|menu)$", re.I)


def _occurrences(row) -> dict[str, list[int]]:
    """Every column index matching each field, in left-to-right order."""
    found: dict[str, list[int]] = {k: [] for k in _SYNONYMS}
    for idx, cell in enumerate(row):
        for norm in _header_variants(cell):
            matched = None
            for field, syns in _SYNONYMS.items():
                if norm in syns:
                    matched = field
                    break
            # "energy kcal" must win over a bare "energy"; require exact match
            # so the kJ column (normalises to "energy kj") never binds to kcal.
            if matched and idx not in found[matched]:
                found[matched].append(idx)
                break
    return found


def _find_header(table):
    for i, row in enumerate(table[:6]):
        if not row:
            continue
        occ = _occurrences(row)
        if occ["kcal"] and occ["protein_g"]:
            return occ, i
    return None


def _fetch_pdf(url: str) -> bytes | None:
    try:
        r = session().get(url, timeout=90)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    pr = fetch_protected(url, timeout=120)
    if pr is not None and pr.content[:4] == b"%PDF":
        return pr.content
    return None


def _parse(raw: bytes) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if len(table) < 2:
                    continue
                header = _find_header(table)
                if not header:
                    continue
                occ, hidx = header
                # Second occurrence == "Per Portion" block; first == "Per 100g".
                per_portion = len(occ["kcal"]) > 1 and len(occ["protein_g"]) > 1
                pick = 1 if per_portion else 0
                basis = "per serving" if per_portion else "per 100g"
                kcol = occ["kcal"][pick]
                pcol = occ["protein_g"][pick]
                category = None
                if hidx > 0:
                    category = re.sub(r"\s+", " ",
                                      str(table[0][0] or "").replace("\n", " ")).strip() or None
                for row in table[hidx + 1:]:
                    if not row or not row[0]:
                        continue
                    name = re.sub(r"\s+", " ",
                                  str(row[0]).replace("\n", " ")).strip()
                    if len(name) < 3 or _NOT_A_PRODUCT.match(name):
                        continue
                    if kcol >= len(row) or pcol >= len(row):
                        continue
                    kcal = to_float(row[kcol])
                    protein = to_float(row[pcol])
                    if kcal is None or protein is None:
                        continue
                    if kcal <= 0 or protein < 0:
                        continue
                    if protein * 4 > kcal * 1.15:
                        continue
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    extra = {}
                    for field in ("fat_g", "carbs_g", "salt_g"):
                        idxs = occ.get(field) or []
                        if len(idxs) > pick and idxs[pick] < len(row):
                            extra[field] = to_float(row[idxs[pick]])
                    out.append(item(CHAIN, name, SOURCE, SOURCE_URL,
                                    item_id=name, category=category,
                                    serving_desc=basis,
                                    kcal=kcal, protein_g=protein, **extra))
    return out


def fetch() -> list[dict]:
    raw = _fetch_pdf(SOURCE_URL)
    if raw is None:
        return []
    return _parse(raw)
