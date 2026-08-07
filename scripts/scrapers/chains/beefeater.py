"""Beefeater (Whitbread) — per-portion macros from the brand allergy & nutrition guides.

Discovery
---------
beefeater.co.uk/en-gb/allergy-nutrition is the index. Older menus there are
PDFs; the current ones are static HTML pages at

    https://www.beefeater.co.uk/en-gb/allergy-nutrition/bg-<id>-web

Each dish on those pages carries a per-portion ``table.NandATable`` with
Energy (kJ / kcal), Fat, Saturates, Carbohydrates, Sugars, Protein, Salt —
full macros, not allergens only. Brewers Fayre uses the identical template
(same parent, Whitbread), so the parsing lives in ``_whitbread.py``.

Trap: the ``bg-<id>`` numbers are content-management ids that change every
menu cycle, so a pinned URL breaks silently within months. This adapter
re-reads the index page each run and parses every guide it links, falling back
to the pinned core-menu URL only if the index cannot be read. Dishes are
deduped by name across guides (main / breakfast / NGCI / Christmas), first
occurrence winning.
"""
from __future__ import annotations

from ..base import fetch_protected, item, session
from . import _whitbread

CHAIN = "beefeater"
SOURCE = "brand site (Beefeater allergy & nutrition guide, Whitbread)"
INDEX_URL = "https://www.beefeater.co.uk/en-gb/allergy-nutrition"
#: Fallback if the index page cannot be read: Autumn Winter 25 core menu.
FALLBACK_URL = "https://www.beefeater.co.uk/en-gb/allergy-nutrition/bg-1482392-web"
#: Whitbread prefixes Beefeater guide ids with "bg-".
LINK_PREFIX = "bg-"
#: Sanity cap so a template change cannot turn one run into hundreds of fetches.
MAX_GUIDES = 12


def _get(url: str) -> str | None:
    s = session()
    try:
        r = s.get(url, timeout=90)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    pr = fetch_protected(url, timeout=120)
    return pr.text if pr is not None else None


def _guide_urls() -> list[str]:
    body = _get(INDEX_URL)
    if body:
        urls = _whitbread.resolve_menu_urls(INDEX_URL, body, LINK_PREFIX)
        if urls:
            return urls[:MAX_GUIDES]
    return [FALLBACK_URL]


def fetch() -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    for url in _guide_urls():
        body = _get(url)
        if not body:
            continue
        for rec in _whitbread.parse_guide(body):
            kcal = rec.get("kcal")
            protein = rec.get("protein_g")
            name = rec.get("name")
            # Plausibility gate: drop anything without a name, kcal or protein,
            # and anything whose protein alone would exceed the stated
            # calories (the signature of a misread column).
            if not name or not kcal or protein is None:
                continue
            if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item(
                CHAIN, name, SOURCE, url,
                item_id=name,
                category=rec.get("category"),
                serving_desc="per portion",
                kcal=kcal,
                protein_g=protein,
                carbs_g=rec.get("carbs_g"),
                fat_g=rec.get("fat_g"),
                salt_g=rec.get("salt_g"),
                vegetarian=rec.get("vegetarian"),
                vegan=rec.get("vegan"),
            ))
    return out
