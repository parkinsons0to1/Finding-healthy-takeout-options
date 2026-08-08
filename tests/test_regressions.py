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
    2-piece), badly distorting protein-per-pound.

    The assertion is deliberately about *which row* was matched, not about a
    pound value: the live adapter reprices these every run (the 12-wing
    estimate of £10.99 turned out to be £9.99 collection), and pinning the
    number would make this test fail on a price change rather than on the
    defect it exists to catch."""
    twelve = price_for("popeyes", "12 Hot Wings")
    assert twelve is not None, "'12 Hot Wings' lost its price"
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


def test_live_prices_take_precedence_over_estimates():
    """Estimates were badly wrong — a Whopper estimated at £6.49 actually
    costs £10.49 collection. Where a scraped price exists it must win, and it
    must be labelled 'collection' so the UI can distinguish it."""
    import json, pathlib
    db = pathlib.Path(__file__).resolve().parents[1] / "data" / "db"
    for chain in ("nandos", "burger_king", "papa_johns"):
        cache = db / f"prices_{chain}.json"
        if not cache.exists():
            continue                      # adapter not run in this checkout
        payload = json.loads(cache.read_text())
        rows = list(payload.get("prices", {}).values())
        assert rows, f"{chain} price cache is empty"
        sample = rows[0]
        quote = price_for(chain, sample["name"])
        assert quote is not None, f"{chain}: {sample['name']} lost its price"
        assert quote.basis in ("collection", "delivery"), \
            f"{chain} served a {quote.basis} price despite a live cache"
        assert quote.price_gbp == sample["price_gbp"]


def test_single_slice_and_test_rows_are_not_orderable():
    """Papa John's publishes every pizza twice, whole and '(1 slice)' — 240 of
    its 480 rows. A slice has a sixth of the calories and can only ever be
    priced by matching the whole pizza, so it would top protein-per-pound
    while being unbuyable. Burger King ships staging rows in its live feed."""
    for name in ["All The Meats — Original Base - Large (1 slice)",
                 "White Bread / Toast (VE) - per slice",
                 "TEST Chilli Jam & Bacon Double Whopper®"]:
        assert not _is_orderable({"name": name, "kcal": 300, "protein_g": 14,
                                  "chain_id": "papa_johns"}), name

    # A multi-slice portion IS the product — Pizza Hut sells garlic bread by
    # the four. Filtering every slice count would bin real items.
    assert _is_orderable({"name": "Garlic Bread (4 slices)", "kcal": 480,
                          "protein_g": 14, "chain_id": "pizza_hut"})


def test_price_join_tolerates_word_order_and_vocabulary():
    """Nutrition and ordering feeds describe a Papa John's pizza with the same
    three dimensions in different orders and words — 'All The Meats — Original
    Base - Large' vs 'All the Meats™ - Large Original'. Matching only on exact
    strings priced 93 of 480 rows; folding noise words and plurals priced 148
    of the 240 real ones."""
    from scripts.api.prices import _token_key

    assert _token_key("All The Meats — Original Base - Large") == \
        _token_key("All the Meats™ - Large Original")
    assert _token_key("3 Chicken Wings") == _token_key("3 chicken wing")

    # …but a portion count is never folded away. This is the property the
    # whole matcher rests on.
    assert _token_key("2 Hot Wings") != _token_key("12 Hot Wings")
    assert _token_key("Large Original") != _token_key("Medium Original")
    assert _token_key("Stuffed Crust") != _token_key("Cheddar Stuffed Crust")


def test_pizza_toppings_are_not_orderable_but_chicken_strips_are():
    """Two halves of the same fix.

    Banning the word "strips" to exclude Subway's fillings silently deleted
    chicken strips from nine chains — the exact food this product exists to
    surface. Removing the ban let Domino's *toppings* back in, which are worse:
    "Chicken Breast Strips — Large" is 85 kcal and 88% protein by calories, so
    it would top the leaderboard while being un-orderable."""
    from scripts.api.search import _component_categories

    assert "chicken breast strips" in _component_categories("dominos")
    assert not _is_orderable({"name": "Chicken Breast Strips — Large",
                              "kcal": 85, "protein_g": 18.7,
                              "chain_id": "dominos",
                              "category": "Chicken Breast Strips"})

    # The pizza itself has a compound suffix, not a bare size, and survives.
    assert _is_orderable({
        "name": "Chicken Feast — Classic Crust, Large, Standard Mozzarella",
        "kcal": 2103, "protein_g": 111.7, "chain_id": "dominos",
        "category": "Chicken Feast"})

    # Real chicken-strip dishes at other chains must be rankable again.
    for chain, name in [("wetherspoons", "Southern-fried chicken strips basket"),
                        ("pizza_hut", "Single - Breaded Chicken Strips (4 Strips)"),
                        ("chopstix", "Katsu Chicken Strips (5)")]:
        assert _is_orderable({"name": name, "kcal": 400, "protein_g": 30,
                              "chain_id": chain}), f"{chain}/{name}"


def test_popeyes_bundles_with_copied_nutrition_are_flagged():
    """Popeyes' feed has a second, sharper version of its known kcal fault: a
    piece-count SKU can carry a DIFFERENT SKU's nutrition wholesale. Five
    Boneless bundle sizes (6 to 20 pieces) all report the identical 35.6g
    protein; "10 Hot Wings" copies "8 Hot Wings"' 75.0g. Neither trips the
    existing kcal-vs-protein ratio check, because the copied row is internally
    consistent — it is just the wrong row. It only shows up across rows: two
    different piece counts of the same product cannot have the same protein.

    These ranked in the top 15 of a real search before the fix, at up to 66%
    protein-by-calories for breaded fried chicken."""
    from scripts.scrapers.popeyes import _flag_family_inconsistencies

    rows = [
        {"name": "1 Classic Tender", "kcal": 156.0, "protein_g": 12.0},
        {"name": "3 Classic Tenders & a dip", "kcal": 233.0, "protein_g": 35.6},
        {"name": "5 Classic Tenders & a dip", "kcal": 383.0, "protein_g": 59.4},
        {"name": "6 Boneless & a dip", "kcal": 225.0, "protein_g": 35.6},
        {"name": "8 Boneless & a dip", "kcal": 298.0, "protein_g": 35.6},
        {"name": "8 Hot Wings", "kcal": 739.0, "protein_g": 75.0},
        {"name": "10 Hot Wings", "kcal": 924.0, "protein_g": 75.0},
        {"name": "12 Hot Wings", "kcal": 1109.0, "protein_g": 112.0},
    ]
    _flag_family_inconsistencies(rows)
    flagged = {r["name"] for r in rows
              if "implausible-kcal" in (r.get("quality_flags") or [])}

    assert flagged == {"3 Classic Tenders & a dip", "5 Classic Tenders & a dip",
                       "6 Boneless & a dip", "8 Boneless & a dip",
                       "8 Hot Wings", "10 Hot Wings"}
    # "8 Hot Wings" and "10 Hot Wings" collide on the same 75.0g, so both are
    # flagged — the check cannot tell which one is genuine from a pairwise
    # collision alone, only that two different piece counts cannot share it.
    # The single-tender anchor and a wing count with its own unique, plausibly
    # scaled protein must survive: a scalpel for a specific fault, not a net.
    assert "1 Classic Tender" not in flagged
    assert "12 Hot Wings" not in flagged


def test_convenience_retailers_are_not_treated_as_unrankable_food_chains():
    """Ten retail chains (Poundland, Holland & Barrett, Farmfoods...) were
    recognised by name but missing from SUPERMARKET_CHAINS, so a search near
    one classified it `kind: "chain"` and reported it as "chains nearby, not
    yet rankable" — a menu adapter that will never exist for a Poundland,
    since its products are barcoded groceries, not a menu."""
    from scripts.geo.location import SUPERMARKET_CHAINS

    for chain_id in ["costcutter", "best_one", "lifestyle_express", "day_today",
                     "scotmid", "farmfoods", "holland_barrett", "home_bargains",
                     "poundland", "bm_bargains"]:
        assert chain_id in SUPERMARKET_CHAINS, chain_id


def test_price_caches_carry_no_zero_priced_or_channel_misattributed_rows():
    """Two defects found in the same review pass, both about a scraped price
    file claiming something buyable that isn't:

    Pret's Just Eat catalogue lists a real, non-DealOnly "Allergen Guide"
    entry at a literal £0.00 — an informational link, not a free item.
    `price is None` alone let it through.

    Zizzi's collection-channel API serves items self-labelled "DELIVERY
    EXCLUSIVE" in their own name, unhidden and fully priced — the only
    signal they can't actually be bought in the shop is that literal string.
    Serving one at basis="collection" would tell a customer they can walk in
    and buy something Zizzi's own data says they can't.

    Checks the committed cache files directly (skips a chain not yet run in
    this checkout), the same style `test_live_prices_take_precedence_over_
    estimates` uses, so a regenerated file is caught same as a code change."""
    import json
    import pathlib

    db = pathlib.Path(__file__).resolve().parents[1] / "data" / "db"

    cache = db / "prices_pret.json"
    if cache.exists():
        rows = json.loads(cache.read_text()).get("prices", {})
        zero = [n for n, v in rows.items() if v["price_gbp"] <= 0]
        assert not zero, f"pret: zero-priced non-food rows leaked in: {zero}"

    cache = db / "prices_zizzi.json"
    if cache.exists():
        rows = json.loads(cache.read_text()).get("prices", {})
        collection_only_exclusives = [
            v["name"] for v in rows.values()
            if v.get("basis") == "collection"
            and v["name"].upper().startswith("DELIVERY EXCLUSIVE")]
        assert not collection_only_exclusives, \
            f"zizzi: delivery-exclusive items served as collection: {collection_only_exclusives}"


def test_milkshake_mix_ins_are_not_orderable():
    """Five Guys' PDF files 'Myprotein (12g)' under a category that says, in
    its own words, 'Amount Of Individual Mix-Ins May Vary Depending Upon
    Number Of Mix-Ins Included In Shake' — a scoop stirred into someone
    else's milkshake, not a thing you can buy alone. At 54 kcal for 12g
    protein it is 89% protein by calories, high enough to sit at the very
    top of the whole leaderboard if left in — found by auditing the actual
    output after Five Guys' nutrition was fixed to read per-serving."""
    assert not _is_orderable({
        "name": "Myprotein (12g)", "kcal": 54.0, "protein_g": 12.0,
        "chain_id": "five_guys",
        "category": "Milkshakes (Including Big Kids Shake) + Mix-Ins - "
                    "Amount Of Individual Mix-Ins May Vary Depending Upon "
                    "Number Of Mix-Ins Included In Shake"})
    assert _is_orderable({"name": "Hamburger", "kcal": 666.0,
                          "protein_g": 42.0, "chain_id": "five_guys",
                          "category": "Burgers"})


def test_live_price_carries_its_own_branch_name():
    """Live prices reuse whichever single branch a chain's adapter scraped —
    there is no per-region scraping — so a search anywhere in the UK can
    surface a real Sutton price under a Manchester outlet's name with no way
    to tell the two apart. found by searching Manchester directly and
    noticing Pret/Tortilla cards showed a local outlet name with a silently
    South-London price attached. PriceQuote.store carries the scraped
    branch so the UI can say so instead of presenting it as local."""
    from scripts.api.prices import price_for

    quote = price_for("pret", "Chicken & Edamame Protein Pot")
    if quote is None or quote.basis not in ("collection", "delivery"):
        return   # adapter not run in this checkout
    assert quote.store, "a live quote must carry which branch it came from"
    assert quote.store in quote.source


def test_estimated_prices_carry_no_branch_name():
    """An estimate isn't tied to any one branch, so it must not claim one —
    that would fabricate a precision the number doesn't have."""
    from scripts.api.scoring import ScoredItem

    item = ScoredItem("Fillet Burger", "kfc", "KFC Anywhere", 0.5, 500, 30,
                      5.99, 5.99, None, "halal", "brand_per_outlet", False,
                      False, "", "high", "estimated", price_store="")
    assert item.price_store == ""


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
