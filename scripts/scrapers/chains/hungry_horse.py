"""Hungry Horse (Greene King) — per-serving macros from the brand nutrition PDF.

Discovery
---------
hungryhorse.co.uk has no nutrition page (``/nutrition`` and
``/nutritional-information`` both 404) and ``/allergens`` links only NGCI and
drinks guides. The full nutrition table is a PDF on Greene King's content hub:

    https://gkbr-p-001.sitecorecontenthub.cloud/api/public/content/<guid>?v=<ver>

THE TRAP — interleaved "% Reference Intake" columns
---------------------------------------------------
The shared ``generic_pdf`` adapter returns exactly ONE row from this file, and
that near-empty result is the thing most likely to be misread as "the PDF is
allergen-only" or "the parser is broken". Neither is true. The table has a
two-tier header: a top row naming each nutrient and a second row that splits
every nutrient into TWO columns, "Per Serving" and "% Reference Intake":

    Menu | Menu Cat. | Dish Name | Energy(kJ) | Energy(kcal) | Fat | Sat Fat |
    Carbohydrates | Sugars | Protein | Salt          <- top row, 8 nutrients
    ...  | ...      | ...       | Per Serving | %RI | Per Serving | %RI | ...

``generic_pdf`` maps columns by matching the header row, but here the row that
carries the units is the *second* one and it says "Per Serving" under every
nutrient, so nothing matches. Extracting by fixed index against the real
layout is what works:

    col  2 = Dish Name
    col  5 = Energy (kcal)     <- NOT col 3; col 3/4 are Energy (kJ) and its %RI
    col 15 = Protein (g)       <- 3 + 2*6, six nutrients past energy-kcal

Those indices are asserted against the header before use (see
``_header_matches``) so that a future re-layout fails loudly instead of
silently reading the wrong column — which is precisely how a 218%-protein
pizza gets shipped.

The PDF currently published is labelled "Autumn Winter 2024". Greene King
rotates the content-hub GUID when they replace it, so if this adapter starts
returning 0 items, re-read the guid from hungryhorse.co.uk/allergens.
"""
from __future__ import annotations

import io

from ..base import fetch_protected, item, session

CHAIN = "hungry_horse"
SOURCE = "brand PDF (Hungry Horse core main menu nutrition, Greene King)"
SOURCE_URL = ("https://gkbr-p-001.sitecorecontenthub.cloud/api/public/content/"
              "b458816b05d642ab91b2e5a255de1f0e?v=13b0672b")

#: Fixed column indices — see the module docstring for why these and not 3/9.
COL_CATEGORY = 1
COL_NAME = 2
COL_KCAL = 5
COL_PROTEIN = 15
COL_FAT = 7
COL_CARBS = 11
COL_SALT = 17
#: Widest index touched, so a short row can be skipped without IndexError.
MIN_COLS = COL_SALT + 1


def _download() -> bytes | None:
    s = session()
    try:
        r = s.get(SOURCE_URL, timeout=120)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    pr = fetch_protected(SOURCE_URL, timeout=150)
    if pr is not None and pr.content[:4] == b"%PDF":
        return pr.content
    return None


def _cell(row, idx) -> str:
    if idx >= len(row):
        return ""
    return (row[idx] or "").replace("\n", " ").strip()


def _header_matches(row) -> bool:
    """True if this row is the two-tier header AND our indices still line up.

    Guards the fixed column indices: if Greene King re-lays-out the table, the
    assertion fails, the adapter yields nothing, and the run reports 0 items —
    loud and obviously wrong — instead of quietly reading sugars as protein.
    """
    if len(row) < MIN_COLS:
        return False
    return (_cell(row, COL_NAME).lower().startswith("dish name")
            and _cell(row, COL_KCAL).lower().startswith("per serving")
            and _cell(row, COL_PROTEIN).lower().startswith("per serving"))


def _num(text: str):
    try:
        return float(text.replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def fetch() -> list[dict]:
    raw = _download()
    if not raw:
        return []

    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    layout_ok = False

    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                rows = list(table)
                # Confirm the layout on any page that still carries the header.
                if any(_header_matches(r) for r in rows[:3] if r):
                    layout_ok = True
                if not layout_ok:
                    continue
                for row in rows:
                    if not row or len(row) < MIN_COLS or _header_matches(row):
                        continue
                    name = _cell(row, COL_NAME)
                    if not name or name.lower().startswith("dish name"):
                        continue
                    kcal = _num(_cell(row, COL_KCAL))
                    protein = _num(_cell(row, COL_PROTEIN))
                    # Plausibility gate: no name/kcal/protein, or protein-derived
                    # calories above the stated calories, means a misread row.
                    if kcal is None or protein is None:
                        continue
                    if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
                        continue
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(item(
                        CHAIN, name, SOURCE, SOURCE_URL,
                        item_id=name,
                        category=_cell(row, COL_CATEGORY) or None,
                        serving_desc="per serving",
                        kcal=kcal,
                        protein_g=protein,
                        carbs_g=_num(_cell(row, COL_CARBS)),
                        fat_g=_num(_cell(row, COL_FAT)),
                        salt_g=_num(_cell(row, COL_SALT)),
                    ))
    return out
