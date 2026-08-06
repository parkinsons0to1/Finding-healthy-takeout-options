"""A generic adapter for brand nutrition PDFs.

UK chains publish nutrition as PDFs in broadly one shape: a table with a
product-name column and numeric columns including energy and protein. The
column *order* and the header wording vary constantly ("Energy (kcal)",
"kcal", "Calories"; "Protein (g)", "Protein"), and headers are often split
across lines or rotated, so a fixed column index per chain is fragile — that
is exactly how the Papa John's parser produced a 218%-protein pizza.

So this adapter finds the columns by reading the header row instead of being
told where they are, then applies the same plausibility gates everywhere:

* a row must have a name and parse both energy and protein
* protein-derived calories cannot exceed the stated calories by more than a
  rounding margin (`protein_g * 4 <= kcal * 1.15`) — the single most effective
  check against column misalignment, because a misread row is usually
  nonsensical in exactly that way
* per-100g pages are detected and kept separate from per-serving pages, since
  mixing them silently halves or doubles everything

Chains whose PDFs don't yield rows this way get a bespoke adapter (KFC,
Subway and Papa John's already have one). This exists so that adding the next
ten chains is configuration, not code.
"""
from __future__ import annotations

import io
import re

from .base import fetch_protected, item, session, to_float

#: Header synonyms -> canonical field.
_HEADER_MAP = {
    "kcal": ("kcal", "calories", "energy kcal", "energykcal", "energy (kcal)",
             "energy kcal per serving", "cals"),
    "protein_g": ("protein", "protein g", "protein (g)", "proteins"),
    "fat_g": ("fat", "fat g", "fat (g)", "total fat"),
    "carbs_g": ("carbohydrate", "carbs", "carbohydrates", "carbohydrate (g)",
                "total carbohydrate"),
    "salt_g": ("salt", "salt (g)", "sodium"),
}

_PER_100G = re.compile(r"per\s*100\s*g", re.I)
#: Rows whose "name" is really a section heading or a units line.
_NOT_A_PRODUCT = re.compile(
    r"^(kcal|kj|g|per|total|energy|nutrition|allergen|contains|values|menu)$", re.I)


def _clean(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _header_variants(cell) -> list[str]:
    """Readable forms of a header cell, in both text orientations.

    Nutrition PDFs very often rotate their column headers 90 degrees to fit
    them above narrow numeric columns. pdfplumber then returns the glyphs
    bottom-to-top, one per line: 'Protein (g)' arrives as
    ')g\\n(\\nn\\nie\\nt\\no\\nr\\nP'. Reading the de-newlined string backwards
    recovers it. Trying both orientations is what lets one adapter handle
    chains that would otherwise each need bespoke column indices.
    """
    raw = str(cell or "")
    flat = raw.replace("\n", "").replace("\r", "")
    return [v for v in (_clean(raw), _clean(flat), _clean(flat[::-1])) if v]


def _map_columns(row) -> dict[str, int]:
    """Map canonical field -> column index, from a candidate header row."""
    found: dict[str, int] = {}
    for idx, cell in enumerate(row):
        for norm in _header_variants(cell):
            for field, synonyms in _HEADER_MAP.items():
                if field in found:
                    continue
                if norm in synonyms or any(norm.startswith(s) for s in synonyms):
                    found[field] = idx
    return found


def _find_header(table) -> tuple[dict[str, int], int] | None:
    for i, row in enumerate(table[:6]):
        if not row:
            continue
        cols = _map_columns(row)
        if "kcal" in cols and "protein_g" in cols:
            return cols, i
    return None


def _plausible(kcal: float, protein: float) -> bool:
    if kcal <= 0 or protein < 0:
        return False
    if protein * 4 > kcal * 1.15:
        return False        # misaligned columns
    return kcal <= 5000 and protein <= 400


def parse_pdf(raw: bytes, chain_id: str, source: str, source_url: str,
              max_pages: int = 60) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages[:max_pages]:
            page_text = page.extract_text() or ""
            basis = "per 100g" if _PER_100G.search(page_text) else "per serving"
            for table in page.extract_tables():
                if len(table) < 2:
                    continue
                header = _find_header(table)
                if not header:
                    continue
                cols, header_idx = header
                for row in table[header_idx + 1:]:
                    if not row or not row[0]:
                        continue
                    name = re.sub(r"\s+", " ",
                                  str(row[0]).replace("\n", " ")).strip()
                    if len(name) < 3 or _NOT_A_PRODUCT.match(name):
                        continue
                    kcal = to_float(row[cols["kcal"]]) if cols["kcal"] < len(row) else None
                    protein = (to_float(row[cols["protein_g"]])
                               if cols["protein_g"] < len(row) else None)
                    if kcal is None or protein is None or not _plausible(kcal, protein):
                        continue
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    extra = {}
                    for field in ("fat_g", "carbs_g", "salt_g"):
                        idx = cols.get(field)
                        if idx is not None and idx < len(row):
                            extra[field] = to_float(row[idx])
                    out.append(item(chain_id, name, source, source_url,
                                    item_id=name, serving_desc=basis,
                                    kcal=kcal, protein_g=protein, **extra))
    return out


def fetch_from_pdf(chain_id: str, pdf_url: str, source_label: str) -> list[dict]:
    """Download a nutrition PDF (plain, then TLS-impersonated) and parse it."""
    s = session()
    raw = None
    try:
        r = s.get(pdf_url, timeout=90)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            raw = r.content
    except Exception:
        pass
    if raw is None:
        pr = fetch_protected(pdf_url, timeout=120)
        if pr is not None and pr.content[:4] == b"%PDF":
            raw = pr.content
    if raw is None:
        return []
    return parse_pdf(raw, chain_id, source_label, pdf_url)
