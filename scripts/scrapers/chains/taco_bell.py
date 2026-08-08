"""Taco Bell UK — brand menu served through a Nutritionix-hosted table.

Discovery notes:
  * tacobell.co.uk/nutrition-information/ carries no macros itself. Its only
    content is an <iframe> pointing at Nutritionix, so probing the brand
    domain finds a page that mentions nutrition and contains no numbers —
    another instance of "the obvious page isn't the source".
  * The iframe URL serves the whole brand menu as a **static HTML table**, no
    JS required. Columns are positional:
        c0 name, c1 energy kJ, c2 energy kcal, c3 fat, c4 saturates,
        c5 carbohydrate, c6 sugars, c7 fibre, c8 protein, c9 salt
    Note kcal is the *second* energy column — taking the first would report
    kilojoules as calories and quadruple every item's energy.
  * Values are per serving.

TRAP — the name cell is not clean text: it flattens THREE things
    Cell 0 holds ``<a class="nmItem" title="NAME">NAME</a>`` (the real name,
    repeated in a `title` attribute), then a sibling
    ``<a class="moreInfo">[more info]</a>``, and for meal-combo rows a further
    plain-text ingredient list ("Beef BBQ Habanero Burrito, Crunchy Taco
    Supreme w/ Beef, Large Fries…"). Stripping tags and reading the cell as
    text concatenates all three, so "BBQ Habanero Burrito Deluxe Box Plus
    with Fries - Beef (Large)" grows a trailing sentence describing its own
    contents. The `title` attribute on the `nmItem` anchor is the clean name;
    read it directly rather than the cell's flattened text.

Dietary flag source
--------------------
The Nutritionix booklet above carries no diet column, but Taco Bell UK's own
ordering backend does: `order.tacobell.co.uk`'s guest-accessible GraphQL API
(the same Yum! storefront `prices/taco_bell.py` prices from — see that
module's docstring for the full endpoint trace) returns a `brandTags` list
per product, and `Vegetarian` is one of the real values that appears there
(others seen: `Bundle`, `Drink`, `VegConfigAvailable`) — a structured tag
the brand's own backend assigns, not text this project is pattern-matching.
No `Vegan` tag exists on this platform.

JOIN PROBLEM, and why it's only solved for the SAFE cases
    The till's product names and the booklet's item names diverge exactly as
    `prices/taco_bell.py`'s NAME DRIFT section documents (Side-prefixing,
    count-prefixing, sizing spelled out in the booklet but not the till) — a
    few of those drifts are safe to bridge (stripping a leading "Side "/"Nx "
    and appending "(Regular)"/"(Large)"/"(XL)" cannot change what a dish
    physically contains) and are applied here. Left UNRESOLVED: several
    tagged till products (e.g. "Cheese Quesadilla", "Cheesy Roll-Up",
    "Cheesy Topped Nachos") have no obvious booklet counterpart at all — the
    booklet's nearest-sounding rows are meat-inclusive combo boxes ("Grilled
    Cheese Beef/Chicken/Black Bean Quesadilla Box...") that are a different,
    more specific product, not a naming variant of the same one. Guessing
    that link would risk exactly the kind of false positive this project's
    non-negotiable rule exists to prevent, so those rows are left unset.
    Items whose booklet name carries a protein suffix ("- Beef", "- Chicken")
    are never joined to a till tag either, since a product-level tag can't
    speak for a specific protein variant.
"""
from __future__ import annotations

import html
import json
import re

from ..base import item, post_protected, session, to_float

CHAIN = "taco_bell"
SOURCE = "brand menu via Nutritionix (Taco Bell UK)"
SOURCE_URL = "https://www.nutritionix.com/taco-bell-uk/menu/premium"

#: Same Yum! storefront GraphQL API `prices/taco_bell.py` prices from --
#: see "Dietary flag source" above. Used here only for its `brandTags` field.
_TOKEN_URL = "https://order.tacobell.co.uk/v1/oidc/oauth2/token"
_GRAPHQL_URL = "https://order.tacobell.co.uk/tb_uk/storefront/graphql"
_APP_ID = "tb_uk_web"
#: Wimbledon, SW19 1RF (094006) -- same default branch as prices/taco_bell.py;
#: brandTags describe the dish itself, not a per-branch attribute.
_STORE_NUMBER = "094006"

_PRODUCTS_QUERY = """
query Menu($s: ExternalID!, $after: String) {
  storeByNumber(storeNumber: $s) {
    menuByChannel(channel: WEB) {
      products(first: 50, after: $after) {
        pageInfo { hasNextPage }
        edges { cursor node { name brandTags } }
      }
    }
  }
}
"""

_COUNT_PREFIX_RE = re.compile(r"^\d+x\s+", re.I)
_MEAT_WORD_RE = re.compile(r"\b(beef|chicken)\b", re.I)


def _till_vegetarian_names() -> set[str]:
    """Lower-cased till product names carrying the "Vegetarian" brandTag.
    Best-effort: any failure (token/network/schema) returns an empty set
    rather than raising, since this is a supplementary signal, not the
    macro data this adapter exists to fetch."""
    try:
        r = post_protected(_TOKEN_URL,
                           data={"grant_type": "guest", "client_id": _APP_ID},
                           headers={"originatingAppId": _APP_ID,
                                    "Content-Type": "application/x-www-form-urlencoded"})
        if r is None or r.status_code != 200:
            return set()
        token = r.json().get("access_token")
        if not token:
            return set()
        headers = {"Authorization": "Bearer " + token,
                  "originatingAppId": _APP_ID, "Content-Type": "application/json"}

        out: set[str] = set()
        after = None
        for _ in range(20):     # hard cap: a runaway cursor must not hang fetch()
            r = post_protected(_GRAPHQL_URL, data=json.dumps(
                {"query": _PRODUCTS_QUERY,
                 "variables": {"s": _STORE_NUMBER, "after": after}}).encode("utf-8"),
                headers=headers)
            if r is None or r.status_code != 200:
                return out
            payload = r.json()
            if payload.get("errors"):
                return out
            conn = (((payload.get("data") or {}).get("storeByNumber") or {})
                   .get("menuByChannel") or {}).get("products") or {}
            edges = conn.get("edges") or []
            for edge in edges:
                node = edge.get("node") or {}
                if "Vegetarian" in (node.get("brandTags") or []):
                    name = (node.get("name") or "").strip()
                    if name:
                        out.add(name.lower())
                after = edge.get("cursor")
            if not (conn.get("pageInfo") or {}).get("hasNextPage") or not edges:
                return out
        return out
    except Exception:
        return set()


def _booklet_candidates(till_name_lower: str) -> list[str]:
    """Nutritionix-side names that safely correspond to one till product --
    see JOIN PROBLEM above. Additive; every candidate is checked against the
    real booklet name set by the caller, so an over-generated candidate that
    doesn't exist is simply a no-op, never a wrong match."""
    base = till_name_lower
    if base.startswith("side "):
        base = base[5:]
    base = _COUNT_PREFIX_RE.sub("", base)
    return [base, f"{base} (regular)", f"{base} (large)", f"{base} (xl)"]


_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_NAME_TITLE = re.compile(r'class="nmItem"[^>]*\btitle="([^"]*)"', re.I)


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def _name(name_cell_html: str) -> str:
    """The clean item name, from the nmItem anchor's title attribute — see
    the flattened-name trap above. Falls back to the flattened text (trimmed
    at the first "[more info]") if a row's markup ever lacks that anchor."""
    m = _NAME_TITLE.search(name_cell_html)
    if m:
        return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    text = _text(name_cell_html)
    text = re.sub(r"\s*\[?more info\]?.*$", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def fetch() -> list[dict]:
    s = session()
    r = s.get(SOURCE_URL, timeout=60)
    r.raise_for_status()

    till_veg = _till_vegetarian_names()
    # booklet name -> True, built from every safe candidate of every tagged
    # till product (see JOIN PROBLEM above). A name only ever maps to True
    # here, never False, so an accidental double-generation can't conflict.
    booklet_veg: set[str] = set()
    for till_name in till_veg:
        booklet_veg.update(_booklet_candidates(till_name))

    out: list[dict] = []
    seen: set[str] = set()
    for row_html in _ROW.findall(r.text):
        cell_html = _CELL.findall(row_html)
        cells = [_text(c) for c in cell_html]
        if len(cells) < 9:
            continue
        name = _name(cell_html[0])
        kcal = to_float(cells[2])
        protein = to_float(cells[8])
        if not name or kcal is None or protein is None:
            continue
        if kcal <= 0 or protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        if key in booklet_veg:
            vegetarian = True
        elif _MEAT_WORD_RE.search(name):
            vegetarian = False
        else:
            vegetarian = None
        out.append(item(
            CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
            serving_desc="per serving", kcal=kcal, protein_g=protein,
            fat_g=to_float(cells[3]), carbs_g=to_float(cells[5]),
            salt_g=to_float(cells[9]) if len(cells) > 9 else None,
            vegetarian=vegetarian))
    return out
