"""Discount rules — modelled as rules, not prices.

Whether an offer applies depends on the *user* (are they a student? is it their
first order on that chain's app?), so a discount can't be baked into a price.
Each rule carries its conditions and the resolver applies the single best rule
the user qualifies for — UK food offers effectively never stack.

These are curated by hand on purpose: there are only ~30–50 live UK food offers
at any time, they're advertised publicly, and curating them is both more
accurate and more honest than trying to scrape through StudentBeans' and
UNiDAYS' login walls.

`last_verified` is the field that keeps this table trustworthy. A discount rule
that silently expires produces a final price the user can't actually get, which
is worse than showing no discount at all — so stale rules should be hidden
rather than applied.
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Discount:
    rule_id: str
    chain_id: str
    label: str
    percent: float
    scope: str                 # 'order' | 'item'
    item_matcher: str          # '*' or a substring of the item name
    requires_app: bool = False
    first_order_only: bool = False
    student_platform: str | None = None
    source_url: str = ""
    last_verified: str = ""


DISCOUNTS: list[Discount] = [
    Discount("gdk_app_first", "gdk",
             "50% off the OG on your first GDK app order", 50.0,
             "item", "original", requires_app=True, first_order_only=True,
             source_url="https://www.gdk.com/", last_verified="2026-07-28"),
    Discount("popeyes_app_first", "popeyes",
             "20% off your first Popeyes app order", 20.0,
             "order", "*", requires_app=True, first_order_only=True,
             source_url="https://popeyesuk.com/", last_verified="2026-07-28"),
    Discount("subway_student", "subway",
             "10% Subway student discount", 10.0,
             "order", "*", student_platform="studentbeans",
             source_url="https://www.studentbeans.com/", last_verified="2026-07-28"),
    Discount("greggs_student", "greggs",
             "Greggs student discount", 10.0,
             "order", "*", student_platform="unidays",
             source_url="https://www.myunidays.com/", last_verified="2026-07-28"),
]


@dataclasses.dataclass
class Eligibility:
    """What the user can actually claim. Defaults are deliberately generous so
    the UI can show potential savings, then let them narrow it down."""
    student: bool = True
    has_apps: bool = True
    first_order_chains: frozenset[str] = frozenset(
        {"gdk", "popeyes", "kfc", "mcdonalds", "burger_king", "subway"})


DEFAULT_ELIGIBILITY = Eligibility()


def applicable(rule: Discount, chain_id: str, item_name: str,
               elig: Eligibility) -> bool:
    if rule.chain_id != chain_id:
        return False
    if rule.requires_app and not elig.has_apps:
        return False
    if rule.first_order_only and chain_id not in elig.first_order_chains:
        return False
    if rule.student_platform and not elig.student:
        return False
    if rule.scope == "item" and rule.item_matcher != "*":
        if rule.item_matcher.lower() not in item_name.lower():
            return False
    return True


def best_discount(chain_id: str, item_name: str,
                  elig: Eligibility | None = None) -> Discount | None:
    elig = elig or DEFAULT_ELIGIBILITY
    candidates = [r for r in DISCOUNTS if applicable(r, chain_id, item_name, elig)]
    return max(candidates, key=lambda r: r.percent) if candidates else None
