"""Chains served by the generic PDF adapter — configuration, not code.

Each entry is a chain whose nutrition PDF parses with `generic_pdf`. Adding
another chain is a line here plus a discovery run, which is the whole point of
having a generic parser: bespoke adapters (KFC, Subway, Papa John's) should be
the exception for genuinely odd layouts.

`url` may be a direct PDF or a page whose nutrition PDF link we resolve at
fetch time — several chains version the filename by month
("...-JULY-2026-v2.pdf"), so pinning the exact file guarantees a silent break
within weeks.
"""
from __future__ import annotations

import re

from .base import fetch_protected, session
from .generic_pdf import fetch_from_pdf

#: chain_id -> (landing page or PDF, link-matching hint, label)
PDF_CHAINS: dict[str, tuple[str, str, str]] = {
    "five_guys": (
        "https://www.fiveguys.co.uk/nutrition",
        r"allergen|nutrition",
        "brand PDF (Five Guys UK allergen & nutrition)"),
    "starbucks": (
        "https://www.starbucks.co.uk/nutrition",
        r"allergen|nutrition",
        "brand PDF (Starbucks UK allergen book)"),
    "krispy_kreme": (
        "https://krispykreme.co.uk/media/wysiwyg/PDFs/"
        "UK_Drinks_Allergen_Nutrition_Book_310726.pdf",
        r"allergen|nutrition",
        "brand PDF (Krispy Kreme UK nutrition book)"),
}

_PDF_LINK = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)


def resolve_pdf_url(page_url: str, hint: str) -> str | None:
    """If `page_url` is already a PDF, use it; otherwise find the best link."""
    if page_url.lower().endswith(".pdf"):
        return page_url
    s = session()
    body = None
    try:
        r = s.get(page_url, timeout=45)
        if r.status_code == 200:
            body = r.text
    except Exception:
        pass
    if body is None:
        pr = fetch_protected(page_url, timeout=60)
        body = pr.text if pr is not None else None
    if not body:
        return None

    links = [m for m in _PDF_LINK.findall(body) if re.search(hint, m, re.I)]
    if not links:
        return None
    link = links[0]
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return "/".join(page_url.split("/")[:3]) + link
    return link


def fetch_chain(chain_id: str) -> list[dict]:
    page_url, hint, label = PDF_CHAINS[chain_id]
    pdf_url = resolve_pdf_url(page_url, hint)
    if not pdf_url:
        return []
    return fetch_from_pdf(chain_id, pdf_url, label)


def make_adapter(chain_id: str):
    """Build a module-like adapter object for run_all's registry."""
    class _Adapter:
        CHAIN = chain_id

        @staticmethod
        def fetch() -> list[dict]:
            return fetch_chain(chain_id)
    _Adapter.__name__ = f"{chain_id}_pdf_adapter"
    return _Adapter


ADAPTERS = {chain_id: make_adapter(chain_id) for chain_id in PDF_CHAINS}
