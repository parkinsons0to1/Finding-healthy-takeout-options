"""Meal-deal product candidates, with per-pack macros.

Nutrition comes from Open Food Facts (free, open, strong UK supermarket
coverage). The catch is that OFF stores values **per 100 g**, while a meal deal
is eaten per *pack* — a 100 g figure ranks a dense snack above a large sandwich
that actually delivers more protein. So everything is converted to per-pack
using `product_quantity`/`serving_quantity` where available, and products where
we cannot establish a pack size are dropped rather than guessed at.

Slot assignment (main / snack / drink) is derived from OFF category tags. It is
deliberately conservative: a product that doesn't clearly belong to a slot is
skipped, because a wrong slot produces a bundle the shop won't actually sell you
at the deal price.
"""
from __future__ import annotations

import re
import time

from ..scrapers.base import now_iso, session

OFF_SEARCH = "https://world.openfoodfacts.org/api/v2/search"
FIELDS = ("code,product_name,brands,quantity,product_quantity,serving_quantity,"
          "nutriments,categories_tags,labels_tags")

#: OFF category tags that map onto meal-deal slots.
SLOT_CATEGORIES = {
    "main": ["en:sandwiches", "en:wraps", "en:salads", "en:sushi",
             "en:prepared-salads", "en:pasta-salads"],
    "snack": ["en:crisps", "en:chips-and-fries", "en:nuts", "en:fruit-snacks",
              "en:chocolate-bars", "en:biscuits", "en:yogurts",
              "en:protein-bars", "en:popcorn"],
    "drink": ["en:waters", "en:sodas", "en:fruit-juices", "en:iced-teas",
              "en:energy-drinks", "en:milk-drinks", "en:smoothies"],
}

#: Meal-deal items are **single-serve**, which is a strong filter Open Food
#: Facts itself cannot apply: OFF happily returns 454 g packs of raw quarter
#: pounders under "sandwiches" and 300 g biscuit multipacks under "biscuits",
#: none of which any shop will sell you inside a meal deal. Pack sizes outside
#: these ranges are rejected rather than corrected.
PLAUSIBLE_PACK_G = {"main": (120, 330), "snack": (18, 100), "drink": (200, 600)}

#: Sanity bounds on energy density (kcal per 100 g). Open Food Facts contains
#: per-serving figures mistakenly entered as per-100g, which produce nonsense
#: like a 300 g salad at 1155 kcal — and that nonsense wins the optimiser,
#: because the optimiser is looking for exactly the extreme values.
MAX_KCAL_PER_100G = {"main": 320, "snack": 650, "drink": 120}
#: Likewise for protein: nothing sold in a meal deal is 40 g protein per 100 g.
MAX_PROTEIN_PER_100G = 35.0
#: Per-pack protein ceilings. A squash listed at 19 g protein per bottle is an
#: OFF per-100g/per-serving mix-up; the ceiling keeps such rows from winning
#: the optimiser, which by design hunts for the highest-protein candidate.
MAX_PROTEIN_PER_PACK = {"main": 60.0, "snack": 30.0, "drink": 12.0}

#: Categories that appear under a slot's tags but are never meal-deal stock.
EXCLUDE_CATEGORIES = {
    "en:raw-meats", "en:meats", "en:fresh-meats", "en:beef", "en:poultry",
    "en:frozen-foods", "en:meal-kits", "en:pizzas", "en:cakes",
    "en:breakfast-cereals", "en:spreads", "en:breads", "en:flours",
    "en:tortillas", "en:condiments", "en:sauces", "en:groceries",
}

#: Bulk/ingredient formats that slip through category tags.
_NOT_SINGLE_SERVE = re.compile(
    r"\b(wraps|tortillas|rolls|baps|buns|loaf|bag|sharing|family|bulk|"
    r"in\s+shell|shells|burgers|patties|grills|fillets|steaks|pain)\b", re.I)

#: Multipack giveaways in the product name — "6 pack", "x4", "multipack".
_MULTIPACK = re.compile(r"\b(\d+\s*(pack|pk)|multipack|x\s?\d+\b|sharing)\b", re.I)


def _pack_grams(p: dict, slot: str) -> float | None:
    for key in ("product_quantity", "serving_quantity"):
        try:
            v = float(p.get(key))
        except (TypeError, ValueError):
            continue
        lo, hi = PLAUSIBLE_PACK_G[slot]
        if lo <= v <= hi:
            return v
    return None


def _per_pack(p: dict, slot: str) -> dict | None:
    n = p.get("nutriments") or {}
    kcal100 = n.get("energy-kcal_100g")
    prot100 = n.get("proteins_100g")
    if kcal100 is None or prot100 is None:
        return None
    try:
        if float(kcal100) > MAX_KCAL_PER_100G[slot] or float(prot100) > MAX_PROTEIN_PER_100G:
            return None
    except (TypeError, ValueError):
        return None
    grams = _pack_grams(p, slot)
    if grams is None:
        return None
    f = grams / 100.0
    protein_pack = round(float(prot100) * f, 1)
    if protein_pack > MAX_PROTEIN_PER_PACK[slot]:
        return None
    return {
        "kcal": round(float(kcal100) * f, 1),
        "protein_g": protein_pack,
        "carbs_g": round(float(n.get("carbohydrates_100g") or 0) * f, 1),
        "fat_g": round(float(n.get("fat_100g") or 0) * f, 1),
        "pack_g": grams,
    }


def _dietary(p: dict) -> dict:
    labels = set(p.get("labels_tags") or [])
    return {
        "vegan": "en:vegan" in labels,
        "vegetarian": "en:vegetarian" in labels or "en:vegan" in labels,
        "halal": "en:halal" in labels,
        "kosher": "en:kosher" in labels,
    }


def _get_with_retry(s, params, attempts: int = 4) -> list[dict] | None:
    """Open Food Facts is a free community API and rate-limits readily.

    Returns the product list, or None if every attempt failed — distinct from
    an empty list, which genuinely means "no more results".
    """
    delay = 1.5
    for _ in range(attempts):
        try:
            r = s.get(OFF_SEARCH, params=params, timeout=45)
            if r.status_code == 200:
                return r.json().get("products", [])
        except Exception:
            pass
        time.sleep(delay)
        delay *= 2
    return None


def fetch_slot_products(retailer_id: str, slot: str, s=None,
                        page_size: int = 100, pages: int = 2) -> list[dict]:
    """Candidate products for one retailer and one meal-deal slot."""
    s = s or session()
    out: list[dict] = []
    for category in SLOT_CATEGORIES[slot]:
        for page in range(1, pages + 1):
            params = {"brands_tags": retailer_id.replace("_", "-"),
                      "categories_tags": category,
                      "countries_tags": "en:united-kingdom",
                      "fields": FIELDS, "page_size": page_size, "page": page}
            products = _get_with_retry(s, params)
            if products is None:
                continue        # transient failure on this page; try the next
            if not products:
                break           # genuinely no more results for this category
            for p in products:
                name = (p.get("product_name") or "").strip()
                if not name or _MULTIPACK.search(name) or _NOT_SINGLE_SERVE.search(name):
                    continue
                if set(p.get("categories_tags") or []) & EXCLUDE_CATEGORIES:
                    continue
                macros = _per_pack(p, slot)
                if not macros:
                    continue
                out.append({
                    "retailer_id": retailer_id, "slot": slot,
                    "barcode": p.get("code"), "name": name,
                    "brand": p.get("brands"), "quantity": p.get("quantity"),
                    **macros, **_dietary(p),
                    "source": "Open Food Facts", "fetched_at": now_iso(),
                    "source_url": f"https://world.openfoodfacts.org/product/{p.get('code')}",
                })
            time.sleep(0.7)   # be polite to a free community API
    # De-duplicate by barcode, keeping the first (highest-ranked) hit.
    seen, unique = set(), []
    for p in out:
        if p["barcode"] in seen:
            continue
        seen.add(p["barcode"])
        unique.append(p)
    return unique


def fetch_all(retailer_id: str, s=None) -> dict[str, list[dict]]:
    s = s or session()
    return {slot: fetch_slot_products(retailer_id, slot, s) for slot in SLOT_CATEGORIES}
