"""Krispy Kreme UK — "UK Drinks Allergen & Nutrition Book" (brand PDF).

Discovery
---------
https://www.krispykreme.co.uk/nutritionals (plain ``requests`` 403s — the
site fingerprints TLS, so this needs ``fetch_protected``) links the current
book, filename-versioned by date
(``UK_Drinks_Allergen_Nutrition_Book_<DDMMYY>.pdf``), so the URL is resolved
from the landing page each run rather than hard-coded.

TRAP — two nutrition blocks per row, in the WRONG order for a naive first-match
    Every nutrition table (doughnuts, milkshakes, hot/iced drinks, ice cream)
    is 20 columns wide and has real header text for both blocks:
        col 0       item name
        cols 1-9    Nutrition Per 100g / Per 100ml (kJ, kcal, fat, sat,
                                                      carbs, sugars, fibre,
                                                      protein, salt)
        col 10      average portion weight/volume, e.g. "50g", "340 ml"
        cols 11-19  Nutrition Per Portion (same nine fields)
    generic_pdf's column mapper binds the FIRST header cell that matches a
    field's synonyms — here that is the per-100g block, because per-100g is
    printed first (the opposite order to chains like PizzaExpress, where
    "first" happens to be per-portion). The result: every row got the
    per-100g numbers stamped "per 100g" (91 of 97 rows) rather than the
    per-portion numbers this PDF publishes right next to them. This adapter
    reads cols 11-19 explicitly.

    Verified against the raw table: Original Glazed = 225 kcal / 2.8 g
    protein per 50 g portion (per 100 g it would be 450 / 5.5 — the value
    previously recorded).

Nutrition tables are told apart from allergen tables (which share the same
"Product Description" header wording) by requiring 'energy'/'kcal' to appear
in one of the header cells — allergen tables don't have those.
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session, to_float

CHAIN = "krispy_kreme"
SOURCE = "brand PDF (Krispy Kreme UK Drinks Allergen & Nutrition Book)"
LANDING_URL = "https://www.krispykreme.co.uk/nutritionals"

_PDF_LINK = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)
_NOT_A_PRODUCT = re.compile(
    r"^(kcal|kj|g|per|total|energy|nutrition|allergen|contains|values|menu|"
    r"product description)$", re.I)


def _find_pdf_url() -> str | None:
    pr = fetch_protected(LANDING_URL, timeout=60)
    body = pr.text if pr is not None else None
    if body is None:
        try:
            r = session().get(LANDING_URL, timeout=45)
            if r.status_code == 200:
                body = r.text
        except Exception:
            pass
    if not body:
        return None
    links = [m for m in _PDF_LINK.findall(body)
             if re.search(r"allergen.*nutrition|nutrition.*allergen", m, re.I)]
    if not links:
        return None
    link = links[0]
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return "https://www.krispykreme.co.uk" + link
    return link


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


def _clean(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _has_energy_header(table) -> bool:
    for row in table[:3]:
        for cell in row:
            raw = str(cell or "")
            flat = raw.replace("\n", "").replace("\r", "")
            for v in (_clean(raw), _clean(flat), _clean(flat[::-1])):
                if "energy" in v or "kcal" in v:
                    return True
    return False


def _plausible(kcal: float, protein: float) -> bool:
    if kcal <= 0 or protein < 0:
        return False
    if protein * 4 > kcal * 1.15:
        return False
    return kcal <= 5000 and protein <= 400


def _parse(raw: bytes, source_url: str) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    category = None
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if len(table) < 2 or not _has_energy_header(table):
                    continue
                for row in table:
                    if not row or not row[0]:
                        continue
                    name = re.sub(r"\s+", " ",
                                   str(row[0]).replace("\n", " ")).strip()
                    if len(name) < 3:
                        continue
                    rest = row[1:]
                    if all(c is None or str(c).strip() == "" for c in rest):
                        if name.isupper() or name.istitle():
                            category = name.title()
                        continue
                    if len(row) != 20 or _NOT_A_PRODUCT.match(name):
                        continue
                    kcal = to_float(row[12])       # per-portion block: col11=kJ
                    protein = to_float(row[18])    # ...col12=kcal ... col18=protein
                    if kcal is None or protein is None or not _plausible(kcal, protein):
                        continue
                    weight = str(row[10] or "").strip()
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    serving = f"per portion ({weight})" if weight else "per portion"
                    out.append(item(
                        CHAIN, name, SOURCE, source_url, item_id=name,
                        category=category, serving_desc=serving,
                        kcal=kcal, protein_g=protein,
                        fat_g=to_float(row[13]), carbs_g=to_float(row[15]),
                        salt_g=to_float(row[19])))
    return out


def fetch() -> list[dict]:
    pdf_url = _find_pdf_url()
    if not pdf_url:
        return []
    raw = _fetch_pdf(pdf_url)
    if raw is None:
        return []
    return _parse(raw, pdf_url)
