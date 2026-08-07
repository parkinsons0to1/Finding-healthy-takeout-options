"""Chipotle UK — nutrition calculator PDF.

Discovery notes (2026-08):
  * The real source is the PDF behind https://www.chipotle.co.uk/nutrition-calculator
    — a full per-ingredient nutrition table (Chicken 27.3 g protein / 185 kcal,
    Barbacoa 29.7 g / 154 kcal), not an allergen sheet.
  * Bulk discovery originally matched a *menu* PDF on the same site, which has
    no macros. That produced zero parsed rows, and the zero was then written up
    as "Chipotle publishes allergen-only PDFs". It doesn't. The lesson is in
    `chains/discover.py`: a probe that finds nothing must report "unresolved",
    never a reason.
  * The calculator page is client-rendered and the PDF link is not present in
    the served HTML, so the live URL can't yet be resolved over plain HTTP.
    Until it can, we parse a cached copy of the brand's own PDF.

**This file is a cached brand document, so it goes stale.** `SOURCE_DATE`
records when it was captured, and `fetch()` re-attempts the live page first so
the cache is a fallback rather than the plan.
"""
from __future__ import annotations

import pathlib
import re

from .base import fetch_protected, session
from .generic_pdf import fetch_from_pdf, parse_pdf

CHAIN = "chipotle"
PAGE_URL = "https://www.chipotle.co.uk/nutrition-calculator"
CACHED_PDF = (pathlib.Path(__file__).resolve().parents[2]
              / "data" / "sources" / "chipotle_nutrition_calculator.pdf")
SOURCE_DATE = "2026-08"
SOURCE = (f"brand PDF (Chipotle UK nutrition calculator, cached {SOURCE_DATE})")

_PDF_LINK = re.compile(r'["\']([^"\']*\.pdf[^"\']*)["\']', re.I)


def _try_live() -> list[dict]:
    """Attempt the live page in case the PDF link becomes server-rendered."""
    s = session()
    body = None
    try:
        r = s.get(PAGE_URL, timeout=40)
        if r.status_code == 200:
            body = r.text
    except Exception:
        pass
    if body is None:
        pr = fetch_protected(PAGE_URL, timeout=60)
        body = pr.text if pr is not None else None
    if not body:
        return []

    for link in _PDF_LINK.findall(body):
        if not re.search(r"nutrition|calculator", link, re.I):
            continue
        url = link
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://www.chipotle.co.uk" + url
        items = fetch_from_pdf(CHAIN, url, "brand PDF (Chipotle UK, live)")
        if items:
            return items
    return []


def fetch() -> list[dict]:
    live = _try_live()
    if live:
        return live
    if not CACHED_PDF.exists():
        return []
    return parse_pdf(CACHED_PDF.read_bytes(), CHAIN, SOURCE, PAGE_URL)
