"""Regression tests for defects that reached a user.

Every test here corresponds to a real bug that shipped and was caught in the
field rather than by us. They are deliberately written against the specific
failing input, so a reintroduction fails loudly.

    python3 -m pytest tests/ -q      (or: python3 tests/test_regressions.py)

No network: these exercise pure logic. Adapter/live-source health belongs in
freshness monitoring, not here.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts.api.prices import price_for                       # noqa: E402
from scripts.api.scoring import ScoredItem, rank               # noqa: E402
from scripts.api.search import _is_orderable                   # noqa: E402
from scripts.geo.location import identify_chain, looks_like_postcode  # noqa: E402
from scripts.halal.evidence import Status                      # noqa: E402
from scripts.halal.sources import hmc_registry, just_eat       # noqa: E402


def test_price_lookup_does_not_substring_match_portions():
    """'2 Hot Wings' was matching the '12 Hot Wings' price (£8.79 for a
    2-piece), badly distorting protein-per-pound."""
    twelve = price_for("popeyes", "12 Hot Wings")
    assert twelve and twelve.price_gbp == 10.99
    two = price_for("popeyes", "2 Hot Wings")
    assert two is None, f"'2 Hot Wings' wrongly priced at {two.price_gbp}"


def test_price_lookup_still_matches_exact_names():
    for chain, name in [("popeyes", "6 Hot Wings"), ("kfc", "Fillet Burger"),
                        ("greggs", "Sausage Roll")]:
        assert price_for(chain, name) is not None, f"{chain}/{name} lost its price"


def test_ingredient_rows_are_not_orderable():
    """Subway's PDF lists fillings alongside subs; scoring them put 29-kcal
    turkey slices on the leaderboard."""
    for name in ["Ham (2 slices)", "HALAL Turkey Ham (3 slices)",
                 "Roast Chicken Breast Strips"]:
        assert not _is_orderable(
            {"name": name, "kcal": 62, "protein_g": 10,
             "chain_id": "subway", "category": "Fillings"}), name

    assert _is_orderable({"name": "Chicken Breast", "kcal": 340,
                          "protein_g": 26, "chain_id": "subway",
                          "category": "Subs"})


def test_items_with_missing_macros_are_excluded_not_imputed():
    items = [
        ScoredItem("Real", "kfc", "KFC", 0.1, 300, 30, 3.0, 3.0, None,
                   "halal", "brand_per_outlet", False, False, "", "high", "estimated"),
        ScoredItem("NoProtein", "kfc", "KFC", 0.1, 300, 0, 3.0, 3.0, None,
                   "halal", "brand_per_outlet", False, False, "", "high", "estimated"),
    ]
    out = rank(items, min_protein_share=0.3)
    assert [r["name"] for r in out["results"]] == ["Real"]


def test_known_chains_are_recognised():
    """An unrecognised chain is silently filed as an independent — it vanishes
    from results AND from the 'chains nearby' count. A Papa John's inside a
    holiday park was reported as an independent."""
    expected = {
        "Papa Johns": "papa_johns", "Domino's Pizza": "dominos",
        "Costa Coffee": "costa", "McDonald's": "mcdonalds",
        "KFC Sutton Rst": "kfc", "Greggs PLC": "greggs",
        "Spar": "spar", "Pepe's Piri Piri": "pepes_piri_piri",
        "German Doner Kebab": "gdk", "Subway® Sutton High Street": "subway",
    }
    for name, chain_id in expected.items():
        assert identify_chain(name) == chain_id, f"{name} -> {identify_chain(name)}"


def test_genuine_independents_are_not_misread_as_chains():
    for name in ["Suleymans Kebab House", "Curry Garden", "Harveys Butchers"]:
        assert identify_chain(name) is None, name


def test_sources_that_cannot_prove_a_negative_never_return_not_halal():
    """The original wrong KFC Sutton call came from reading 'absent from a
    partial listing' as 'not halal'. These sources must be structurally
    incapable of that."""
    assert hmc_registry.can_prove_negative is False
    assert just_eat.can_prove_negative is False

    class _Blank:
        status_code = 200
        text = "<html></html>"

        def json(self):
            return {"restaurants": []}

    class _Session:
        def get(self, *a, **k):
            return _Blank()

    s = _Session()
    assert hmc_registry.check_outlet(s, "KFC", 51.36, -0.19).status is Status.UNVERIFIED
    assert just_eat.check_outlet(s, "KFC", "SM1 4FR").status is Status.UNVERIFIED


def test_postcode_vs_place_detection():
    for pc in ["SM1 4FR", "sm14fr", "TR27 5AF", "M1 1AE"]:
        assert looks_like_postcode(pc), pc
    for place in ["St Ives Cornwall", "Haven Riviera Sands", "Manchester"]:
        assert not looks_like_postcode(place), place


# --- limited-time offers -------------------------------------------------

def test_expired_offers_are_never_served():
    """A price the user cannot get is worse than no price. Offers past their
    end date, or unverified for too long, must be withheld."""
    import datetime
    from scripts.offers.model import Component, Offer

    today = datetime.date(2026, 7, 28)
    base = dict(offer_id="x", chain_id="kfc", title="t", price_gbp=7.99,
                components=(Component("Tender (per piece", 10),),
                source="s", source_url="u")

    assert Offer(**base, last_verified="2026-07-27").is_live(today)
    assert not Offer(**base, last_verified="2026-07-27",
                     valid_to="2026-07-01").is_live(today), "expired offer served"
    assert not Offer(**base, last_verified="2026-01-01").is_live(today), \
        "stale offer served"


def test_offer_with_unresolvable_component_is_dropped():
    """An invented bundle would top the ranking precisely because it looks too
    good, so unresolved compositions must never be published."""
    from scripts.offers.model import Component, Offer, expand

    menu = [{"name": "Tender (per piece, average)", "kcal": 125, "protein_g": 13.1}]
    good = Offer("a", "kfc", "10 Tenders", 7.99,
                 (Component("Tender (per piece", 10),), "s", "u", "2026-07-28")
    row = expand(good, menu)
    assert row and row["protein_g"] == 131.0 and row["kcal"] == 1250.0

    bad = Offer("b", "kfc", "Mystery Box", 5.0,
                (Component("Nonexistent Item", 3),), "s", "u", "2026-07-28")
    assert expand(bad, menu) is None


def test_offer_prefers_per_unit_rows_over_multipacks():
    """Matching a multi-pack row would multiply an already-multiplied quantity."""
    from scripts.offers.model import Component, Offer, expand

    menu = [
        {"name": "Tender (per piece, average)", "kcal": 125, "protein_g": 13.1},
        {"name": "5 Tenders Sharing Box", "kcal": 625, "protein_g": 65.5},
    ]
    offer = Offer("a", "kfc", "10 Tenders", 7.99,
                  (Component("Tender", 10),), "s", "u", "2026-07-28")
    row = expand(offer, menu)
    assert row["protein_g"] == 131.0, f"used the wrong base row: {row}"


def test_addons_and_modifiers_are_not_orderable():
    """Scaling to pub and casual-dining chains filled menus with "Add …"/
    "Extra …" rows. A bare "Add A Grilled Chicken Breast" is ~100% protein by
    calories, so it outranks every real meal while being unbuyable alone."""
    for name in ["ADD A GRILLED CHICKEN BREAST", "Add Turkey Carvery 100g",
                 "Extra Chicken Breast", "& Chicken Breast",
                 "Soy sauce sachet", "Swap to sweet potato fries"]:
        assert not _is_orderable(
            {"name": name, "kcal": 120, "protein_g": 26,
             "chain_id": "beefeater"}), name

    # Real dishes must survive.
    for name in ["8OZ SIRLOIN STEAK WITH PEAS", "Flattened Half Roast Chicken",
                 "Chicken Katsu Curry"]:
        assert _is_orderable(
            {"name": name, "kcal": 700, "protein_g": 45,
             "chain_id": "beefeater"}), name


def test_component_categories_are_not_orderable():
    """PizzaExpress files toppings under "Extra Toppings" — a bare "Chicken"
    row there is a topping, not a dish."""
    assert not _is_orderable({"name": "Chicken", "kcal": 60, "protein_g": 13,
                              "chain_id": "pizza_express",
                              "category": "Extra Toppings"})
    assert _is_orderable({"name": "American Hot", "kcal": 900, "protein_g": 40,
                          "chain_id": "pizza_express",
                          "category": "Pizzas - Classic"})


def _run_all() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL  {name}: {e}")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
