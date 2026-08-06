"""KFC UK — limited-time offers from their own deals page.

`https://www.kfc.co.uk/kfc-deals` is server-rendered and carries the current
promotions in marketing copy, e.g.

    "Get our 10 Tenders Bucket, featuring 10 of our beautifully crispy
     Tenders, for just £7.99 at your local KFC."

Parsing prose is inherently lossy, so this adapter is deliberately narrow: it
extracts only patterns it can turn into a *resolvable composition* — a
quantity, a product word that matches a scraped menu row, and a price. Anything
it can't parse confidently is skipped rather than approximated, because a
bundle with invented macros would top the ranking by construction.

The output still goes through `model.expand`, which re-checks that every
component resolves against real scraped nutrition before the offer is
published.
"""
from __future__ import annotations

import datetime
import html
import re

from ...scrapers.base import session
from ..model import Component, Offer

DEALS_URL = "https://www.kfc.co.uk/kfc-deals"
CHAIN = "kfc"
SOURCE = "KFC UK deals page"

#: "10 Tenders Bucket ... for just £7.99" / "6 Wings for £5.99"
_OFFER_RE = re.compile(
    r"(?P<qty>\d{1,2})\s+(?P<product>Tenders?|Wings?|Mini Fillets?|"
    r"Fillets?|Pieces?|Boneless)\b[^.£]{0,120}?"
    r"(?:for\s+(?:just\s+)?)?£(?P<price>\d{1,2}\.\d{2})",
    re.I)

#: Map the marketing word to the menu row that carries per-unit macros.
_PRODUCT_TO_MENU = {
    "tender": "Tender (per piece",
    "tenders": "Tender (per piece",
    "wing": "Wings (per piece",
    "wings": "Wings (per piece",
    "mini fillet": "Mini Fillet",
    "mini fillets": "Mini Fillet",
    "piece": "Original Recipe Chicken (per piece",
    "pieces": "Original Recipe Chicken (per piece",
}


def _visible_text(raw_html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_html,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\\u003c", " ").replace("\\u003e", " ")
    return re.sub(r"\s+", " ", text)


def fetch(s=None) -> list[Offer]:
    s = s or session()
    try:
        r = s.get(DEALS_URL, timeout=30)
        r.raise_for_status()
    except Exception:
        return []

    text = _visible_text(r.text)
    today = datetime.date.today().isoformat()
    offers: dict[str, Offer] = {}

    for m in _OFFER_RE.finditer(text):
        qty = int(m.group("qty"))
        product = m.group("product").lower()
        price = float(m.group("price"))
        matcher = _PRODUCT_TO_MENU.get(product)
        # Guard against nonsense parses from unrelated prose (delivery fees,
        # order thresholds) that happen to sit near a price.
        if not matcher or not (1 <= qty <= 30) or not (1.0 <= price <= 40.0):
            continue

        title = f"{qty} {m.group('product').title()} — £{price:.2f} deal"
        offer_id = f"kfc_{qty}_{product.rstrip('s')}_{price:.2f}".replace(".", "")
        offers.setdefault(offer_id, Offer(
            offer_id=offer_id, chain_id=CHAIN, title=title, price_gbp=price,
            components=(Component(matcher, qty),),
            source=SOURCE, source_url=DEALS_URL, last_verified=today,
            valid_to=None, availability="national", basis="scraped",
            notes="parsed from KFC's deals page copy"))

    return list(offers.values())
