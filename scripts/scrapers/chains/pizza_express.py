"""PizzaExpress — "Nutritional Information, England, Wales & Scotland" (PDF).

Discovery
---------
The landing page is https://www.pizzaexpress.com/allergens-and-nutritionals.
It is a Next.js page whose "Download PDF" cards point at Sanity-hosted assets:

    https://cdn.sanity.io/files/lj3txstz/production/<40-hex>.pdf

Twelve such PDFs are linked and the filenames are content hashes, so the only
way to tell them apart is the ``data-analytics-id`` on the enclosing anchor:
``card-selection-nutritionals.*`` vs ``...-allergens.*`` vs
``...-ingredients-list.*``. Four are nutritionals; the one used here (24 pages,
340 rows) is the England/Wales/Scotland core menu. The other three are smaller
regional/menu variants (53, 292 and 33 rows).

TRAP 1 — the brand site 403s
    Both pizzaexpress.com and the Sanity CDN reject a plain ``requests`` GET
    (and WebFetch). ``fetch_protected`` is required for both the page and the
    PDF.

TRAP 2 — TWO nutrition blocks per row, and the page says "PER 100g"
    Each table is 19 columns wide:
        col 0      dish name
        cols 1-9   PER PORTION  (kcal, kJ, fat, sat, carb, sugar, fibre,
                                 protein, salt)
        cols 10-18 PER 100g     (same nine, repeated)
    The generic parser binds the FIRST kcal/protein pair, which is the correct
    per-portion one — but it then stamps ``serving_desc="per 100g"`` because
    the *page text* contains the words "PER 100g" (that string is the second
    block's spanning header). The flag is wrong; the numbers are per portion.
    This adapter therefore reads the columns itself and labels them honestly.
    Verified against the raw table: Hot Honey Dough Balls = 415 kcal / 9.8 g
    protein per portion (per 100 g it would be 280 / 6.6).

TRAP 3 — do not pair by index
    Name and nutrition live in the SAME row here, so there is no positional
    pairing to get wrong. If a future revision splits them, skip rather than
    zip: an earlier pizza adapter mis-attached macros exactly that way.

Basis is per portion throughout; pizzas are whole-pizza portions (a Romana is
one dish, not a shared pizza), so ``serving_desc`` says "per serving".
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session, to_float
from ..generic_pdf import _find_header

CHAIN = "pizza_express"
SOURCE = "PizzaExpress Nutritional Information (England, Wales & Scotland)"
SOURCE_URL = ("https://cdn.sanity.io/files/lj3txstz/production/"
              "230f6a921a100e32ad47e5f9f92e1fdbd01fef23.pdf")

_NOT_A_PRODUCT = re.compile(
    r"^(kcal|kj|g|per|total|energy|nutrition|allergen|contains|values|menu)$", re.I)


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


def _parse(raw: bytes) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if len(table) < 2:
                    continue
                header = _find_header(table)
                if not header:
                    continue
                cols, hidx = header
                # The header row's first cell names the menu section, e.g.
                # "Starters - Doughballs", "Pizzas - Romana".
                category = re.sub(r"\s+", " ",
                                  str(table[hidx][0] or "").replace("\n", " ")).strip()
                for row in table[hidx + 1:]:
                    if not row or not row[0]:
                        continue
                    name = re.sub(r"\s+", " ",
                                  str(row[0]).replace("\n", " ")).strip()
                    if len(name) < 3 or _NOT_A_PRODUCT.match(name):
                        continue
                    if cols["kcal"] >= len(row) or cols["protein_g"] >= len(row):
                        continue
                    kcal = to_float(row[cols["kcal"]])
                    protein = to_float(row[cols["protein_g"]])
                    if kcal is None or protein is None:
                        continue
                    if kcal <= 0 or protein < 0:
                        continue
                    if protein * 4 > kcal * 1.15:
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
                    out.append(item(CHAIN, name, SOURCE, SOURCE_URL,
                                    item_id=name, category=category or None,
                                    serving_desc="per serving",
                                    kcal=kcal, protein_g=protein, **extra))
    return out


def fetch() -> list[dict]:
    raw = _fetch_pdf(SOURCE_URL)
    if raw is None:
        return []
    return _parse(raw)
