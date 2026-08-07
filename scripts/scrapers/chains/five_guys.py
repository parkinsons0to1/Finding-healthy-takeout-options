"""Five Guys UK — brand nutrition PDF, "UK Nutrition & Allergen Guide".

Discovery
---------
https://www.fiveguys.co.uk/nutrition links several PDFs. Two are easy to
confuse:

* "UK Nutrition & Allergen Guide" — despite living at a URL whose filename
  says ``..._Myprotein_shake_DIGITAL_...pdf`` (a CMS artifact — the brand
  reused/renamed an old upload slug), this is the complete UK nutrition book:
  every ingredient, every composed burger/hot dog/sandwich, breakfast, sides.
  Verified by content, not by filename.
* "Northern Ireland Nutrition & Allergen Guide" (media.fiveguys.com) — a
  different, NI/Benelux-market PDF with different figures. Not the UK menu.

Picking the wrong one by "first .pdf link" would be a silent regional-data
bug, so this adapter selects by the anchor's visible text ("UK Nutrition"),
not by hint-regex-first-match.

TRAP — two nutrition blocks per row, and the FIRST one has no header text
    The nutrition table is 19 columns wide:
        col 0      item name
        cols 1-9   TYPICAL VALUES PER SERVING (kJ, kcal, fat, sat, carbs,
                                                sugars, fibre, protein, salt)
        cols 10-18 TYPICAL VALUES PER 100G     (same nine, repeated)
    pdfplumber extracts real header text for the per-100g block but returns
    None for every per-serving header cell (a rendering quirk of this PDF —
    the per-serving super-header "TYPICAL VALUES PER SERVING" sits above the
    table's bounding box, not inside a table cell). generic_pdf's
    header-driven column mapping therefore cannot find "kcal"/"protein" in
    the first block at all and silently binds to the second (per-100g) one —
    which is how every row ended up labelled per-100g. There is no header to
    read for the correct block, so this adapter reads it by position instead,
    verified against the row width (19 = no separator column) and against
    plausibility (protein*4 <= kcal*1.15) for every row.

Verified against the raw table (per serving): Hamburger 666 kcal / 42 g
protein, Little Hamburger 457 kcal / 24 g, Bacon Cheeseburger 870 kcal / 56 g
— consistent with Five Guys' published composed-item calories elsewhere.
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session, to_float

CHAIN = "five_guys"
SOURCE = "brand PDF (Five Guys UK Nutrition & Allergen Guide)"
LANDING_URL = "https://www.fiveguys.co.uk/nutrition"

_PDF_LINK = re.compile(
    r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_NOT_A_PRODUCT = re.compile(
    r"^(kcal|kj|g|per|total|energy|nutrition|allergen|contains|values|menu)$",
    re.I)


def _find_pdf_url() -> str | None:
    """Pick the UK guide by its anchor text, not by link order."""
    s = session()
    body = None
    try:
        r = s.get(LANDING_URL, timeout=45)
        if r.status_code == 200:
            body = r.text
    except Exception:
        pass
    if body is None:
        pr = fetch_protected(LANDING_URL, timeout=60)
        body = pr.text if pr is not None else None
    if not body:
        return None

    candidates = []
    for m in _PDF_LINK.finditer(body):
        href, text = m.group(1), _TAG.sub("", m.group(2)).strip()
        candidates.append((href, text))

    for href, text in candidates:
        if "uk nutrition" in text.lower():
            return href
    # Fall back to any nutrition/allergen link that isn't the NI/Benelux one.
    for href, text in candidates:
        if re.search(r"allergen|nutrition", href, re.I) and \
                "northern ireland" not in text.lower():
            return href
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
                for row in table:
                    if not row or not row[0]:
                        continue
                    name = re.sub(r"\s+", " ",
                                   str(row[0]).replace("\n", " ")).strip()
                    if len(name) < 3:
                        continue
                    rest = row[1:]
                    if all(c is None or str(c).strip() == "" for c in rest):
                        # Section heading, e.g. "MEAT", "BURGERS", "HOT DOGS".
                        if name.isupper() or " - " in name:
                            category = name.title()
                        continue
                    if len(row) != 19 or _NOT_A_PRODUCT.match(name):
                        continue
                    kcal = to_float(row[2])       # per-serving block: col1=kJ
                    protein = to_float(row[8])    # ...col2=kcal ... col8=protein
                    if kcal is None or protein is None or not _plausible(kcal, protein):
                        continue
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(item(
                        CHAIN, name, SOURCE, source_url, item_id=name,
                        category=category, serving_desc="per serving",
                        kcal=kcal, protein_g=protein,
                        fat_g=to_float(row[3]), carbs_g=to_float(row[5]),
                        salt_g=to_float(row[9])))
    return out


def fetch() -> list[dict]:
    pdf_url = _find_pdf_url()
    if not pdf_url:
        return []
    raw = _fetch_pdf(pdf_url)
    if raw is None:
        return []
    return _parse(raw, pdf_url)
