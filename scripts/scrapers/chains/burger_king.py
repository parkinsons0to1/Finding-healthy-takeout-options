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
small.

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
* `vegan` / `vegetarian` top-level booleans DO NOT EXIST on this dataset —
  the docstring here previously claimed they did (true of some other RBI
  market, not `prod_bk_gb`; `count(*[_type=="item" && defined(vegan)])` is 0,
  same for `vegetarian`). The old code read them anyway via
  `bool(row.get("vegetarian"))`, which silently turned the missing field into
  a hard `False` for all 375 items — actively wrong for the ~23 genuinely
  meat-free items, worse than leaving it unset.

Dietary flag source
--------------------
No boolean field exists, but every item carries `productHierarchy`, BK's own
internal menu-category hierarchy (not free text we're pattern-matching —
it's a structured field the brand's backend assigns). `productHierarchy.L2
== "VEGGIE BURGER"` is BK UK's own curated grouping for its meat-free burger
range (Plant-Based Whopper, Vegan Royale, Halloumi King Burger, etc.) —
verified by hand: all 23 items with nutrition data in that category are
genuinely vegetarian, no meat/fish item is miscategorised into it. Used as
the sole source of `vegetarian=True` here.

No comparable structured field distinguishes vegan within that category
(several names say "Vegan"/"Plant-based", but that's still just the item's
own display name, and the project's rule is to never infer a positive from
name text) — so `vegan` is left unset for everything except the two Halloumi
items, which the name confirms contain dairy (`vegan=False`, safe direction).
`vegetarian`/`vegan` are also set `False` wherever the name contains an
unambiguous meat/fish word (Beef, Chicken, Bacon, Ham, Turkey, Sausage,
Pepperoni, Fish, Prawn) — a false negative here is safe (project convention).
Everything else (drinks, most sides/desserts/sauces) is left unset: BK's
category hierarchy doesn't mark those as vegetarian/vegan either way, and
guessing would be exactly the invention this project avoids.
"""
from __future__ import annotations

import re
import urllib.parse

from ..base import item, session, to_float

CHAIN = "burger_king"
SOURCE = "Burger King UK Sanity content API (project czqk28jt, dataset prod_bk_gb)"

_PROJECT = "czqk28jt"
_DATASET = "prod_bk_gb"
_GROQ = (
    '*[_type=="item" && defined(nutritionWithModifiers.calories)]'
    '{"name":name.en,"l2":productHierarchy.L2,'
    '"n":nutritionWithModifiers}'
)

#: Unambiguous meat/fish words -> vegetarian=False, vegan=False with
#: reasonable confidence (false negative only, the project's safe direction).
_MEAT_RE = re.compile(
    r"\b(beef|chicken|bacon|ham|turkey|sausage|pepperoni|fish|prawn|pork)\b",
    re.I)
#: Dairy words within BK's own "VEGGIE BURGER" category -> vegan=False
#: (vegetarian stays True from the category, just not vegan).
_DAIRY_RE = re.compile(r"\bhalloumi\b", re.I)
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

        veggie_category = row.get("l2") == "VEGGIE BURGER"
        if veggie_category:
            vegetarian: bool | None = True
            vegan: bool | None = False if _DAIRY_RE.search(name) else None
        elif _MEAT_RE.search(name):
            vegetarian = False
            vegan = False
        else:
            vegetarian = None
            vegan = None

        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL,
            item_id=name, serving_desc="per serving",
            kcal=kcal, protein_g=protein,
            carbs_g=to_float(n.get("carbohydrates")), fat_g=to_float(n.get("fat")),
            salt_g=to_float(n.get("salt")),
            vegetarian=vegetarian, vegan=vegan,
        ))
    return out
