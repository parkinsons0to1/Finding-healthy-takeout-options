"""Wingstop UK — allergen & nutrition PDF with a *transposed* layout.

**Caveat: this source is stale, and that is visible in the data.** Read this
before trusting Wingstop numbers.

Discovery notes:
  * www.wingstop.co.uk is an Angular SPA with no macros in its HTML. Its
    allergen page reads `download_url` from /assets/i18n/en.json, which in the
    current build points at a **Saudi staging asset**
    (staging.wingstop.sa/.../ALLERGEN_INFORMATION.pdf) — the shipped UK build
    links the wrong file.
  * The genuine UK document is
    https://www.wingstop.co.uk/content/wingstop-uk-allergen-info-v2.pdf, which
    no longer resolves on the live host; the copy that parses is an Internet
    Archive snapshot (document dated May 2022, snapshot March 2023).

**Why the generic PDF parser returns nothing here.** Wingstop's tables are
transposed relative to every other chain: nutrients run down the rows
(Energy, Fat, … Protein) and *servings* run across the columns ("Per 100g",
"Per Serving (8 Pieces) 370g", "(10 Pieces)", "(12 Pieces)"). There is no
header row containing "kcal" and "protein" as separate columns, so the
column-mapping approach finds no header at all. The product name isn't in the
table either — it's the page heading ("WINGS").

Pages 0–6 are allergen matrices with no macros; nutrition starts around page 7.
Energy cells combine both units in one string ("2615kJ/625kcal"), so kcal is
extracted specifically rather than taking the first number, which would report
kilojoules as calories.
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session, to_float

CHAIN = "wingstop"
SOURCE_DATE = "2022-05 (archived 2023-03)"
LIVE_URL = "https://www.wingstop.co.uk/content/wingstop-uk-allergen-info-v2.pdf"
ARCHIVE_URL = ("https://web.archive.org/web/20230319072145if_/"
               "https://www.wingstop.co.uk/content/wingstop-uk-allergen-info-v2.pdf")
SOURCE = f"brand PDF (Wingstop UK allergen & nutrition, {SOURCE_DATE})"

_KCAL = re.compile(r"([\d.]+)\s*kcal", re.I)
_NUM = re.compile(r"([\d.]+)")
#: Column headers describing a real portion, e.g. "Per Serving (10 Pieces) 462g"
_SERVING_COL = re.compile(r"per\s+serving", re.I)
_PER_100G = re.compile(r"per\s*100\s*g", re.I)


def _pdf_bytes() -> bytes | None:
    s = session()
    for url in (LIVE_URL, ARCHIVE_URL):
        try:
            r = s.get(url, timeout=90)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return r.content
        except Exception:
            pass
        pr = fetch_protected(url, timeout=120)
        if pr is not None and pr.content[:4] == b"%PDF":
            return pr.content
    return None


#: Lines that are table furniture rather than a product heading.
_HEADING_NOISE = re.compile(
    r"^(per\s|nutritional\s+information\b|typical values|energy|fat\b|"
    r"of which|carbohydrate|protein|salt|fibre|then add|naked\b|allergen)", re.I)


def _page_product(page) -> str | None:
    """The product/section name is the page's first real heading line.

    Only the first nutrition page carries the banner "NUTRITIONAL
    INFORMATION"; the rest lead straight with their section name ("BONELESS",
    "TENDERS", "BIG FLAVOUR BURGER", "PLATTERS"). So anchoring on the banner
    finds one page and mis-parses the others — an earlier attempt produced
    items named "Per 100G" and "Fat 0.7G 0G" that way.
    """
    lines = [ln.strip() for ln in (page.extract_text() or "").split("\n") if ln.strip()]
    for line in lines[:3]:
        if line.upper() == "NUTRITIONAL INFORMATION":
            continue
        if _HEADING_NOISE.match(line):
            continue
        if 2 < len(line) < 60 and not re.search(r"\d\s*[gG]\b|\d{3,}", line):
            return line.title()
    return None


def _row_values(table, label_pattern: str) -> list[str] | None:
    for row in table:
        if row and row[0] and re.match(label_pattern, str(row[0]).strip(), re.I):
            return [str(c or "") for c in row]
    return None


def fetch() -> list[dict]:
    import pdfplumber

    raw = _pdf_bytes()
    if raw is None:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "nutritional information" not in text.lower():
                continue
            product = _page_product(page)
            if not product:
                continue

            for table in page.extract_tables():
                if not table or not table[0]:
                    continue
                headers = [str(c or "") for c in table[0]]
                energy = _row_values(table, r"energy")
                protein = _row_values(table, r"protein")
                fat = _row_values(table, r"fat")
                carbs = _row_values(table, r"carbohydrate")
                if not energy or not protein:
                    continue

                for col in range(1, len(headers)):
                    header = headers[col].replace("\n", " ").strip()
                    # Per-100g columns are not a purchasable portion; skip them
                    # so a 257 kcal/100g row can't masquerade as a serving.
                    if not header or _PER_100G.search(header):
                        continue
                    if not _SERVING_COL.search(header):
                        continue
                    if col >= len(energy) or col >= len(protein):
                        continue

                    kcal_m = _KCAL.search(energy[col])
                    prot_m = _NUM.search(protein[col])
                    if not kcal_m or not prot_m:
                        continue
                    kcal = to_float(kcal_m.group(1))
                    prot = to_float(prot_m.group(1))
                    if kcal is None or prot is None or kcal <= 0:
                        continue
                    if prot * 4 > kcal * 1.15:
                        continue

                    portion = re.sub(r"per\s+serving", "", header, flags=re.I).strip()
                    name = f"{product} {portion}".strip()
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)

                    def _cell(row, idx):
                        if not row or idx >= len(row):
                            return None
                        m = _NUM.search(row[idx])
                        return to_float(m.group(1)) if m else None

                    out.append(item(
                        CHAIN, name, SOURCE, ARCHIVE_URL, item_id=name,
                        serving_desc=header, kcal=kcal, protein_g=prot,
                        fat_g=_cell(fat, col), carbs_g=_cell(carbs, col)))
    return out
