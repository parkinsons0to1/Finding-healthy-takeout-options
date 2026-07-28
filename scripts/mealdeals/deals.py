"""UK supermarket meal deals — the fixed-price side of MacroMeter.

Meal deals are the easiest high-value win in the whole product: the price is
*fixed and published* (£3.85, £3.60, …), which removes the hardest data problem
(per-outlet live pricing) entirely. All the work is in knowing which products
fill which slot, and then picking the combination with the most protein.

Deal definitions are curated because they are few, stable, and publicly
advertised. Prices are per-retailer and often have a loyalty tier (Tesco
Clubcard, Sainsbury's Nectar), which materially changes the ranking, so both
are modelled.

`last_verified` is load-bearing: meal deal prices move, and a stale price
silently corrupts every ranking that uses it.
"""
from __future__ import annotations

import dataclasses

SLOTS = ("main", "snack", "drink")


@dataclasses.dataclass(frozen=True)
class MealDeal:
    retailer_id: str
    retailer_name: str
    name: str
    price_pence: int
    loyalty_price_pence: int | None
    loyalty_scheme: str | None
    slots: tuple[str, ...]
    source_url: str
    last_verified: str

    @property
    def best_price_pence(self) -> int:
        return self.loyalty_price_pence or self.price_pence

    def price_gbp(self, loyalty: bool = True) -> float:
        return (self.best_price_pence if loyalty else self.price_pence) / 100


DEALS: list[MealDeal] = [
    MealDeal("tesco", "Tesco", "Meal Deal", 400, 385, "Clubcard",
             SLOTS, "https://www.tesco.com/groceries/en-GB/promotions/mealdeal",
             "2026-07-28"),
    MealDeal("sainsburys", "Sainsbury's", "Meal Deal", 400, 375, "Nectar",
             SLOTS, "https://www.sainsburys.co.uk/", "2026-07-28"),
    MealDeal("boots", "Boots", "Meal Deal", 399, 399, None,
             SLOTS, "https://www.boots.com/meal-deal", "2026-07-28"),
    MealDeal("coop", "Co-op", "Meal Deal", 400, 350, "Co-op Member",
             SLOTS, "https://www.coop.co.uk/", "2026-07-28"),
    MealDeal("morrisons", "Morrisons", "Meal Deal", 395, 350, "More Card",
             SLOTS, "https://www.morrisons.com/", "2026-07-28"),
    MealDeal("asda", "Asda", "Meal Deal", 400, 350, "Asda Rewards",
             SLOTS, "https://www.asda.com/", "2026-07-28"),
    MealDeal("marks_spencer", "M&S", "Lunch Deal", 500, 450, "Sparks",
             SLOTS, "https://www.marksandspencer.com/", "2026-07-28"),
    MealDeal("waitrose", "Waitrose", "Meal Deal", 500, 500, None,
             SLOTS, "https://www.waitrose.com/", "2026-07-28"),
]

BY_RETAILER = {d.retailer_id: d for d in DEALS}


def deal_for(retailer_id: str) -> MealDeal | None:
    return BY_RETAILER.get(retailer_id)
