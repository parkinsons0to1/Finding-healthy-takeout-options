"""Subway UK & ROI — official nutrition PDF, link discovered from the
nutrition page (the filename changes with each revision).

Discovery notes (2026-08, re-verified — the 2026-07-28 URL below has since
404'd, confirming the "filename changes with each revision" warning was not
theoretical):
  * https://www.subway.com/en-gb/menunutrition/nutrition embeds the current
    PDF as an absolute URL on a DIFFERENT host and path shape than the
    2026-07-28 discovery: ``media.subway.com/dam/urn:aaid:aem:<uuid>/
    original/as/UKI_IngredientsNutritionalInformationJune2026.pdf`` (was
    ``www.subway.com/en-gb/media/emea/europe/uk/nutrition/2026/...``). The
    link-finding regex matches on the "IngredientsNutritional...pdf"
    filename fragment, not a path prefix, so it survives the CDN host and
    path moving again. Requires ``fetch_protected`` now (plain ``requests``
    no longer gets the page).
  * Table columns: [name, serving_g, kJ, kcal, fat, sat, carbs, sugars,
    fibre, protein, salt]. Values are per 6-inch sub / per listed serving.
  * Historic note: Subway has published separate "Standard" and "Halal"
    nutrition PDFs (halal stores swap some meats) — per-store halal status.

Dietary flag source
--------------------
A SEPARATE PDF, linked from the same nutrition page, titled "Allergen
Information" (filename fragment "AllergenInformationUKI.pdf") — an
ingredient-level matrix whose own legend reads "Y — Ingredients suitable
for vegetarian / vegan diet". Table extraction shows this is really TWO
adjacent columns (index 2 = vegetarian, index 3 = vegan), not one combined
symbol: confirmed by "Honey & Oat Bread" -> Y in col 2 only (contains
honey, not vegan) and "Italian White Bread" -> Y in both (verified against
several more items the same way — cheese-bearing breads/cookies are
consistently vegetarian-only, egg/plant items are consistently both).

TRAP — this PDF renders every SECTION-HEADING and several DATA rows with
    every glyph doubled and the whole string reversed (an artefact of
    whatever tool produced it — "AAlllleerrggeenn IInnffoorrmmaattiioonn"
    decodes to "Allergen Information"), and pages 1-3 additionally MERGE
    adjacent two-column layout text into single garbled table cells
    ("SFohroetdlodnegd CMhouzrzraorella..."). Rather than write a decoder for
    a rendering bug that could change PDF-to-PDF, corrupted rows are
    recognised (a name containing a newline, or an isolated capital letter
    stranded mid-word — the reversed-doubling's telltale) and DROPPED. This
    sacrifices real rows on the corrupted pages rather than risk decoding
    one dish's flags onto a different dish's name.

JOIN — ingredient-level allergen names vs. this PDF's own item names
    Exact lower-cased match, then (since e.g. "Rotisserie-Style Chicken" vs.
    "Rotisserie Style Chicken" differ only by punctuation/hyphenation) a
    punctuation-stripped word-SET match, trusted only where every allergen
    row sharing that word-set agrees (checked: 0 collisions across 76 clean
    rows). Coverage is modest (13 of 137 nutrition rows) because the
    allergen guide is a smaller, more clipped ingredient list than the
    nutrition table's finished-item names ("B.M.T & Cheese",
    "BBQ Pulled Pork") — most of those simply have no single-ingredient
    counterpart to join to, and are correctly left unset rather than
    decomposed into components and guessed at.
"""
from __future__ import annotations

import io
import re

from .base import fetch_protected, item, session, to_float

PAGE_URL = "https://www.subway.com/en-gb/menunutrition/nutrition"
CHAIN = "subway"
SOURCE = "brand-published PDF (Subway UK nutrition)"

_SECTION_NAMES = ("subs", "salads", "wraps", "sides", "breakfast", "drinks",
                  "extras", "cookies")

#: A name containing a newline, or a stray capital stranded mid-word, is the
#: allergen PDF's reversed-doubled-text corruption -- see "TRAP" above.
_CORRUPT_NAME_RE = re.compile(r"[a-z][A-Z]{1,2}[a-z]")

_PDF_LINK_RE = re.compile(r'href="([^"]*IngredientsNutritional[^"]*\.pdf)"', re.I)
_ALLERGEN_LINK_RE = re.compile(r'href="([^"]*AllergenInformation[^"]*\.pdf)"', re.I)


def _page_html() -> str:
    r = fetch_protected(PAGE_URL, timeout=60)
    if r is None or not r.text:
        raise RuntimeError("Subway nutrition page could not be fetched")
    return r.text


def _find_pdf_url(html: str, pattern: re.Pattern) -> str | None:
    m = pattern.search(html)
    if not m:
        return None
    url = m.group(1)
    if url.startswith("/"):
        url = "https://www.subway.com" + url
    return url


def _pdf_bytes(url: str) -> bytes | None:
    s = session()
    try:
        r = s.get(url, timeout=60)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    r = fetch_protected(url, timeout=90)
    return r.content if r is not None and r.content[:4] == b"%PDF" else None


def _tok(name: str) -> frozenset[str]:
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if w)


def _diet_flags(raw: bytes) -> dict[str, tuple[bool, bool]]:
    """lower-cased ingredient name -> (vegetarian, vegan) -- see "Dietary
    flag source" above."""
    import pdfplumber

    out: dict[str, tuple[bool, bool]] = {}
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or not row[0] or len(row) < 4:
                        continue
                    name = row[0]
                    if "\n" in name or _CORRUPT_NAME_RE.search(name):
                        continue    # reversed-doubled-text corruption, see TRAP
                    name = name.strip()
                    if len(name) < 3:
                        continue
                    veg = bool((row[2] or "").strip())
                    vgn = bool((row[3] or "").strip())
                    key = name.lower()
                    if key in out and out[key] != (veg, vgn):
                        continue    # disagreeing duplicate -- drop, don't guess
                    out[key] = (veg, vgn)
    return out


def _fetch_diet_flags() -> tuple[dict[str, tuple[bool, bool]], dict[frozenset, tuple[bool, bool] | None]]:
    try:
        html = _page_html()
        url = _find_pdf_url(html, _ALLERGEN_LINK_RE)
        if not url:
            return {}, {}
        raw = _pdf_bytes(url)
        if raw is None:
            return {}, {}
        by_name = _diet_flags(raw)
    except Exception:
        return {}, {}
    grouped: dict[frozenset, set[tuple[bool, bool]]] = {}
    for name, flags in by_name.items():
        grouped.setdefault(_tok(name), set()).add(flags)
    by_tokens = {ts: (next(iter(vals)) if len(vals) == 1 else None)
                for ts, vals in grouped.items()}
    return by_name, by_tokens


def fetch() -> list[dict]:
    import pdfplumber

    html = _page_html()
    pdf_url = _find_pdf_url(html, _PDF_LINK_RE)
    if not pdf_url:
        raise RuntimeError("Subway nutrition PDF link not found on page")
    raw = _pdf_bytes(pdf_url)
    if raw is None:
        raise RuntimeError("Subway nutrition PDF could not be downloaded")

    diet_by_name, diet_by_tokens = _fetch_diet_flags()

    out, section = [], None
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for pg in pdf.pages:
            for tbl in pg.extract_tables():
                for r in tbl:
                    if not r or not r[0]:
                        continue
                    name = r[0].replace("\n", " ").strip()
                    if name.lower() in _SECTION_NAMES:
                        section = name
                        continue
                    kcal = to_float(r[3]) if len(r) > 9 else None
                    prot = to_float(r[9]) if len(r) > 9 else None
                    if kcal is None or prot is None:
                        continue
                    flags = diet_by_name.get(name.lower())
                    if flags is None:
                        flags = diet_by_tokens.get(_tok(name))
                    vegetarian, vegan = flags if flags else (None, None)
                    out.append(item(
                        CHAIN, name, SOURCE, pdf_url,
                        item_id=f"{section or 'menu'}:{name}", category=section,
                        serving_desc=f"{r[1]}g serving" if r[1] else None,
                        kcal=kcal, protein_g=prot,
                        fat_g=to_float(r[4]), carbs_g=to_float(r[6]),
                        salt_g=to_float(r[10]) if len(r) > 10 else None,
                        vegetarian=vegetarian, vegan=vegan,
                    ))
    return out
