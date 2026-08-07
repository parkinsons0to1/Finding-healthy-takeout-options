"""MacroMeter scoring engine (score_version 1.0).

Three numbers, all shown to the user, one used for ranking:

    protein density   protein_g * 4 / kcal      the gym filter (default >= 35%)
    protein per £     protein_g / final_price   THE RANKING KEY
    calories per £    kcal / final_price        secondary view for bulking

`final_price` is list price minus the single best discount the user is actually
eligible for (UK food offers effectively never stack), so the ranking reflects
what leaves your account, not the menu board.

Design notes worth keeping:
  * Items with no protein figure are **excluded**, never imputed. A guessed
    macro that lands near the 35% line silently reorders the whole list.
  * The density filter is a hard gate, but near-misses (30–35%) are returned
    separately rather than hidden — KFC Original Recipe sat at 34% in early
    data while being the best value in town, and silently dropping it made the
    tool feel wrong.
  * Every result carries its provenance (nutrition source + confidence, halal
    evidence tier) so the UI can show why, and a low-confidence row never
    looks identical to a brand-published one.
"""
from __future__ import annotations

import dataclasses

SCORE_VERSION = "1.0"
DEFAULT_MIN_PROTEIN_SHARE = 0.35
NEAR_MISS_FLOOR = 0.30


@dataclasses.dataclass
class ScoredItem:
    name: str
    chain_id: str
    outlet_name: str
    distance_miles: float
    kcal: float
    protein_g: float
    list_price_gbp: float | None
    final_price_gbp: float | None
    discount_label: str | None
    halal_status: str
    halal_tier: str
    vegetarian: bool
    vegan: bool
    nutrition_source: str
    nutrition_confidence: str
    price_basis: str
    #: Limited-time bundle fields — empty for ordinary menu items.
    is_offer: bool = False
    offer_basis: str | None = None
    offer_components: list[str] | None = None
    offer_valid_to: str | None = None
    offer_availability: str | None = None

    @property
    def protein_share(self) -> float:
        return round(self.protein_g * 4 / self.kcal, 4) if self.kcal else 0.0

    @property
    def protein_per_pound(self) -> float | None:
        if not self.final_price_gbp:
            return None
        return round(self.protein_g / self.final_price_gbp, 2)

    @property
    def kcal_per_pound(self) -> float | None:
        if not self.final_price_gbp:
            return None
        return round(self.kcal / self.final_price_gbp, 1)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "chain_id": self.chain_id,
            "outlet_name": self.outlet_name, "distance_miles": self.distance_miles,
            "kcal": self.kcal, "protein_g": self.protein_g,
            "protein_share": self.protein_share,
            "list_price_gbp": self.list_price_gbp,
            "final_price_gbp": self.final_price_gbp,
            "discount_label": self.discount_label,
            "protein_per_pound": self.protein_per_pound,
            "kcal_per_pound": self.kcal_per_pound,
            "halal_status": self.halal_status, "halal_tier": self.halal_tier,
            "vegetarian": self.vegetarian, "vegan": self.vegan,
            "nutrition_source": self.nutrition_source,
            "nutrition_confidence": self.nutrition_confidence,
            "price_basis": self.price_basis,
            "is_offer": self.is_offer,
            "offer_basis": self.offer_basis,
            "offer_components": self.offer_components,
            "offer_valid_to": self.offer_valid_to,
            "offer_availability": self.offer_availability,
            "score_version": SCORE_VERSION,
        }


def passes_diet(item: ScoredItem, diet: set[str], strict_halal: bool = True) -> bool:
    """Dietary gate.

    `strict_halal` decides what an *unverified* halal status means. Default is
    strict: unverified is excluded, because showing a maybe-halal item to
    someone filtering for halal is the failure mode that matters. Users who
    would rather see them and ask in store can relax it.
    """
    if "vegetarian" in diet and not item.vegetarian:
        return False
    if "vegan" in diet and not item.vegan:
        return False
    if "halal" in diet:
        if item.halal_status != "halal":
            return False
        if strict_halal and item.halal_tier in ("", "none"):
            return False
    return True


def _dedupe_by_nearest_branch(items: list[ScoredItem]) -> list[ScoredItem]:
    """Two Greggs on the same high street shouldn't fill the list with the same
    sausage roll twice. Keep one row per (chain, item) — the nearest branch,
    preferring a halal-verified one where branches differ (which they can:
    neighbouring KFCs genuinely differ on halal status)."""
    best: dict[tuple[str, str], ScoredItem] = {}
    for item in items:
        key = (item.chain_id, item.name.lower())
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        better_halal = (item.halal_status == "halal"
                        and current.halal_status != "halal")
        if better_halal or (item.halal_status == current.halal_status
                            and item.distance_miles < current.distance_miles):
            best[key] = item
    return list(best.values())


def rank(items: list[ScoredItem], diet: set[str] | None = None,
         min_protein_share: float = DEFAULT_MIN_PROTEIN_SHARE,
         strict_halal: bool = True, sort_by: str = "protein_per_pound",
         limit: int = 25) -> dict:
    """Rank items, returning the qualifying list plus visible near-misses."""
    diet = diet or set()
    passes = [i for i in items
              if i.protein_g and i.kcal and passes_diet(i, diet, strict_halal)]
    eligible = _dedupe_by_nearest_branch([i for i in passes if i.final_price_gbp])

    # Items with real macros but no price we trust. They can't be ranked —
    # protein-per-pound needs a pound — but hiding them is its own error: as
    # chain coverage grew, priced items became a small minority, and silently
    # dropping the rest would tell a user that a high-protein dish nearby
    # doesn't exist. Surfaced separately, ordered by protein density, never
    # mixed into the ranking and never given a guessed price.
    unpriced = _dedupe_by_nearest_branch([i for i in passes if not i.final_price_gbp])
    unpriced.sort(key=lambda i: (i.protein_share, i.protein_g), reverse=True)

    key = (lambda i: i.kcal_per_pound or 0) if sort_by == "kcal_per_pound" \
        else (lambda i: i.protein_per_pound or 0)

    qualifying = sorted([i for i in eligible if i.protein_share >= min_protein_share],
                        key=key, reverse=True)
    near_miss = sorted(
        [i for i in eligible
         if NEAR_MISS_FLOOR <= i.protein_share < min_protein_share],
        key=key, reverse=True)

    return {
        "score_version": SCORE_VERSION,
        "filters": {"diet": sorted(diet), "min_protein_share": min_protein_share,
                    "strict_halal": strict_halal, "sort_by": sort_by},
        "results": [i.to_dict() for i in qualifying[:limit]],
        "near_misses": [i.to_dict() for i in near_miss[:5]],
        "unpriced": [i.to_dict() for i in unpriced
                     if i.protein_share >= min_protein_share][:limit],
        "counts": {"considered": len(items), "eligible": len(eligible),
                   "qualifying": len(qualifying), "near_miss": len(near_miss),
                   "unpriced": len(unpriced)},
    }
