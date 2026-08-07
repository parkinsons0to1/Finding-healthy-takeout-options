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
  * Second, sharper instance of the same source bug (found 2026-08-07): a
    piece-count SKU can carry a DIFFERENT SKU's nutrition wholesale, rather
    than being merely miscalculated. "10 Hot Wings" reports the identical
    75.0g protein as "8 Hot Wings"; every Boneless bundle from 6 to 20 pieces
    reports the identical 35.6g protein. None of that trips the ratio check
    above, because kcal and protein are internally *consistent* within the
    copied row — it is just the wrong row's numbers. The "Classic/Spicy
    Tenders & a dip" bundles have a subtler version of the same fault: kcal
    scales consistently across the 3/5/8-piece bundle rows (~77 kcal/tender)
    but at roughly half the per-tender rate the standalone "1 Classic
    Tender" states (156 kcal) — each bundle size agrees with its siblings
    and disagrees with the ground truth.
    The only way to see either fault is across rows, not within one: sort a
    product family ("Boneless", "Tenders", …) by piece count and check that
    calories-per-piece is roughly stable. A row whose per-piece rate is far
    from its own family's is flagged, and so is the row it was probably
    copied from — we cannot tell which one is genuine, only that they
    disagree by more than any two portions of the same fried chicken should.
"""
from __future__ import annotations

import re

from .base import item, session, to_float

#: A product family, for the cross-row consistency check: the piece count
#: stripped, any "& a dip"/"& 2 dips" suffix stripped, and the trailing
#: plural folded so "1 Classic Tender" joins "3 Classic Tenders & a dip".
#: The dip count is worded as "a" for one and a digit from two up ("& a dip",
#: "& 2 dips") — matching only `\d*` silently failed on "a" and put every
#: "& a dip" bundle in its own one-member family, where the consistency check
#: below has nothing to compare against and never fires.
_QTY_RE = re.compile(r"^(\d+)\s+(.*?)(?:\s*&\s*(?:a|\d+)\s*dips?)?$", re.I)


def _family(name: str) -> tuple[str, int] | None:
    m = _QTY_RE.match(name.strip())
    if not m:
        return None
    words = m.group(2).strip().lower().split()
    singular = " ".join(w[:-1] if w.endswith("s") else w for w in words)
    return singular, int(m.group(1))


def _flag(row: dict) -> None:
    row.setdefault("quality_flags", [])
    if "implausible-kcal" not in row["quality_flags"]:
        row["quality_flags"].append("implausible-kcal")


def _flag_family_inconsistencies(rows: list[dict]) -> None:
    """Flag rows whose figures don't scale with piece count as real food must.

    Mutates `quality_flags` in place, via two checks:

    - **Exact protein collisions.** If two members of a family at different
      piece counts report the identical protein_g, one of them is a copy of
      the other's row — real chicken's protein content is never the same at
      6 pieces and at 20. Both are flagged, since which one is genuine is not
      knowable from here. This alone catches the Boneless family, where five
      different quantities all report 35.6g.

    - **Per-piece kcal against the single-piece anchor.** Where the family
      has a genuine 1-piece row, its kcal-per-piece is the most trustworthy
      rate available (nothing to average away), so every other member's rate
      is compared against it rather than against the family's own median —
      a median is worthless once the corrupted rows outnumber the correct
      one, which is exactly the Tenders-bundle case (three corrupted bundle
      sizes agreeing with each other and disagreeing with the single-tender
      truth). No single-piece anchor, no check: extrapolating a rate from
      bundles alone would just re-encode whatever bias they share.
    """
    families: dict[str, list[tuple[dict, int]]] = {}
    for row in rows:
        parsed = _family(row["name"])
        if parsed:
            families.setdefault(parsed[0], []).append((row, parsed[1]))

    for members in families.values():
        if len(members) < 2:
            continue

        by_protein: dict[float, list[dict]] = {}
        for row, _qty in members:
            if row.get("protein_g") is not None:
                by_protein.setdefault(row["protein_g"], []).append(row)
        for protein_rows in by_protein.values():
            if len(protein_rows) > 1:
                for row in protein_rows:
                    _flag(row)

        anchor = next((row for row, qty in members if qty == 1), None)
        if anchor is None or not anchor.get("kcal"):
            continue
        reference_rate = anchor["kcal"] / 1
        for row, qty in members:
            if row is anchor or not row.get("kcal"):
                continue
            rate = row["kcal"] / qty
            # 1.8x, not 2x: the Spicy Tenders bundles sit at ~77 kcal/tender
            # against a 151 kcal single-tender anchor — a ratio of 1.93, which
            # a round 2x tolerance lets through by a hair. The Classic Tenders
            # bundles fail the same way at a slightly larger gap, which is why
            # this was visible at all: two flavours of the same product
            # showing the same halving is the signal that it is a source
            # fault, not one unusually large single tender.
            if rate < reference_rate / 1.8 or rate > reference_rate * 1.8:
                _flag(row)

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
    _flag_family_inconsistencies(out)
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
