"""Wimpy UK — brand nutrition PDF, parsed from text lines.

Discovery notes:
  * Source: the brand's own S3-hosted "Nutrition Guide.pdf" (2 pages,
    per-portion values).
  * `generic_pdf` returns 0 rows here, for two compounding reasons:
    headers are rotated 90 degrees (pdfplumber yields them mirrored, e.g.
    ")lack( ygrenE" for "Energy (kcal)"), and `extract_tables()` splits each
    menu section into a values table *plus* a separate allergen table, so no
    single table has both a name column and a header the mapper recognises.
  * Parsed instead from `extract_text()` lines matching
    "<name> <9 numbers>" — kJ, kcal, fat, saturates, carbs, sugars, fibre,
    protein, salt. kcal is the second number and protein the eighth.
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session, to_float

CHAIN = "wimpy"
SOURCE = "brand PDF (Wimpy UK Nutrition Guide)"
SOURCE_URL = ("https://wimpy-uk.s3-eu-west-2.amazonaws.com/static/"
              "Nutrition%20Guide.pdf")

#: name followed by exactly nine numeric columns
_ROW = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9'’&()\-/\. ]{2,60}?)\s+"
    r"(?P<nums>(?:\d[\d.,]*\s+){8}\d[\d.,]*)\s*$")


def _pdf_bytes() -> bytes | None:
    s = session()
    try:
        r = s.get(SOURCE_URL, timeout=90)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    pr = fetch_protected(SOURCE_URL, timeout=120)
    return pr.content if pr is not None and pr.content[:4] == b"%PDF" else None


def fetch() -> list[dict]:
    import pdfplumber

    raw = _pdf_bytes()
    if raw is None:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").split("\n"):
                m = _ROW.match(line.strip())
                if not m:
                    continue
                nums = [to_float(n) for n in m.group("nums").split()]
                if len(nums) != 9:
                    continue
                kcal, protein = nums[1], nums[7]
                name = m.group("name").strip()
                if kcal is None or protein is None or kcal <= 0:
                    continue
                if protein * 4 > kcal * 1.15:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(item(
                    CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
                    serving_desc="per portion", kcal=kcal, protein_g=protein,
                    fat_g=nums[2], carbs_g=nums[4], salt_g=nums[8]))
    return out
