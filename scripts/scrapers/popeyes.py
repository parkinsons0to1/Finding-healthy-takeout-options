"""Popeyes UK — public ordering-platform API (Azure Front Door).

Discovery notes (2026-07-28):
  * API base found in popeyesuk.com Angular bundle:
      https://pe-uk-ordering-api-fd-eecsdkg6btfeg0cc.z01.azurefd.net
  * /en/ordering/menu/allergensandnutritions -> every product with per-100g
    AND per-serving macros, allergens, vegetarian/vegan flags. No auth.
  * /api/v2/restaurants -> all UK stores with coordinates (store locator).
  * Known data-quality issue: per-serving kcal on some multi-piece items
    (e.g. "3 Classic Tenders & a dip" at 233 kcal when 1 tender = 156) is
    wrong at the source. Rows where kcal < 0.8 x (protein*4) are flagged
    'implausible-kcal' so the scoring engine can exclude or derive instead.
"""
from __future__ import annotations

from .base import item, session, to_float

BASE = "https://pe-uk-ordering-api-fd-eecsdkg6btfeg0cc.z01.azurefd.net"
NUTRITION_URL = f"{BASE}/en/ordering/menu/allergensandnutritions"
RESTAURANTS_URL = f"{BASE}/api/v2/restaurants"

CHAIN = "popeyes"
SOURCE = "live-scrape Popeyes UK ordering API"


def _block(it, which):
    for blk in it.get("nutritions", []):
        if blk.get("category") == which:
            return {n["name"]: to_float(n["value"]) for n in blk.get("nutritions", [])}
    return {}


def fetch() -> list[dict]:
    s = session()
    data = s.get(NUTRITION_URL, timeout=40).json()
    out = []
    for cat in data.get("data", []):
        cat_name = cat.get("categoryShortName")
        for p in cat.get("items", []):
            per = _block(p, "per-serving") or _block(p, "per-100")
            kcal, prot = per.get("energy-kCal"), per.get("protein")
            flags = []
            if kcal and prot and kcal < prot * 4 * 0.8:
                flags.append("implausible-kcal")   # brand data error, see module docstring
            allergens = sorted({a for g in p.get("allergensGroups", [])
                                if g.get("type") == "contains"
                                for a in g.get("allergens", [])})
            out.append(item(
                CHAIN, p.get("productName", ""), SOURCE, NUTRITION_URL,
                item_id=p.get("externalId"), category=cat_name,
                kcal=kcal, protein_g=prot,
                carbs_g=per.get("carbohydrates"), fat_g=per.get("fats"),
                salt_g=per.get("salt"),
                vegetarian=bool(p.get("isSuitableForVegetarians")),
                vegan=bool(p.get("isSuitableForVegans")),
                allergens=allergens, quality_flags=flags,
            ))
    return out


def fetch_outlets() -> list[dict]:
    s = session()
    data = s.get(RESTAURANTS_URL, timeout=40).json()
    return [{
        "chain_id": CHAIN, "store_id": r.get("id"), "slug": r.get("slug"),
        "name": r.get("storeName"), "address": r.get("storeAddress"),
        "lat": r.get("storeLocation", {}).get("coordinates", {}).get("latitude"),
        "lng": r.get("storeLocation", {}).get("coordinates", {}).get("longitude"),
        "source_url": RESTAURANTS_URL,
    } for r in data.get("data", [])]
