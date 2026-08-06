"""Slim Chickens UK — schema.org JSON-LD on their TenKites menu portal.

Discovery
---------
slimchickens.co.uk has no nutrition of its own; its footer links "Dietary
Information" to https://menus.tenkites.com/brg/slimchickensall (TenKites is
the allergen/menu platform Boparan Restaurant Group uses). That page is only
a location picker — the *core* menu lives at

    https://menus.tenkites.com/brg/slimscore?sitecode=SLM

and that page embeds one `<script type="application/ld+json">` block: a
schema.org `Menu` covering the whole catalogue, every `MenuItem` carrying
`NutritionInformation` with `calories`, `proteinContent`, `fatContent`,
`carbohydrateContent`, `saturatedFatContent`.

Traps
-----
* Stopping at /brg/slimchickensall and concluding "allergens only" is the
  mistake here — the nutrition is one hop further in, on the per-menu page.
  Sibling portals exist for other estates (`slimshubs`, `slimsbelfast`) if a
  site-specific menu is ever needed.
* Values are strings with units ("303 calories", "43 grams"), so the leading
  number has to be pulled out; sugars are often an empty " grams".
* Everything is rounded to whole grams at source, so sauces all read 1 g
  protein. That is the brand's rounding, not a parse error.
* `MenuItem`s repeat across sections (212 blocks -> 103 distinct rows);
  deduped on name + macros.
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected, item, session, to_float

CHAIN = "slim_chickens"
SOURCE = "Slim Chickens UK dietary portal (TenKites, schema.org JSON-LD menu)"
SOURCE_URL = "https://menus.tenkites.com/brg/slimscore?sitecode=SLM"

_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_NUM = re.compile(r"([\d.]+)")


def _num(v):
    m = _NUM.search(str(v or ""))
    return to_float(m.group(1)) if m else None


def _walk(node, out: list):
    if isinstance(node, dict):
        if node.get("@type") == "MenuItem" and isinstance(node.get("nutrition"), dict):
            out.append(node)
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def fetch() -> list[dict]:
    r = session().get(SOURCE_URL, timeout=90)
    body = r.text if r.status_code == 200 else None
    if body is None:
        pr = fetch_protected(SOURCE_URL)
        body = pr.text if pr is not None else ""

    products: list = []
    for block in _LD.findall(body):
        try:
            _walk(json.loads(block), products)
        except ValueError:
            continue

    out: list[dict] = []
    seen: set = set()
    for p in products:
        name = (p.get("name") or "").strip()
        n = p["nutrition"]
        kcal, protein = _num(n.get("calories")), _num(n.get("proteinContent"))
        if not name or not kcal or protein is None:
            continue
        if protein * 4 > kcal * 1.15:
            continue
        key = (name.lower(), kcal, protein)
        if key in seen:
            continue
        seen.add(key)
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name, serving_desc="per serving",
            kcal=kcal, protein_g=protein,
            carbs_g=_num(n.get("carbohydrateContent")),
            fat_g=_num(n.get("fatContent")),
        ))
    return out
