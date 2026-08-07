"""YO! To Go — the grab-and-go range, from YO!'s "allergen guide" PDF.

Discovery
---------
`yo_to_go` is a genuinely separate range from the `yo_sushi` adapter. That one
reads the live Tenkites menus (`menus.tenkites.com/yosushi/allergenpageyosushi`
+ `/yosushi/kiosk02`), which between them yield 165 items and contain **no**
TOGO recipes at all — the To Go recipes are separately costed ("… TOGO March
22") and are not published to any Tenkites page. `/yosushi/togo`, `/yotogo`,
`/yosushi/yotogo`, `/yosushi/kiosk01`, `/yosushi/kiosk03`,
`/yosushi/allergenpageyotogo` and `/yosushi/supermarkets` were all probed:
they return either the 1157-byte Tenkites 404 shell or "No menus have been
published to this page".

What does exist is a brand-hosted PDF:

    https://yosushi.com/getattachment/bc1cc1c8-6a1e-4755-9607-21fb5ac8e882/
    Allergen-Guide-YO!-To-Go-March.pdf?lang=en-GB

THE TRAP: it is titled "allergen information & dietary guide: YO! to go" and
its first four pages are a pure allergen matrix with rotated, mirrored column
headers and zero numbers. Pages 5-6 are a full
"Nutritional Information Recipe List (values per typical serving)" table with
energy AND protein. Judging this file by its title or its first page is
exactly how a chain gets wrongly written off.

Parsing
-------
`page.extract_tables()` returns nothing (whitespace-aligned layout, no ruling
lines), so this parses `extract_text()` line by line: a name followed by
exactly 12 columns —

    Energy(kcal) Energy(kJ) Fat saturates mono poly Carb Starch Sugars
    Protein Fibre Sodium(mg)

so kcal is index 0 and protein is index 9 (same column order as the YO! Sushi
PDF fallback). Two further traps:

* Long names wrap, leaving a bare "March 22" / "22" on the following line, so
  the captured name is the truncated form; the "TOGO March 22" costing suffix
  is stripped off either way.
* Some cells are a literal "-" (e.g. Classic Catch's Starch), so a
  digits-only column regex silently drops those rows — "-" must be accepted
  as a column token and read as None.

Pages 5 and 6 repeat the row that straddles the page break, hence the dedupe.

Freshness: this file is dated 29 March 2022 and is the only YO!-hosted To Go
nutrition document found. `yosushi.com/yo-to-go` and
`yosushi.com/yotogo-supermarkets` carry no nutrition and link only the generic
`/legal/allergen-information` page.
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session

CHAIN = "yo_to_go"
SOURCE = "YO! To Go allergen information & dietary guide (March 2022)"
SOURCE_URL = ("https://yosushi.com/getattachment/"
              "bc1cc1c8-6a1e-4755-9607-21fb5ac8e882/"
              "Allergen-Guide-YO!-To-Go-March.pdf?lang=en-GB")

#: name, then 12 columns each of which is a number or a literal "-".
_NUM = r"(?:-?\d+\.?\d*|-)"
_ROW_RE = re.compile(rf"^(.+?)\s+((?:{_NUM}\s+){{11}}{_NUM})\s*$")

#: costing suffix on every recipe name ("… TOGO March 22", wrapped variants).
_SUFFIX_RE = re.compile(r"\s*TOGO(\s+March(\s+22)?)?\s*$", re.I)


def _num(tok: str) -> float | None:
    return None if tok == "-" else float(tok)


def _download() -> bytes | None:
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

    raw = _download()
    if raw is None:
        return []

    rows: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").split("\n"):
                m = _ROW_RE.match(line.strip())
                if not m:
                    continue
                name = _SUFFIX_RE.sub("", m.group(1)).strip()
                nums = [_num(tok) for tok in m.group(2).split()]
                kcal, protein = nums[0], nums[9]
                if len(name) < 3 or kcal is None or protein is None:
                    continue
                if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                sodium_mg = nums[11]
                rows.append(item(
                    CHAIN, name, SOURCE, SOURCE_URL,
                    item_id=name, serving_desc="per typical serving",
                    kcal=kcal, protein_g=protein,
                    fat_g=nums[2], carbs_g=nums[6],
                    salt_g=(round(sodium_mg * 2.5 / 1000, 2)
                            if sodium_mg is not None else None),
                ))
    return rows
