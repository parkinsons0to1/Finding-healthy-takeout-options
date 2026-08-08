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

Dietary flag source
--------------------
A SEPARATE PDF, the "Allergen Information — England, Scotland, Wales and
Jersey" guide (identified the same way as the nutrition PDF: by the
``card-selection-allergens.*`` analytics id, then by its own cover text,
since three other regional allergen PDFs are linked from the same page and
one of them is a red herring — a 14-page "QSR – Brixton Rd & Finsbury Park"
variant that would silently mix in a different, smaller estate). Its table
has a "DOES IT CONTAIN?" allergen block and, separately, an "ARE THESE
SUITABLE FOR?" block with "Vegetarian" / "Vegan" / "Coeliacs" columns, marked
with a Wingdings-style checkmark glyph (the private-use codepoint U+F0FC)
when suitable and a BLANK cell (never ambiguous -- checked: every data cell
in both columns is exactly one of the checkmark, an empty string, or None,
and None only ever occurs on whole-row section headings like "SIDES", never
on a real dish) when not.
Confirms real data, not name-echoing: "Margherita" -> vegetarian only (real
mozzarella); "Vegan Margherita"/"Margherita Vegan" -> both.

JOIN PROBLEM — the two PDFs do not share a naming convention
    Exact lower-cased name match against the nutrition table's 340 rows
    finds only 45: the allergen guide uses far coarser dish names (one entry,
    "Bruschetta Originale 'PizzaExpress'", covers what the nutrition table
    lists as separate GF/Dine-Out/Sharer rows) and inverts word order for
    vegan pizzas ("Vegan Margherita" vs. the nutrition table's "Margherita
    Vegan"). A second pass strips a small, explicit set of decorator words
    that add portion/format variants without changing what's IN the dish
    (gf, "gluten free", "dine out (exclusive)", sharer, new(-recipe),
    "deliveroo exclusive", light, leggera, the "'PizzaExpress'" brand mark,
    baked) plus punctuation, and matches on the SET of remaining words (order-
    independent, which is what fixes "Vegan Margherita" / "Margherita Vegan"
    without a hand-written alias). A token-set is only trusted when every
    allergen-guide row sharing it agrees on both flags (checked: 0 of 150
    distinct token-sets disagree) — brings the match rate to 116/340. The
    rest (mostly dips, dressings, and salad/bowl "with GF Dough Balls" /
    "with dough sticks" suffixes the allergen guide doesn't break out
    separately) are left unset rather than guessed at.
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session, to_float
from ..generic_pdf import _find_header

#: Allergen guide — "Allergen Information, England, Scotland, Wales and
#: Jersey" — see "Dietary flag source" above. A SEPARATE PDF from
#: SOURCE_URL's nutrition table.
_ALLERGEN_PDF_URL = ("https://cdn.sanity.io/files/lj3txstz/production/"
                      "02b1f194304b52bb420ae8bd0db34a411eac1a90.pdf")

_DECOR_RE = re.compile(
    r"\b(gf|gluten free|dine.?out exclusive|dine.?out|exclusive|sharer|"
    r"new recipe|new|deliveroo exclusive|light|leggera|pizzaexpress|baked)\b",
    re.I)
_PUNCT_RE = re.compile(r"[\[\]()'‘’\"“”.,\-–&]")


def _core_tokens(name: str) -> frozenset[str]:
    """Order-independent "what's actually in this dish" token set -- see
    JOIN PROBLEM above."""
    n = _PUNCT_RE.sub(" ", name)
    n = _DECOR_RE.sub(" ", n)
    return frozenset(t for t in n.lower().split() if t)


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


def _diet_flags(raw: bytes) -> dict[str, tuple[bool, bool]]:
    """lower-cased dish name -> (vegetarian, vegan), from the allergen
    guide's "ARE THESE SUITABLE FOR?" block -- see "Dietary flag source"
    above. A SEPARATE PDF from the nutrition table this module otherwise
    reads."""
    import pdfplumber

    out: dict[str, tuple[bool, bool]] = {}
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table:
                    continue
                header, hidx = None, None
                for i, row in enumerate(table[:3]):
                    if row and "DISHES" in [str(c).strip() for c in row]:
                        header, hidx = row, i
                        break
                if header is None:
                    continue
                try:
                    vi = header.index("Vegetarian")
                    vgi = header.index("Vegan")
                except ValueError:
                    continue
                for row in table[hidx + 1:]:
                    if not row or not row[0]:
                        continue
                    if vi >= len(row) or row[vi] is None:
                        continue    # a whole-row section heading, not a dish
                    name = re.sub(r"\s+", " ", str(row[0]).replace("\n", " ")).strip().lower()
                    if not name:
                        continue
                    veg = row[vi] != ""
                    vgn = vgi < len(row) and row[vgi] not in (None, "")
                    out[name] = (veg, vgn)
    return out


def _fetch_diet_flags() -> tuple[dict[str, tuple[bool, bool]], dict[frozenset, tuple[bool, bool] | None]]:
    """(exact-name map, token-set map). The token-set map only carries an
    entry where every allergen-guide row sharing that token set agrees on
    both flags -- see JOIN PROBLEM above; a disagreement maps to None so a
    future ambiguous case fails closed (unset) rather than picking one
    arbitrarily."""
    raw = _fetch_pdf(_ALLERGEN_PDF_URL)
    if raw is None:
        return {}, {}
    by_name = _diet_flags(raw)
    grouped: dict[frozenset, set[tuple[bool, bool]]] = {}
    for name, flags in by_name.items():
        grouped.setdefault(_core_tokens(name), set()).add(flags)
    by_tokens = {ts: (next(iter(vals)) if len(vals) == 1 else None)
                for ts, vals in grouped.items()}
    return by_name, by_tokens


def _parse(raw: bytes) -> list[dict]:
    import pdfplumber

    diet_by_name, diet_by_tokens = _fetch_diet_flags()
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
                    flags = diet_by_name.get(key)
                    if flags is None:
                        flags = diet_by_tokens.get(_core_tokens(name))
                    vegetarian, vegan = flags if flags else (None, None)
                    out.append(item(CHAIN, name, SOURCE, SOURCE_URL,
                                    item_id=name, category=category or None,
                                    serving_desc="per serving",
                                    kcal=kcal, protein_g=protein,
                                    vegetarian=vegetarian, vegan=vegan, **extra))
    return out


def fetch() -> list[dict]:
    raw = _fetch_pdf(SOURCE_URL)
    if raw is None:
        return []
    return _parse(raw)
