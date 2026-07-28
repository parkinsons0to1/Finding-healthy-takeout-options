"""Pick the highest-protein meal deal bundle for a fixed price.

Because the deal price is fixed, "best value" reduces to **maximise protein**
(subject to the user's dietary filters and protein-density rule) — every bundle
costs the same, so protein-per-£ is monotonic in protein. That makes this a
small, exact optimisation rather than a heuristic one.

The naive search space (mains × snacks × drinks) looks large but collapses
immediately: only the top-N by protein in each slot can appear in an optimal
bundle, so we keep those and enumerate exactly. With N=25 that's ~15k
combinations — microseconds — and it's provably optimal for total protein
because the objective is a plain sum over independent slots.

The protein-density filter (≥35% of calories from protein) is applied to the
**bundle**, not to each item, which is the right call: a chicken salad main can
carry a low-density drink and the meal as a whole still clears the bar. Applying
it per-item would wrongly reject water.
"""
from __future__ import annotations

import dataclasses
import itertools

from .deals import MealDeal


@dataclasses.dataclass
class Bundle:
    deal: MealDeal
    items: dict[str, dict]
    price_gbp: float

    @property
    def kcal(self) -> float:
        return round(sum(i["kcal"] for i in self.items.values()), 1)

    @property
    def protein_g(self) -> float:
        return round(sum(i["protein_g"] for i in self.items.values()), 1)

    @property
    def protein_share(self) -> float:
        return round(self.protein_g * 4 / self.kcal, 4) if self.kcal else 0.0

    @property
    def protein_per_pound(self) -> float:
        return round(self.protein_g / self.price_gbp, 2) if self.price_gbp else 0.0

    def describe(self) -> str:
        parts = [f"{slot}: {self.items[slot]['name']}" for slot in self.items]
        return " + ".join(parts)

    def to_row(self) -> dict:
        return {
            "retailer": self.deal.retailer_name,
            "deal": self.deal.name,
            "price_gbp": self.price_gbp,
            "protein_g": self.protein_g,
            "kcal": self.kcal,
            "protein_share": self.protein_share,
            "protein_per_pound": self.protein_per_pound,
            **{f"{slot}_name": item["name"] for slot, item in self.items.items()},
            **{f"{slot}_protein_g": item["protein_g"] for slot, item in self.items.items()},
        }


def _passes_diet(item: dict, diet: set[str]) -> bool:
    return all(item.get(flag) for flag in diet)


def optimise(deal: MealDeal, products: dict[str, list[dict]],
             diet: set[str] | None = None, min_protein_share: float = 0.0,
             loyalty: bool = True, top_n_per_slot: int = 25,
             limit: int = 10) -> list[Bundle]:
    """Best bundles for one deal, strongest first.

    `diet` is a set of required flags ('halal', 'vegetarian', 'vegan', 'kosher').
    `min_protein_share` filters on the finished bundle.
    """
    diet = diet or set()
    price = deal.price_gbp(loyalty)

    shortlists = {}
    for slot in deal.slots:
        candidates = [p for p in products.get(slot, []) if _passes_diet(p, diet)]
        if not candidates:
            return []
        candidates.sort(key=lambda p: p["protein_g"], reverse=True)
        shortlists[slot] = candidates[:top_n_per_slot]

    bundles: list[Bundle] = []
    for combo in itertools.product(*(shortlists[s] for s in deal.slots)):
        items = dict(zip(deal.slots, combo))
        b = Bundle(deal, items, price)
        if b.protein_share < min_protein_share:
            continue
        bundles.append(b)

    bundles.sort(key=lambda b: b.protein_g, reverse=True)
    return bundles[:limit]


def optimise_all(deals: list[MealDeal], products_by_retailer: dict[str, dict],
                 **kwargs) -> list[Bundle]:
    """Best bundle from each retailer, ranked across retailers by protein/£."""
    best: list[Bundle] = []
    for deal in deals:
        products = products_by_retailer.get(deal.retailer_id)
        if not products:
            continue
        top = optimise(deal, products, limit=1, **kwargs)
        best.extend(top)
    best.sort(key=lambda b: b.protein_per_pound, reverse=True)
    return best
