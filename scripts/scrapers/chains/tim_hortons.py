"""Tim Hortons UK & Ireland — brand nutrition PDF.

Discovery: timhortons.co.uk has no nutrition page in its nav or footer, and the
PDF URLs that search engines have indexed (``.../products/<random>.pdf``) 404 —
the asset filename is versioned on every reissue. The live link is only in the
HTML of https://timhortons.co.uk/menu, as
``/assets/img/products/Nutrition-<yyyymmdd>-<hhmmss>-<hash>.pdf``, so this
adapter re-resolves it from the menu page on every run instead of pinning a
filename that dies within weeks.

Format: 13-page PDF. Pages 0-4 are the allergen matrix (no macros); pages 5-12
carry "Nutritional Information (UK & Ireland)" tables, one row per menu item,
per PORTION (not per 100 g), with a portion column ("12 oz", "405 g").

Trap: the generic PDF adapter returns zero rows here even though the table
extracts perfectly — every cell carries its unit inline ("367Kcal", "5.4g"),
and `base.to_float` rejects those. This adapter strips the unit before parsing.
Second trap: the header cells are split over two lines ("Kcal per\\nportion",
"Protein Per\\nportion (g)"), so headers must be de-newlined before matching.
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session

CHAIN = "tim_hortons"
SOURCE = "brand PDF (Tim Hortons UK & Ireland nutrition guide)"
MENU_PAGE = "https://timhortons.co.uk/menu"

_PDF_LINK = re.compile(r'href="([^"]*Nutrition[^"]*\.pdf[^"]*)"', re.I)
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _num(cell) -> float | None:
    """Parse a value that carries its unit inline: '367Kcal' -> 367.0."""
    if cell is None:
        return None
    m = _NUM.search(str(cell).replace("<", "").replace(",", ""))
    return float(m.group()) if m else None


def resolve_pdf_url() -> str | None:
    body = None
    try:
        r = session().get(MENU_PAGE, timeout=60)
        if r.status_code == 200:
            body = r.text
    except Exception:
        pass
    if body is None:
        pr = fetch_protected(MENU_PAGE, timeout=90)
        body = pr.text if pr is not None else None
    if not body:
        return None
    m = _PDF_LINK.search(body)
    if not m:
        return None
    link = m.group(1)
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return "https://timhortons.co.uk" + link
    return link


def _download(url: str) -> bytes | None:
    try:
        r = session().get(url, timeout=120)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    pr = fetch_protected(url, timeout=150)
    if pr is not None and pr.content[:4] == b"%PDF":
        return pr.content
    return None


def parse(raw: bytes, url: str) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or not table[0]:
                    continue
                header = [str(c or "").replace("\n", " ").strip().lower()
                          for c in table[0]]
                i_kcal = i_pro = None
                for i, h in enumerate(header):
                    if i_kcal is None and h.startswith("kcal"):
                        i_kcal = i
                    if i_pro is None and h.startswith("protein"):
                        i_pro = i
                if i_kcal is None or i_pro is None:
                    continue
                for row in table[1:]:
                    if not row or not row[0]:
                        continue
                    name = re.sub(r"\s+", " ",
                                  str(row[0]).replace("\n", " ")).strip()
                    if len(name) < 3:
                        continue
                    kcal = _num(row[i_kcal]) if i_kcal < len(row) else None
                    protein = _num(row[i_pro]) if i_pro < len(row) else None
                    if kcal is None or protein is None:
                        continue
                    if kcal <= 0 or protein < 0:
                        continue
                    if protein * 4 > kcal * 1.15:
                        continue          # misaligned columns
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    portion = (str(row[1]).strip()
                               if len(row) > 1 and row[1] else None)
                    out.append(item(
                        CHAIN, name, SOURCE, url, item_id=name,
                        serving_desc=portion or "per portion",
                        kcal=kcal, protein_g=protein,
                        fat_g=_num(row[5]) if len(row) > 5 else None,
                        carbs_g=_num(row[9]) if len(row) > 9 else None,
                        salt_g=_num(row[16]) if len(row) > 16 else None))
    return out


def fetch() -> list[dict]:
    url = resolve_pdf_url()
    if not url:
        return []
    raw = _download(url)
    if raw is None:
        return []
    return parse(raw, url)
