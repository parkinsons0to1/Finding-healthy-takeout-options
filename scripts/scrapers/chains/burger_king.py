"""Burger King UK — Sanity CMS content API (the site's own backing store).

Discovery
---------
burgerking.co.uk is an RBI whitelabel React SPA: the served HTML is a shell
with `<div id="root">` and no macros anywhere. The way in is a detail the
shell leaks in its own `<head>` — the Open Graph image is served from
`https://cdn.sanity.io/images/czqk28jt/...`, which names the Sanity project id
(`czqk28jt`) that the storefront reads its menu from. Sanity's query API is a
public, unauthenticated GET:

    https://<project>.api.sanity.io/v1/data/query/<dataset>?query=<GROQ>

Datasets are per-market and are NOT discoverable from the API; they have to be
guessed. `prod_bk_gb` is the UK one (`prod_bk_uk` 404s — the trap here is
assuming "uk").

Shape
-----
Menu items are `_type == "item"`. Nutrition lives on
`nutritionWithModifiers` — `calories`, `proteins`, `fat`, `carbohydrates`,
`salt`, `sugar`, `fiber`, `sodium`, `weight` — per serving. Names are
localised objects, so `name.en` is projected server-side to keep the response
small. `vegan` / `vegetarian` are top-level booleans on the item.

Traps
-----
* 452 items carry `calories`; only 419 also carry `proteins`. Drinks and
  sauces are the ones missing protein, and they are dropped by the gate below
  rather than defaulted to 0.
* The catalogue contains duplicates (the same product exists under several
  documents, e.g. two "Truffle Loaded King Fries"), plus point-of-sale-only
  rows prefixed "fs" (e.g. "fsLarge Fanta Zero"). Deduped on lower-cased name.
* Values are not rounded at source (e.g. 581.47 kcal); that is the brand's own
  precision, not a parsing artefact.
"""
from __future__ import annotations

import urllib.parse

from ..base import item, session, to_float

CHAIN = "burger_king"
SOURCE = "Burger King UK Sanity content API (project czqk28jt, dataset prod_bk_gb)"

_PROJECT = "czqk28jt"
_DATASET = "prod_bk_gb"
_GROQ = (
    '*[_type=="item" && defined(nutritionWithModifiers.calories)]'
    '{"name":name.en,"vegan":vegan,"vegetarian":vegetarian,'
    '"n":nutritionWithModifiers}'
)
SOURCE_URL = (f"https://{_PROJECT}.api.sanity.io/v1/data/query/{_DATASET}"
              f"?query={urllib.parse.quote(_GROQ)}")


def fetch() -> list[dict]:
    data = session().get(SOURCE_URL, timeout=90).json()
    out: list[dict] = []
    seen: set[str] = set()
    for row in data.get("result", []):
        name = (row.get("name") or "").strip()
        n = row.get("n") or {}
        kcal, protein = to_float(n.get("calories")), to_float(n.get("proteins"))
        if not name or not kcal or protein is None:
            continue
        if protein * 4 > kcal * 1.15:      # misread / bad source row
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name, serving_desc="per serving",
            kcal=kcal, protein_g=protein,
            carbs_g=to_float(n.get("carbohydrates")), fat_g=to_float(n.get("fat")),
            salt_g=to_float(n.get("salt")),
            vegetarian=bool(row.get("vegetarian")), vegan=bool(row.get("vegan")),
        ))
    return out
