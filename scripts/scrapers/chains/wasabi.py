"""Wasabi Sushi & Bento — brand nutrition PDF (per-100g, with portion sizes).

Discovery
---------
Linked from wasabi.uk.com; the file lives under WordPress uploads at
`/wp-content/uploads/<YYYY>/<MM>/WAS_Nutritional_Guide_<DDMMYY>[vN].pdf` and
is REPUBLISHED UNDER A NEW FILENAME every few weeks (v16 Jan 2025, v21 Jun
2025, v26 Sep 2025, v27 Oct 2025, v30 Nov 2025 ...). There is no stable
"latest" URL, so `SOURCE_URL` will eventually 404 and needs re-discovery from
the site rather than guessing a date.

The trap
--------
`generic_pdf.fetch_from_pdf` "works" on this file — it returns ~187 rows — and
every one of them is wrong for our purposes. Nearly every column in this PDF
is **per 100 g**, including Protein. Only one column, "Energy (Kcal) per
portion", is per serving. The generic parser matches the first kcal-ish header
(the per-100g one) and pairs it with per-100g protein. That is internally
consistent, so the `protein*4 <= kcal*1.15` gate never fires, but the numbers
are per 100 g while the rest of the pipeline is per serving.

So this adapter reads the columns by their full header text and rebuilds
per-portion values:

    kcal    = "Energy (Kcal) per portion"          (already per serving)
    protein = "Protein (g) per 100g" * "Portion size (g)" / 100

Header cells are multi-line ("Energy\\n(Kcal) per\\nportion"), hence the
whitespace-collapse before matching. Tables extract cleanly with pdfplumber —
no rotation handling needed.

Politeness: one request for the whole 29-page catalogue.
"""
from __future__ import annotations

import io

from ..base import fetch_protected, item, session, to_float

CHAIN = "wasabi"
SOURCE = "Wasabi Nutritional Guide (PDF)"
SOURCE_URL = ("https://www.wasabi.uk.com/wp-content/uploads/2025/11/"
              "WAS_Nutritional_Guide_181125v2.pdf")


def _norm(cell) -> str:
    return " ".join(str(cell or "").split()).lower()


def _columns(header) -> tuple[int, int, int, dict[str, int]] | None:
    """(kcal_per_portion, protein_per_100g, portion_size, extras) or None."""
    cells = [_norm(c) for c in header]

    def find(*preds):
        for i, c in enumerate(cells):
            if all(p in c for p in preds):
                return i
        return None

    i_kcal = find("kcal", "portion")
    i_prot = find("protein")
    i_size = find("portion", "size")
    if i_kcal is None or i_prot is None or i_size is None:
        return None
    extras = {}
    for field, needle in (("carbs_g", "carbohy"), ("fat_g", "fat"),
                          ("salt_g", "salt")):
        # "sat fat" must not win the plain-fat slot
        idx = next((i for i, c in enumerate(cells)
                    if needle in c and not c.startswith("sat")), None)
        if idx is not None:
            extras[field] = idx
    return i_kcal, i_prot, i_size, extras


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
                if len(table) < 2 or not table[0]:
                    continue
                cols = _columns(table[0])
                if not cols:
                    continue
                i_kcal, i_prot, i_size, extras = cols
                for row in table[1:]:
                    if not row or not row[0]:
                        continue
                    name = " ".join(str(row[0]).split())
                    if len(name) < 3:
                        continue
                    width = len(row)
                    if max(i_kcal, i_prot, i_size) >= width:
                        continue
                    kcal = to_float(row[i_kcal])
                    per100 = to_float(row[i_prot])
                    size = to_float(row[i_size])
                    if kcal is None or per100 is None or not size:
                        continue
                    protein = round(per100 * size / 100, 1)
                    if kcal <= 0 or protein * 4 > kcal * 1.15:
                        continue
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)

                    extra_vals = {}
                    for field, idx in extras.items():
                        if idx < width:
                            v = to_float(row[idx])
                            # same per-100g -> per-portion conversion
                            extra_vals[field] = (round(v * size / 100, 1)
                                                 if v is not None else None)
                    rows.append(item(
                        CHAIN, name, SOURCE, SOURCE_URL,
                        item_id=name, category=section or None,
                        serving_desc=f"per portion ({size:g} g)",
                        kcal=kcal, protein_g=protein, **extra_vals,
                    ))
    return rows
