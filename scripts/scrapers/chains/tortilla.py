"""Tortilla — brand nutrition PDF on the Storyblok CDN.

Discovery
---------
`https://www.tortilla.co.uk/menu/nutrition-and-allergens` links the guide,
hosted on Storyblok (`a.storyblok.com/f/158888/...`). The sibling page
`/menu/nutrition-calculator` is a Next.js client-rendered widget and is not
worth scraping — the PDF has the same numbers in one request.

The trap
--------
`generic_pdf.fetch_from_pdf` returns 0 rows. The header spans TWO physical
rows and neither row alone contains both keys:

    row 0: ['Menu Item', 'Energy', None, 'Fat\\n(g)', ... 'Protein\\n(g)', ...]
    row 1: [None,        'Kcal',  'KJ',  None,        ... None,           ...]

`_find_header` scans one row at a time, so it sees kcal without protein and
protein without kcal and gives up. Concatenating row 0 and row 1 per column
recovers "energy kcal" and "protein (g)" and everything parses.

Content note
------------
The tables are build-your-own COMPONENTS (tortilla wrap, coriander rice, black
beans, each protein, each salsa), not finished meals, and the same component
appears at different values on the medium and large pages. Names are therefore
prefixed with the page heading (e.g. "Black Beans (MeDiuM Burrito/Bowl)") —
without it, dedupe would silently drop the large-portion rows. The odd
capitalisation comes from the PDF's small-caps headings and is left as-is so
it stays traceable to the source.

Politeness: one request for the whole 20-page guide.
"""
from __future__ import annotations

import io

from ..base import fetch_protected, item, session, to_float

CHAIN = "tortilla"
SOURCE = "Tortilla Nutrition & Allergen Information (PDF)"
SOURCE_URL = ("https://a.storyblok.com/f/158888/x/5965ee8d1d/"
              "tortilla-nutrition-guide-wed-29-jul.pdf")

#: Sections whose tables carry no macros (hot drinks list Kcal only).
_FIELD_NEEDLES = (("carbs_g", "carbs"), ("fat_g", "fat"), ("salt_g", "salt"))


def _norm(cell) -> str:
    return " ".join(str(cell or "").split()).lower()


def _merged_header(table) -> list[str]:
    """Concatenate the first two rows column-wise into one header row."""
    top = [_norm(c) for c in table[0]]
    if len(table) > 1 and len(table[1]) == len(top):
        second = [_norm(c) for c in table[1]]
        return [(a + " " + b).strip() for a, b in zip(top, second)]
    return top


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
            section = ((page.extract_text() or "").split("\n") or [""])[0].strip()
            for table in page.extract_tables():
                if len(table) < 3:
                    continue
                header = _merged_header(table)
                i_kcal = next((i for i, h in enumerate(header) if "kcal" in h), None)
                i_prot = next((i for i, h in enumerate(header) if "protein" in h), None)
                if i_kcal is None or i_prot is None:
                    continue
                extras = {}
                for field, needle in _FIELD_NEEDLES:
                    idx = next((i for i, h in enumerate(header)
                                if needle in h and not h.startswith("sat")), None)
                    if idx is not None:
                        extras[field] = idx

                for row in table[2:]:          # rows 0 and 1 are the split header
                    if not row or not row[0]:
                        continue
                    name = " ".join(str(row[0]).split())
                    if len(name) < 3 or max(i_kcal, i_prot) >= len(row):
                        continue
                    kcal = to_float(row[i_kcal])
                    protein = to_float(row[i_prot])
                    if kcal is None or protein is None:
                        continue
                    if kcal <= 0 or protein * 4 > kcal * 1.15:
                        continue
                    label = f"{name} ({section})" if section else name
                    key = label.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(item(
                        CHAIN, label, SOURCE, SOURCE_URL,
                        item_id=label, category=section or None,
                        serving_desc="per serving",
                        kcal=kcal, protein_g=protein,
                        **{f: to_float(row[i]) for f, i in extras.items()
                           if i < len(row)},
                    ))
    return rows
