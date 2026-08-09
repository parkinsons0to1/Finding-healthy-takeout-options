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
import re

from ..geo.location import find_outlets, resolve_location
from ..halal.cache import HalalCache
from ..halal.resolver import resolve as resolve_halal
from ..scrapers.base import session
from .discounts import DISCOUNTS, best_discount
from ..offers.registry import expanded_for_chain
from .prices import PriceQuote, price_for
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
#:
#: These are substring tests, so each word here bans a word rather than a kind
#: of row — which is why "strips" and "slices" had to come out. Banning
#: "strips" to exclude Subway's filling silently deleted *chicken strips* from
#: nine chains (Wetherspoon's southern-fried chicken strips basket, Chopstix
#: katsu strips, Pepe's tender strips, Pizza Hut's breaded chicken strips…) —
#: the single food category this product exists to surface. Subway's fillings
#: are already excluded by `_PRODUCT_SECTIONS` below, which excludes by
#: section rather than by word and so cannot misfire on another chain.
_INGREDIENT_WORDS = ("premix", "do not use", "sauce", "dressing",
                     "portion", "scoop", "topping", "cheese triangle")

#: **Add-ons and modifiers**, which every table-service chain lists alongside
#: real dishes. They are catastrophic for this ranking specifically: a bare
#: "Add A Grilled Chicken Breast" is ~100% protein-by-calories and would
#: outrank every actual meal, while being something you cannot buy on its own.
#: Broadening this beyond Subway became necessary once pub and casual-dining
#: chains were ingested — their menus are full of "Add …"/"Extra …" rows.
_MODIFIER_RE = re.compile(
    r"^\s*(add|extra|swap|upgrade|side of|make it|with)\b"
    r"|^\s*&\s"                       # "& Chicken Breast" (ASK Italian)
    r"|\b(sachet|dip pot|condiment)\b"
    r"|\btaster topping\b",
    re.I)

#: Section names that indicate a buyable product rather than a component.
_PRODUCT_SECTIONS = {
    "subway": {"subs", "salads", "wraps", "breakfast", "sides"},
}

#: **Rows that are real food but not a purchase.**
#:
#: Papa John's publishes every pizza twice, whole and "(1 slice)" — 240 of its
#: 480 nutrition rows are slices. You cannot buy one slice, and the ordering
#: API has no price for one, so a slice row can only ever be priced by
#: accidentally matching the whole pizza. It is also the single most attractive
#: row in the file: a slice is a sixth of the calories at (wrongly) the same
#: price, which would put it straight to the top of protein-per-pound.
#:
#: "TEST …" rows are Burger King's own staging data, which ships in their live
#: nutrition feed ("TEST Chilli Jam & Bacon Double Whopper®"). They read as
#: perfectly ordinary burgers and cannot be bought anywhere.
#: Only a *single* slice, never "(4 slices)" — Pizza Hut's "Garlic Bread
#: (4 slices)" is the portion they sell, and matching any slice count would
#: throw away real products alongside the phantom ones.
_NOT_A_PURCHASE_RE = re.compile(
    r"\(\s*1\s*slice\s*\)"            # "… - Large (1 slice)"
    r"|\bper\s+slice\b"
    r"|^\s*TEST\b",
    re.I)

#: **Unambiguous pork markers.** An outlet's halal status is resolved once
#: per branch and stamped onto every item that branch sells — correct for a
#: chain whose whole menu shares one animal (Popeyes' chicken, Tortilla's
#: beef/chicken/pork protein pots), wrong the moment that branch also sells
#: pork on the side. Popeyes' own chain policy already documents "shares
#: fryers with non-halal items (e.g. pork bacon)" as a caveat — but nothing
#: enforced it: "Bacon Roll with Cajun Ketchup" was still being labelled
#: halal_status="halal" for every halal-chain-wide branch, and the same
#: bug would have hit Tortilla's "Pork Carnitas" the moment its chicken was
#: correctly added as chain-wide halal. This is not a case for the same
#: "only guess in the safe direction" discipline vegetarian/vegan flags use
#: — there the danger was a false True, so the safe move was to stay silent.
#: Here the danger runs the other way: a MISSED pork item stays wrongly
#: labelled halal, so this list is deliberately broad rather than narrow.
#: Kept to words that are essentially always pork in UK food service —
#: never words that are sometimes-pork (e.g. "pepperoni", frequently beef in
#: UK chains — see dominos.json/prices, which sells it as a plain topping).
_PORK_RE = re.compile(
    r"\bpork\b|\bbacon\b|\bham\b|\bgammon\b|\bchorizo\b|\bpancetta\b"
    r"|\bprosciutto\b|\bsalami\b|\black pudding\b|\blardons?\b"
    r"|\bpepperoni\b",  # UK pepperoni is traditionally pork; only Domino's
                        # (own beef pepperoni, verified separately) is exempt
    re.I)

#: Domino's UK sells pepperoni as beef, not pork (their own allergen/recipe
#: data has no pork mention on pepperoni items) — the one chain this project
#: currently ingests where "pepperoni" would otherwise be a false pork flag.
_PEPPERONI_EXEMPT_CHAINS = {"dominos"}


def _contains_pork(chain_id: str, name: str) -> bool:
    if not _PORK_RE.search(name):
        return False
    if chain_id in _PEPPERONI_EXEMPT_CHAINS \
            and re.search(r"\bpepperoni\b", name, re.I) \
            and not re.search(r"\bpork\b|\bbacon\b|\bham\b|\bgammon\b|"
                              r"\bchorizo\b|\bpancetta\b|\bprosciutto\b|"
                              r"\bsalami\b|\black pudding\b|\blardons?\b",
                              name, re.I):
        return False
    return True


#: **Protein-scoped halal claims.** A handful of chains have a brand
#: statement confirming ONE protein's supplier is halal-certified, on a menu
#: that also sells other proteins the statement says nothing about —
#: Tortilla confirms HFA-certified chicken (their own tweet), but also sells
#: beef and pork. `chain_policy.py`'s POLICIES dict can only express one
#: verdict per outlet, so a chain like this can't go there without either
#: wrongly clearing the beef/pork too, or wrongly denying the chicken. This
#: is the item-level equivalent instead: promotes to halal only when the
#: name confirms the certified protein AND contains no other named protein
#: that would make the dish something other than a plain example of it.
_PROTEIN_HALAL = {
    "tortilla": {
        "protein": re.compile(r"\bchicken\b", re.I),
        "other_proteins": re.compile(
            r"\bbeef\b|\bpork\b|\bbarbacoa\b|\bcarnitas\b|\bveg(an|etarian)\b",
            re.I),
        "url": "https://x.com/tortillauk/status/1620436428588220416",
    },
}


def _protein_halal_override(chain_id: str, name: str) -> bool:
    rule = _PROTEIN_HALAL.get(chain_id)
    if not rule:
        return False
    return bool(rule["protein"].search(name)) \
        and not rule["other_proteins"].search(name)


#: Menu sections that are explicitly components, whatever the item is called.
#: PizzaExpress files toppings under "Extra Toppings" and Wasabi files
#: condiments under "optional sauce & dressing" — a bare "Chicken" row there is
#: a pizza topping, not a dish, and reads as ~100% protein.
#:
#: The pub and casual-dining chains name these sections imaginatively —
#: Frankie & Benny's "Go on… add a little extra!", Harvester's "KIDS MEAL DEAL
#: / 1. CHOOSE YOUR MAIN", Wetherspoon's "CHILDREN'S MENU / Step 1",
#: Beefeater's "Upgrade" — and they nest the section inside a path, so an
#: anchored `^extras?$` missed nearly all of them. A "choose your …" or
#: numbered step is a builder for one priced meal, not a shelf of things you
#: can buy; a bare "Chicken breast" from one is 77% protein by calories.
#:
#: Five Guys' PDF category spells this out almost too literally: "Milkshakes
#: + Mix-Ins - Amount Of Individual Mix-Ins May Vary Depending Upon Number Of
#: Mix-Ins Included In Shake". "Myprotein (12g)" out of that section is a
#: scoop stirred into someone else's milkshake, not a thing you can buy on its
#: own, and at 54 kcal for 12g protein it is 89% protein by calories — high
#: enough to sit at the very top of the whole leaderboard if left in.
_NON_PRODUCT_CATEGORY_RE = re.compile(
    r"\btoppings?\b|\bextras?\b|\badd[- ]?ons?\b|add a little extra"
    r"|\bchoose your\b|\bstep\s*\d|\bupgrade\b|\bmix-?ins?\b"
    r"|optional sauce|dressing|condiment|dips?$", re.I)


#: **Per-100g rows, which cannot be ranked against a per-item price.**
#:
#: Some chains publish nutrition per 100g rather than per portion — Hotel
#: Chocolat's entire table is per 100g. Their protein *share* is still true,
#: so they sail through the 35% gate, but protein-per-pound is nonsense: it
#: divides 100g of food by the price of a whole one.
#:
#: Five Guys and Krispy Kreme used to be per-100g here too, but both actually
#: publish per-serving/per-portion nutrition right next to the per-100g
#: numbers in the same PDF table — the bug was in column selection, not a
#: missing source. See scrapers/chains/five_guys.py and krispy_kreme.py.
#:
#: The negative lookbehind matters — Papa John's says "whole pizza, 1100g, 10
#: slices", which contains "100g" and is emphatically per-item.
_PER_100_RE = re.compile(r"(?<!\d)100\s*(?:g|ml)\b", re.I)

#: Portion words a component is sized by when it is sized to fit a product
#: rather than sold on its own.
_SIZE_ONLY_RE = re.compile(
    r"^(x?s|small|medium|regular|large|xl|xxl|personal|mini|kids?|junior)$", re.I)


@functools.lru_cache(maxsize=32)
def _component_categories(chain_id: str) -> frozenset[str]:
    """Categories whose rows are just one product's parts, sized to fit it.

    Domino's publishes every topping as four rows — "Chicken Breast Strips —
    Large/Medium/Small/Personal", filed under a category of the same name.
    They are 85 kcal and 88% protein by calories, so they would sit at the top
    of the leaderboard while being un-orderable: you cannot buy the chicken off
    a pizza. Its actual pizzas, by contrast, carry a compound suffix
    ("Chicken Feast — Classic Crust, Large, Standard Mozzarella").

    That difference is the test, and it is derived from the data rather than
    listed by hand: a category is a component group when every row in it is the
    category name plus nothing but a size. An allowlist would not scale —
    Domino's alone has 109 categories — and, more importantly, a hand-listed
    rule is one we would have to remember to update for the next chain.
    """
    groups: dict[str, list[str]] = {}
    for item in load_menu(chain_id):
        category = (item.get("category") or "").strip()
        if category:
            groups.setdefault(category, []).append((item.get("name") or "").strip())

    out = set()
    for category, names in groups.items():
        if not (2 <= len(names) <= 8):
            continue
        suffixes = []
        for name in names:
            head, sep, tail = name.partition("—")
            if not sep or head.strip().casefold() != category.casefold():
                break
            suffixes.append(tail.strip())
        else:
            if suffixes and all(_SIZE_ONLY_RE.match(s) for s in suffixes):
                out.add(category.casefold())
    return frozenset(out)


def _is_orderable(item: dict) -> bool:
    name = (item.get("name") or "").strip()
    lowered = name.lower()
    if not name or not item.get("kcal") or item.get("protein_g") is None:
        return False
    # A 1-2 kcal row is a garnish or a diet drink, not a meal, and dividing by
    # it produces a meaningless protein share ("Pepsi Max Cherry - Regular",
    # 2 kcal, reads as 100% protein). Kept deliberately far below any real
    # dish: the lightest genuine item in the whole database is ~40 kcal.
    if float(item["kcal"]) < 20:
        return False
    if "implausible-kcal" in (item.get("quality_flags") or []):
        return False
    if any(w in lowered for w in _INGREDIENT_WORDS):
        return False
    if _MODIFIER_RE.search(name):
        return False
    if _NOT_A_PURCHASE_RE.search(name):
        return False
    serving = item.get("serving_desc")
    if isinstance(serving, str) and _PER_100_RE.search(serving):
        return False
    category = (item.get("category") or "").strip()
    if category and _NON_PRODUCT_CATEGORY_RE.search(category):
        return False
    if category and item.get("chain_id") \
            and category.casefold() in _component_categories(item["chain_id"]):
        return False
    sections = _PRODUCT_SECTIONS.get(item.get("chain_id"))
    if sections and category.lower() not in sections:
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

        # Limited-time bundles carry their own price and their macros are
        # summed from menu rows, so they join the same ranking as ordinary
        # items — which is the point: KFC's 10-tender bucket beats every
        # standard item on protein-per-pound.
        for item in menu + expanded_for_chain(chain_id, menu):
            if item.get("is_offer"):
                quote = PriceQuote(item["offer_price_gbp"], "offer",
                                   item.get("offer_valid_to") or "",
                                   item.get("source", ""))
                disc = None      # an offer price is already the deal
            else:
                quote = price_for(chain_id, item["name"])
                disc = best_discount(chain_id, item["name"]) if quote else None
            if quote is None:
                # No trustworthy price. Keep the item so it can be listed as
                # "price unknown" rather than vanishing; scoring will exclude
                # it from the ranking.
                list_price = final = None
                price_basis = "unknown"
            else:
                list_price = quote.price_gbp
                final = (round(quote.price_gbp * (1 - disc.percent / 100), 2)
                         if disc else quote.price_gbp)
                price_basis = quote.basis
            # An outlet's halal status is resolved once per branch, which is
            # wrong the instant that branch also sells pork alongside an
            # otherwise-halal range — see _PORK_RE above. This item-level
            # override fires regardless of how confidently "halal" the
            # branch itself is; pork is never halal no matter who else in
            # the kitchen is.
            item_halal_status, item_halal_tier = halal_status, halal_tier
            if halal_status == "halal" and _contains_pork(chain_id, item["name"]):
                item_halal_status = "not_halal"
            elif halal_status != "halal" \
                    and _protein_halal_override(chain_id, item["name"]):
                # The inverse case: a per-outlet status of unverified/none is
                # correct for the branch as a whole (no chain-wide policy
                # exists — see _PROTEIN_HALAL above for why one can't), but
                # this specific item is a plain example of the one protein
                # that IS confirmed, so it can be promoted on its own.
                item_halal_status, item_halal_tier = "halal", "brand_chain_wide"
            scored.append(ScoredItem(
                name=item["name"], chain_id=chain_id,
                outlet_name=outlet["business_name"],
                distance_miles=outlet["distance_miles"],
                kcal=float(item["kcal"]), protein_g=float(item["protein_g"]),
                list_price_gbp=list_price, final_price_gbp=final,
                discount_label=disc.label if disc else None,
                halal_status=item_halal_status, halal_tier=item_halal_tier,
                vegetarian=bool(item.get("vegetarian")),
                vegan=bool(item.get("vegan")),
                nutrition_source=item.get("source", ""),
                nutrition_confidence="high",
                price_basis=price_basis,
                # Live prices reuse whichever single branch each chain's
                # adapter scraped — there is no per-region scraping — so a
                # search anywhere in the UK can surface a real, current price
                # that belongs to a different branch than `outlet_name`
                # above. Carrying the scrape's own branch name lets the UI
                # say so instead of presenting it silently under the local
                # outlet's identity.
                price_store=(quote.store if quote and price_basis
                            not in ("estimated", "unknown", "offer") else ""),
                is_offer=bool(item.get("is_offer")),
                offer_basis=item.get("offer_basis"),
                offer_components=item.get("offer_components"),
                offer_valid_to=item.get("offer_valid_to"),
                offer_availability=item.get("offer_availability")))

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
