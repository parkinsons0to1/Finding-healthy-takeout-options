"""Papa John's UK — official Allergen & Nutrition PDF (Cloudflare-protected).

Discovery notes (2026-07-28):
  * https://www.papajohns.co.uk/static/assets/pdfs/nutritional-information.pdf
    is the brand-published guide (86 pages, "JUNE26" edition). The whole
    domain 403s to plain `requests` because Cloudflare fingerprints the TLS
    handshake, so this adapter uses `base.fetch_protected` — still plain HTTP,
    just a browser-shaped handshake.
  * Layout is one pizza per page, with three aligned tables:
      table[1] SIZE & CRUST rows   ("Authentic Thin Crust - Medium")
      table[2] VALUES PER 100G     [kcal, kJ, protein, fat, sat, carbs, ...]
      table[3] VALUES PER SLICE    [kcal total, kcal/portion, total g, ...]
    Whole-pizza macros are derived as `per_100g x total_product_g / 100`,
    which is why the two tables have to be read together.

Emitted as whole pizzas *and* per slice. Whole-pizza rows matter for
protein-per-£ (you buy a pizza, not a slice); per-slice rows keep the numbers
honest for anyone eating a portion.
"""
from __future__ import annotations

import io
import re

from .base import fetch_protected, item, to_float

PDF_URL = "https://www.papajohns.co.uk/static/assets/pdfs/nutritional-information.pdf"
CHAIN = "papa_johns"
SOURCE = "brand-published PDF (Papa John's UK nutritional-information.pdf)"

#: Pages before this are contents/allergen preamble, not per-product tables.
_FIRST_PRODUCT_PAGE = 6
_SIZE_ROW = re.compile(r"(thin crust|original base|stuffed crust|gluten free|"
                       r"sourdough|calzone|papadia)", re.I)


#: Header lines that look like product names but aren't.
_NOT_A_PRODUCT = re.compile(
    r"values per|allergen|nutrition|contents|ingredient|papa john|"
    r"^june|vegetarian|vegan|toppings", re.I)


def _page_product_name(page) -> str | None:
    """The pizza name is the second line of the page header ("CHEESE & TOMATO")."""
    text = page.extract_text() or ""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    for line in lines[:4]:
        if _NOT_A_PRODUCT.search(line):
            continue
        if re.match(r"^[A-Z0-9][A-Z0-9 &'\-\.]{3,40}$", line):
            return line.title()
    return None


def _numeric_rows(table) -> list[list[str]]:
    """Rows whose first cell parses as a number — i.e. the data, not headers."""
    return [r for r in table if r and to_float(r[0]) is not None]


def fetch() -> list[dict]:
    import pdfplumber

    response = fetch_protected(PDF_URL)
    if response is None:
        raise RuntimeError("Papa John's PDF fetch failed (Cloudflare); "
                           "install curl_cffi or check the impersonation profiles")

    out: list[dict] = []
    with pdfplumber.open(io.BytesIO(response.content)) as pdf:
        for page in pdf.pages[_FIRST_PRODUCT_PAGE:]:
            product = _page_product_name(page)
            if not product:
                continue
            tables = page.extract_tables()
            if len(tables) < 4:
                continue

            sizes = [(r[0] or "").replace("\n", " ").strip() for r in tables[1]
                     if r and r[0] and _SIZE_ROW.search(str(r[0]))]
            per100 = _numeric_rows(tables[2])
            per_slice = _numeric_rows(tables[3])
            # The size labels and the per-100g rows are separate tables that
            # only line up positionally. If their lengths disagree, the page
            # didn't extract cleanly and pairing them by index would attach the
            # wrong macros to a pizza — skip rather than guess.
            if not sizes or not per100 or len(sizes) != len(per100):
                continue

            for i, size in enumerate(sizes):
                kcal100, prot100 = to_float(per100[i][0]), to_float(per100[i][2])
                fat100, carb100 = to_float(per100[i][3]), to_float(per100[i][5])
                if kcal100 is None or prot100 is None:
                    continue
                # Plausibility gate on the *source* values. Pizza runs roughly
                # 200-320 kcal and 8-20 g protein per 100 g; anything outside
                # that means the columns were misread, and a misread row wins
                # the ranking precisely because it looks extraordinary.
                if not (100 <= kcal100 <= 400) or not (2 <= prot100 <= 30):
                    continue

                total_kcal = total_g = slices = None
                if i < len(per_slice):
                    row = per_slice[i]
                    total_kcal = to_float(row[0])
                    total_g = to_float(row[2]) if len(row) > 2 else None
                    slices = to_float(row[5]) if len(row) > 5 else None

                name = f"{product} — {size}"
                if total_g:
                    factor = total_g / 100.0
                    out.append(item(
                        CHAIN, name, SOURCE, PDF_URL,
                        item_id=name, category="pizza (whole)",
                        serving_desc=f"whole pizza, {total_g:.0f}g"
                                     + (f", {slices:.0f} slices" if slices else ""),
                        kcal=total_kcal or round(kcal100 * factor, 1),
                        protein_g=round(prot100 * factor, 1),
                        fat_g=round(fat100 * factor, 1) if fat100 is not None else None,
                        carbs_g=round(carb100 * factor, 1) if carb100 is not None else None,
                        vegetarian=None, vegan=None))

                    if slices and slices > 0:
                        out.append(item(
                            CHAIN, f"{name} (1 slice)", SOURCE, PDF_URL,
                            item_id=f"{name}|slice", category="pizza (slice)",
                            serving_desc=f"1 of {slices:.0f} slices",
                            kcal=round((total_kcal or kcal100 * factor) / slices, 1),
                            protein_g=round(prot100 * factor / slices, 1),
                            vegetarian=None, vegan=None))
    return out
