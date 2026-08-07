"""Frankie & Benny's — per-dish macros from the Tenkites schema.org JSON-LD.

Discovery, and the trap that matters most here
----------------------------------------------
frankieandbennys.com/allergy embeds a Tenkites menu at

    https://menus.tenkites.com/thebigtg/frankiebennys        <- NO nutrition

That officially-linked template renders allergens only: zero occurrences of
"protein" in the served HTML. Stopping there is exactly how you conclude
"Frankie & Benny's publishes allergen-only data", and it is wrong. Sibling
templates on the SAME Tenkites unit (``thebigtg``, the Big Table Group tenant)
carry the macros:

    frankiebennys02  <- used here: GB "MAIN MENU", with BREAKFAST / LUNCH /
                        DESSERTS / DRINKS / EVENING / KIDS sub-menus
    frankiebennys05/07/08/09/10/11/12   also populated
    zfbtest02/03/04/05                  also populated; zfbtest04 is
                                        "FRANKIE & BENNYS NI CORE MENU JUN 2025"
                                        (Northern Ireland, ~174 items)

So the source is the brand's own menu platform — just not the URL the brand
links to. Templates were found by enumerating ``frankiebennys<NN>`` and
``zfbtest<NN>`` against the unit; the ones with no menu return a Tenkites 404
page, and ones with an empty menu return a ~6 KB stub.

Format
------
Unlike wagamama (same platform!), the macros here are NOT in the visible
allergen grid — they are only in the schema.org JSON-LD blocks::

    {"@type":"MenuItem","name":"Giant Mozzarella Stick", ...,
     "nutrition":{"@type":"NutritionInformation","calories":"446 calories",
                  "carbohydrateContent":"27 grams","fatContent":"30 grams",
                  "proteinContent":"16 grams", ...}}

Values are strings with units ("446 calories"), so the number is extracted
rather than cast. ``MenuSection.name`` gives the category, and
``suitableForDiet`` gives vegetarian/vegan. Note TGI Fridays UK is on the same
platform and emits ``NutritionInformation`` objects that are EMPTY — the
presence of the key proves nothing, the values must be checked.
"""
from __future__ import annotations

import html
import json
import re

from ..base import fetch_protected, item, session

CHAIN = "frankie_bennys"
SOURCE = "brand menu platform (Frankie & Benny's, Tenkites JSON-LD)"
SOURCE_URL = "https://menus.tenkites.com/thebigtg/frankiebennys02"
#: Tried in order if the primary template stops carrying nutrition. zfbtest04
#: is the Northern Ireland core menu — a different estate, so it is last.
FALLBACK_URLS = (
    "https://menus.tenkites.com/thebigtg/frankiebennys07",
    "https://menus.tenkites.com/thebigtg/frankiebennys08",
    "https://menus.tenkites.com/thebigtg/zfbtest04",
)

_JSONLD = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _get(url: str) -> str | None:
    s = session()
    try:
        r = s.get(url, timeout=120)
        if r.status_code == 200 and r.content:
            return r.content.decode(r.encoding or "utf-8", errors="replace")
    except Exception:
        pass
    pr = fetch_protected(url, timeout=150)
    if pr is not None and pr.content:
        return pr.content.decode("utf-8", errors="replace")
    return None


def _amount(value) -> float | None:
    """'446 calories' / '16 grams' -> float. Values are strings with units."""
    if value is None:
        return None
    m = _NUM.search(str(value).replace(",", ""))
    return float(m.group(0)) if m else None


def _collect(node, section: str | None, found: list[dict]) -> None:
    """Walk the JSON-LD graph collecting MenuItems with their section name."""
    if isinstance(node, dict):
        if node.get("@type") == "MenuItem":
            nutrition = node.get("nutrition") or {}
            name = html.unescape(str(node.get("name") or "")).strip()
            diet = str(node.get("suitableForDiet") or "").lower()
            found.append({
                "name": name,
                "kcal": _amount(nutrition.get("calories")),
                "protein_g": _amount(nutrition.get("proteinContent")),
                "carbs_g": _amount(nutrition.get("carbohydrateContent")),
                "fat_g": _amount(nutrition.get("fatContent")),
                "category": section,
                "vegan": True if "vegandiet" in diet else None,
                "vegetarian": True if "vegetariandiet" in diet or "vegandiet" in diet else None,
            })
        inner = node.get("name") if node.get("@type") == "MenuSection" else section
        for value in node.values():
            _collect(value, inner, found)
    elif isinstance(node, list):
        for value in node:
            _collect(value, section, found)


def _parse(raw: str) -> list[dict]:
    found: list[dict] = []
    for block in _JSONLD.findall(raw):
        try:
            _collect(json.loads(block.strip()), None, found)
        except Exception:
            continue          # a malformed block must not lose the others
    return found


def fetch() -> list[dict]:
    records: list[dict] = []
    source_url = SOURCE_URL
    for url in (SOURCE_URL, *FALLBACK_URLS):
        raw = _get(url)
        if not raw:
            continue
        parsed = _parse(raw)
        # Only accept a template that actually carries values — the linked
        # template and TGI's emit MenuItems whose nutrition object is empty.
        if sum(1 for r in parsed if r["kcal"] and r["protein_g"] is not None) >= 5:
            records, source_url = parsed, url
            break

    out: list[dict] = []
    seen: set[str] = set()
    for rec in records:
        name, kcal, protein = rec["name"], rec["kcal"], rec["protein_g"]
        # Plausibility gate: reject rows missing a name, kcal or protein, and
        # rows where protein alone would exceed the stated calories.
        if not name or not kcal or protein is None:
            continue
        if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item(
            CHAIN, name, SOURCE, source_url,
            item_id=name,
            category=rec.get("category"),
            serving_desc="per serving",
            kcal=kcal,
            protein_g=protein,
            carbs_g=rec.get("carbs_g"),
            fat_g=rec.get("fat_g"),
            vegetarian=rec.get("vegetarian"),
            vegan=rec.get("vegan"),
        ))
    return out
