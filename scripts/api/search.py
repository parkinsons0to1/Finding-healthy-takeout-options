"""The MacroMeter search pipeline: a location in, a ranked answer out.

    postcode / coordinates
        -> location            (geo.location)
        -> nearby outlets      (FSA FHRS, national)
        -> chain identification + branch match against store indexes
        -> menu items          (data/db/{chain}.json, scraped nutrition)
        -> halal resolution    (halal.resolver, per outlet, evidence-tiered)
        -> prices + discounts  (chain price table; estimates flagged as such)
        -> scoring             (api.scoring)

Everything is keyed off the user's actual location — no city is special.
"""
from __future__ import annotations

import functools
import json
import pathlib

from ..geo.location import find_outlets, resolve_location
from ..halal.cache import HalalCache
from ..halal.resolver import resolve as resolve_halal
from ..scrapers.base import session
from .discounts import DISCOUNTS, best_discount
from .prices import price_for
from .scoring import ScoredItem, rank

DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "db"

#: Shared across requests so a search is a lookup, not a crawl.
_DISK_CACHE = HalalCache()


@functools.lru_cache(maxsize=32)
def load_menu(chain_id: str) -> list[dict]:
    """Scraped nutrition for a chain, from the scraper pipeline's output."""
    path = DB / f"{chain_id}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return list(data.get("items", {}).values())


#: Rows that are genuine nutrition records but not things you can order.
#: Subway's PDF lists every filling and topping ("Ham (2 slices)", "Roast
#: Chicken Breast Strips") alongside the actual subs; scoring those as meals
#: puts 29-kcal slices of turkey on the leaderboard.
_INGREDIENT_WORDS = ("premix", "do not use", "sauce", "dressing", "slices",
                     "strips", "portion", "scoop", "topping", "cheese triangle")
#: Subway's own section names for buyable products.
_SUBWAY_PRODUCT_SECTIONS = {"subs", "salads", "wraps", "breakfast", "sides"}


def _is_orderable(item: dict) -> bool:
    name = (item.get("name") or "").lower()
    if not item.get("kcal") or item.get("protein_g") is None:
        return False
    if "implausible-kcal" in (item.get("quality_flags") or []):
        return False
    if any(w in name for w in _INGREDIENT_WORDS):
        return False
    if item.get("chain_id") == "subway":
        category = (item.get("category") or "").strip().lower()
        if category not in _SUBWAY_PRODUCT_SECTIONS:
            return False
    return True


def search(postcode: str | None = None, lat: float | None = None,
           lng: float | None = None, radius_miles: float = 1.0,
           diet: set[str] | None = None, min_protein_share: float = 0.35,
           strict_halal: bool = True, sort_by: str = "protein_per_pound",
           limit: int = 25, resolve_halal_live: bool = True,
           halal_cache: dict | None = None) -> dict:
    """Full search for a location. Returns a JSON-serialisable payload."""
    s = session()
    loc = resolve_location(postcode=postcode, lat=lat, lng=lng, s=s)
    if not loc:
        return {"error": "could not resolve that location", "results": []}

    outlets = find_outlets(loc["lat"], loc["lng"], radius_miles, s)
    chain_outlets = [o for o in outlets if o["kind"] == "chain"]

    halal_cache = halal_cache if halal_cache is not None else {}
    scored: list[ScoredItem] = []
    outlets_used: list[dict] = []

    unranked_chains: dict[str, dict] = {}

    for outlet in chain_outlets:
        chain_id = outlet["chain_id"]
        menu = [i for i in load_menu(chain_id) if _is_orderable(i)]
        if not menu:
            # A chain we recognise but haven't scraped yet (Papa John's,
            # Domino's, Costa…). Say so rather than dropping it: "we know it's
            # there, we can't rank it" is useful; silence looks like the shop
            # doesn't exist.
            existing = unranked_chains.get(chain_id)
            if not existing or outlet["distance_miles"] < existing["distance_miles"]:
                unranked_chains[chain_id] = {
                    "chain_id": chain_id, "name": outlet["business_name"],
                    "distance_miles": outlet["distance_miles"]}
            continue

        cache_key = (chain_id, outlet.get("postcode"), outlet["business_name"])
        persisted = _DISK_CACHE.get(chain_id, outlet.get("postcode"),
                                    outlet["business_name"])
        if cache_key in halal_cache:
            halal_status, halal_tier = halal_cache[cache_key]
        elif persisted:
            halal_status, halal_tier = persisted
            halal_cache[cache_key] = persisted
        elif resolve_halal_live:
            res = resolve_halal(s, {
                "name": outlet["business_name"], "chain_id": chain_id,
                "lat": outlet["lat"], "lng": outlet["lng"],
                "postcode": outlet["postcode"], "address": outlet["address"]})
            halal_status, halal_tier = str(res.status), res.tier.name.lower()
            halal_cache[cache_key] = (halal_status, halal_tier)
            _DISK_CACHE.put(chain_id, outlet.get("postcode"),
                            outlet["business_name"], halal_status, halal_tier)
        else:
            halal_status, halal_tier = "unverified", "none"

        outlets_used.append({**outlet, "halal_status": halal_status,
                             "halal_tier": halal_tier, "menu_items": len(menu)})

        for item in menu:
            quote = price_for(chain_id, item["name"])
            if not quote:
                continue
            disc = best_discount(chain_id, item["name"])
            final = round(quote.price_gbp * (1 - disc.percent / 100), 2) if disc \
                else quote.price_gbp
            scored.append(ScoredItem(
                name=item["name"], chain_id=chain_id,
                outlet_name=outlet["business_name"],
                distance_miles=outlet["distance_miles"],
                kcal=float(item["kcal"]), protein_g=float(item["protein_g"]),
                list_price_gbp=quote.price_gbp, final_price_gbp=final,
                discount_label=disc.label if disc else None,
                halal_status=halal_status, halal_tier=halal_tier,
                vegetarian=bool(item.get("vegetarian")),
                vegan=bool(item.get("vegan")),
                nutrition_source=item.get("source", ""),
                nutrition_confidence="high",
                price_basis=quote.basis))

    payload = rank(scored, diet=diet, min_protein_share=min_protein_share,
                   strict_halal=strict_halal, sort_by=sort_by, limit=limit)
    payload["location"] = loc
    payload["outlets"] = sorted(outlets_used, key=lambda o: o["distance_miles"])
    payload["outlet_counts"] = {
        "total": len(outlets), "chains": len(chain_outlets),
        "chains_ranked": len({o["chain_id"] for o in outlets_used}),
        "chains_unranked": len(unranked_chains),
        "independents": sum(1 for o in outlets if o["kind"] == "independent"),
        "supermarkets": sum(1 for o in outlets if o["kind"] == "supermarket"),
    }
    payload["unranked_chains"] = sorted(unranked_chains.values(),
                                        key=lambda c: c["distance_miles"])
    payload["discount_rules_applied"] = len(DISCOUNTS)
    _DISK_CACHE.save()
    return payload
