"""Domino's UK — "Nutrition Information Guide: Pizzas, Bases & Toppings" (PDF).

Discovery
---------
The guide is NOT on dominos.co.uk under a nutrition path; it is a static asset
on Domino's UK Amplience CDN:

    https://dominos.a.bigcontent.io/v1/static/nutrition_pizzas

(no ``.pdf`` extension — it is served with ``Content-Type: application/pdf``).
Found by web search; the brand site itself is a JS app that never exposes it.

TRAP 1 — Cloudflare
    dominos.a.bigcontent.io 403s a plain ``requests`` GET regardless of
    headers: it fingerprints the TLS handshake. ``fetch_protected`` (curl_cffi
    browser impersonation) gets through. ``fetch_from_pdf`` already tries plain
    first then falls back, so it is used here.

TRAP 2 — the column layout is NOT constant across the document
    Running ``_find_header`` over all 20 pages shows the first numeric column
    lands at index 0, 2, 3 or 4 depending on the table, and tables are 10, 12,
    13, 14 or 25 columns wide. Anything that hard-codes "name is column 0" is
    wrong for most of the file — which is why this adapter derives the split
    point per table as ``min(cols.values())`` and treats *everything to the
    left* as label columns. Tables whose numbers start at column 0 have no name
    at all (split-off continuation blocks) and are skipped rather than guessed
    at.

TRAP 3 — names are printed once per group, not once per row
    A pizza name appears on the first row of its crust group and the crust
    appears on the first row of its size group; every following row leaves
    those cells empty. Reading rows independently yields ~114 nameless rows
    (their first cell is a number). Hence the per-column carry-forward, reset
    at each table.

TRAP 4 — one label column is rotated 90 degrees
    The cheese column arrives as ``'allerazzoM\\ndradnatS'`` — each line
    reversed AND the lines in reverse order. Decoding is: reverse each line,
    then reverse the line order, giving "Standard Mozzarella". It is detected
    structurally (multi-line cell, no spaces within any line) rather than by
    matching the word, and is pushed to the END of the qualifier list so the
    dish name still leads.

TRAP 5 — basis
    The pizza pages carry BOTH "Per Pizza" and "Per Slice" blocks side by side
    (that is what the 25-column tables are). ``_find_header`` binds the FIRST
    kcal/protein pair, i.e. the **Per Pizza** block, so the figures here are
    for a WHOLE PIZZA — e.g. Absolute Banger Large = 2512 kcal / 114.4 g
    protein. Do not present these as a portion. The basis is recorded in
    ``serving_desc`` and, per size, inside the name.

Sibling static paths (nutrition_sides, etc.) may exist on the same CDN but
were not enumerated — this module covers pizzas, bases and toppings only.
"""
from __future__ import annotations

import re

from ..base import fetch_protected, item, session, to_float
from ..generic_pdf import _find_header

CHAIN = "dominos"
SOURCE = "Domino's UK Nutrition Information Guide (Pizzas, Bases & Toppings)"
SOURCE_URL = "https://dominos.a.bigcontent.io/v1/static/nutrition_pizzas"

_NUMERIC = re.compile(r"^[\d.,\s]+$")
_SIZES = {"large", "medium", "small", "personal"}


def _is_rotated(raw: str) -> bool:
    """A 90-degree-rotated header/label cell: several lines, none with a space."""
    lines = [ln for ln in str(raw).split("\n") if ln.strip()]
    return len(lines) >= 2 and all(" " not in ln.strip() for ln in lines)


def _decode_rotated(raw: str) -> str:
    lines = [ln.strip() for ln in str(raw).split("\n") if ln.strip()]
    return " ".join(ln[::-1] for ln in reversed(lines))


def _is_garbled(text: str) -> bool:
    """Leftover 90-degree text that `_is_rotated` did not catch.

    Some rotated cells break into lines that *do* contain spaces, so the
    structural test misses them and they survive as strings like
    "e lge nv is re re s P". They are recognisable by having several
    one-or-two-character whitespace tokens, which real dish names do not.
    """
    tokens = text.split()
    return sum(1 for t in tokens if len(t) <= 2) >= 3


def _clean(raw) -> str:
    if raw is None:
        return ""
    if _is_rotated(raw):
        return _decode_rotated(raw)
    return re.sub(r"\s+", " ", str(raw).replace("\n", " ")).strip()


def _basis(page_text: str) -> str:
    low = page_text.lower()
    if "per pizza" in low:
        return "whole pizza"
    if re.search(r"per\s*100\s*g", low):
        return "per 100g"
    return "per serving"


def _rows_from_pdf(raw: bytes) -> list[dict]:
    import io

    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            basis = _basis(page.extract_text() or "")
            for table in page.extract_tables():
                if len(table) < 2:
                    continue
                header = _find_header(table)
                if not header:
                    continue
                cols, hidx = header
                numstart = min(cols.values())
                if numstart == 0:
                    continue          # no label columns -> cannot name the row
                # Carry-forward state, one slot per label column, per table.
                carry: list[str] = [""] * numstart
                rotated_col = [False] * numstart
                for row in table[hidx + 1:]:
                    if not row or len(row) <= max(cols.values()):
                        continue
                    for i in range(numstart):
                        cell = row[i] if i < len(row) else None
                        if cell is not None and str(cell).strip():
                            if _is_rotated(cell):
                                rotated_col[i] = True
                            carry[i] = _clean(cell)
                    kcal = to_float(row[cols["kcal"]])
                    protein = to_float(row[cols["protein_g"]])
                    if kcal is None or protein is None:
                        continue
                    if kcal <= 0 or protein < 0:
                        continue
                    if protein * 4 > kcal * 1.15:
                        continue      # misaligned columns / not a dish
                    plain = [carry[i] for i in range(numstart)
                             if carry[i] and not rotated_col[i]
                             and not _NUMERIC.match(carry[i])
                             and not _is_garbled(carry[i])]
                    rot = [carry[i] for i in range(numstart)
                           if carry[i] and rotated_col[i]
                           and not _is_garbled(carry[i])]
                    parts = plain + rot
                    if not parts:
                        continue
                    head, quals = parts[0], parts[1:]
                    name = f"{head} — {', '.join(quals)}" if quals else head
                    if len(name) < 3 or name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    size = next((p for p in parts if p.lower() in _SIZES), None)
                    serving = f"{basis} ({size})" if size and basis == "whole pizza" else basis
                    extra = {}
                    for field in ("fat_g", "carbs_g", "salt_g"):
                        idx = cols.get(field)
                        if idx is not None and idx < len(row):
                            extra[field] = to_float(row[idx])
                    out.append(item(CHAIN, name, SOURCE, SOURCE_URL,
                                    item_id=name, category=head,
                                    serving_desc=serving,
                                    kcal=kcal, protein_g=protein, **extra))
    return out


def fetch() -> list[dict]:
    raw = None
    try:
        r = session().get(SOURCE_URL, timeout=90)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            raw = r.content
    except Exception:
        pass
    if raw is None:
        pr = fetch_protected(SOURCE_URL, timeout=120)
        if pr is not None and pr.content[:4] == b"%PDF":
            raw = pr.content
    if raw is None:
        return []
    return _rows_from_pdf(raw)
