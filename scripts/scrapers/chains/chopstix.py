"""Chopstix Noodle Bar — brand nutrition PDF.

Discovery
---------
`https://chopstixnoodles.co.uk/allergen-info/` links TWO PDFs and it matters
which one you grab:

* `CUSTOMER-ALLERGENS-NON-QR-V<N>-<MONTH><YEAR>.pdf`  — allergens only
* `NUTRITIONAL-VALUES-V<N>-<MONTH><YEAR>.pdf`         — the macros  <- this one

Both live under `/wp-content/uploads/<YYYY>/<MM>/` and are reissued with a
bumped version number, so `SOURCE_URL` will go stale; re-read the link from
the allergen-info page rather than guessing the next version.

The trap
--------
`generic_pdf.fetch_from_pdf` returns 6 rows and all 6 are garbage that looks
like this: `"E C IO H C E S A B"  123.0  3.7`. That is "BASE CHOICE" read
backwards. Column 0 of the table is not the product name — it is a 90-degree
ROTATED section label (BASE CHOICE, TOPPING CHOICES, SIDE CHOICES, STIR MIX
IN, DIPS) spanning many rows, empty on all but the first row of each block.
The generic parser takes `row[0]` as the name, so it emits one mangled row per
section and drops all 141 real products.

The fix is to locate the name column by its header text ("Meal Components
(per serving size)") instead of assuming index 0. `generic_pdf` already knows
how to un-rotate header cells, which is why the numeric columns map fine.

Content note
------------
Rows are build-your-own components at four portion sizes — "TASTER BASE",
"Small", "Regular", "Large" — plus packaged drinks. They are per serving.

Politeness: one request for the 2-page guide.
"""
from __future__ import annotations

import io

from ..base import fetch_protected, item, session, to_float

CHAIN = "chopstix"
SOURCE = "Chopstix Nutritional Data (PDF)"
SOURCE_URL = ("https://chopstixnoodles.co.uk/wp-content/uploads/2026/07/"
              "NUTRITIONAL-VALUES-V21-JULY-2026.pdf")

#: Rotated section labels arrive as reversed glyph soup; recognise a real
#: header row by its numeric columns instead.
_NAME_NEEDLES = ("meal component", "product", "item")


def _norm(cell) -> str:
    return " ".join(str(cell or "").split()).lower()


def _header(table) -> tuple[dict[str, int], int] | None:
    for i, row in enumerate(table[:6]):
        if not row:
            continue
        cells = [_norm(c) for c in row]
        if "kcal" not in cells:
            continue
        i_prot = next((j for j, c in enumerate(cells) if c.startswith("protein")),
                      None)
        if i_prot is None:
            continue
        i_name = next((j for j, c in enumerate(cells)
                       if any(n in c for n in _NAME_NEEDLES)), 1)
        cols = {"name": i_name, "kcal": cells.index("kcal"), "protein_g": i_prot}
        for field, needle in (("carbs_g", "carbohydrate"), ("fat_g", "fats"),
                              ("salt_g", "salt")):
            idx = next((j for j, c in enumerate(cells)
                        if c.startswith(needle)), None)
            if idx is not None:
                cols[field] = idx
        return cols, i
    return None


def _load() -> bytes | None:
    s = session()
    try:
        r = s.get(SOURCE_URL, timeout=120)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    r = fetch_protected(SOURCE_URL, timeout=150)
    return r.content if r is not None and r.content[:4] == b"%PDF" else None


def fetch() -> list[dict]:
    import pdfplumber

    raw = _load()
    if raw is None:
        return []

    rows: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                found = _header(table)
                if not found:
                    continue
                cols, start = found
                for row in table[start + 1:]:
                    if not row or max(cols.values()) >= len(row):
                        continue
                    name = " ".join(str(row[cols["name"]] or "").split())
                    if len(name) < 3:
                        continue
                    kcal = to_float(row[cols["kcal"]])
                    protein = to_float(row[cols["protein_g"]])
                    if kcal is None or protein is None:
                        continue
                    if kcal <= 0 or protein * 4 > kcal * 1.15:
                        continue
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(item(
                        CHAIN, name, SOURCE, SOURCE_URL,
                        item_id=name, serving_desc="per serving",
                        kcal=kcal, protein_g=protein,
                        **{f: to_float(row[cols[f]])
                           for f in ("carbs_g", "fat_g", "salt_g") if f in cols},
                    ))
    return rows
