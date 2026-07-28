# Phase 0 results — SM1 4FR (Sutton, London)

Hand-rolled MacroMeter dataset for one real postcode, built 2026-07-28, per the [Technical Implementation Plan](TECHNICAL_IMPLEMENTATION_PLAN.md) §7 Phase 0. Goal: prove the MacroScore ranking passes the "would I actually buy #1?" test before writing any scrapers.

## What's real vs. estimated

| Layer | Status |
|---|---|
| **Location** | Real: SM1 4FR → (51.360125, −0.190664) via postcodes.io |
| **Outlets** | Real: 24 chain outlets + supermarkets within 1 mile from the **FSA FHRS open API** (with hygiene ratings, addresses, coordinates) — see `data/phase0/outlets.csv` |
| **McDonald's nutrition** | **Live-scraped** from mcdonalds.com's own `dnaapp` JSON API (45 items, full macros) — raw snapshot in `data/phase0/raw/mcd_nutrition.json`. Confidence: high |
| **Other chains' nutrition** | Hand-curated from brand-published nutrition data. Confidence: medium — **verify against current brand docs before relying** |
| **Prices** | All **estimated** typical Greater London walk-in prices — the per-outlet price adapters are Phase 1 work |
| **Halal status** | Evidence-tiered per plan §3.3: GDK halal (brand-stated chain-wide); McDonald's/BK/Popeyes/Taco Bell/Greggs/Pret not halal (brand-stated); KFC/Nando's/Subway/Morley's/Kokoro **unverified for Sutton** — KFC and Nando's publish official halal branch lists; check them for the Sutton branches |
| **Discounts** | Curated rules in `data/phase0/discounts.csv` (GDK 50% first app order on the OG, Popeyes 20% first app order — user-reported; Subway Student Beans 10% — needs verification). Scoring assumes max eligibility (student + first order available) |

## The neighbourhood

Sutton High Street is unusually dense: **Nando's (0.05mi), Burger King (0.06mi), Subway (0.07mi), GDK (0.12mi), Greggs (0.14mi), Pret (0.18mi), Popeyes (0.31mi), Kokoro (0.32mi), McDonald's (0.37mi), KFC (0.42mi), Taco Bell (0.44mi), Morley's (0.76mi)** — plus Sainsbury's, Tesco Express, Lidl ×2, Asda, M&S and Boots for meal deals. All FHRS hygiene 5 except GDK (4).

## Rankings

(Regenerate anytime: `python3 scripts/phase0_rank.py`)

### MacroScore ranking — protein ≥ 35% of calories

| # | Item | Chain | Protein | kcal | P% kcal | Price | Final | g protein/£ | Halal | Conf |
|--:|------|-------|--------:|-----:|--------:|------:|------:|------------:|-------|------|
| 1 | 1/2 Chicken | nandos | 74g | 637 | 46% | £10.75 | £10.75 | **6.9** | unverified | medium |
| 2 | Chicken Tikka 6-inch | subway | 24g | 270 | 36% | £4.79 | £4.31 (student) | **5.6** | unverified | medium |
| 3 | Chicken Butterfly Breast | nandos | 54g | 330 | 65% | £9.95 | £9.95 | **5.4** | unverified | medium |
| 4 | Chicken Breast Salad Bowl | subway | 24g | 170 | 56% | £5.79 | £5.21 (student) | **4.6** | unverified | medium |
| 5 | 4 Chicken Thighs | nandos | 44g | 448 | 39% | £9.75 | £9.75 | **4.5** | unverified | medium |
| 6 | Doner Salad Bowl (chicken) | gdk | 32g | 360 | 36% | £7.99 | £7.99 | **4.0** | halal | medium |

### Relaxed tier — protein ≥ 30% of calories

| # | Item | Chain | Protein | kcal | P% kcal | Price | Final | g protein/£ | Halal | Conf |
|--:|------|-------|--------:|-----:|--------:|------:|------:|------------:|-------|------|
| 1 | 3 Piece Original Recipe | kfc | 66g | 780 | 34% | £6.49 | £6.49 | **10.2** | unverified | medium |
| 2 | Original Recipe Chicken (1 pc) | kfc | 22g | 260 | 34% | £2.29 | £2.29 | **9.6** | unverified | medium |
| 3 | Chicken Breast Footlong | subway | 52g | 600 | 35% | £7.49 | £6.74 (student) | **7.7** | unverified | medium |
| 4 | 1/2 Chicken | nandos | 74g | 637 | 46% | £10.75 | £10.75 | **6.9** | unverified | medium |
| 5 | Chicken Breast 6-inch | subway | 26g | 300 | 35% | £4.99 | £4.49 (student) | **5.8** | unverified | medium |
| 6 | Chicken Tikka 6-inch | subway | 24g | 270 | 36% | £4.79 | £4.31 (student) | **5.6** | unverified | medium |
| 7 | Steak & Cheese 6-inch | subway | 26g | 340 | 31% | £5.29 | £4.76 (student) | **5.5** | unverified | medium |
| 8 | Chicken Butterfly Breast | nandos | 54g | 330 | 65% | £9.95 | £9.95 | **5.4** | unverified | medium |
| 9 | Egg Protein Pot | pret | 13g | 150 | 35% | £2.60 | £2.60 | **5.0** | not_halal | medium |
| 10 | Chicken Breast Salad Bowl | subway | 24g | 170 | 56% | £5.79 | £5.21 (student) | **4.6** | unverified | medium |

### Raw protein-per-£ leaderboard (no density filter)

| # | Item | Chain | Protein | kcal | P% kcal | Price | Final | g protein/£ | Halal | Conf |
|--:|------|-------|--------:|-----:|--------:|------:|------:|------------:|-------|------|
| 1 | 3 Piece Original Recipe | kfc | 66g | 780 | 34% | £6.49 | £6.49 | **10.2** | unverified | medium |
| 2 | Original Recipe Chicken (1 pc) | kfc | 22g | 260 | 34% | £2.29 | £2.29 | **9.6** | unverified | medium |
| 3 | Hamburger | mcdonalds | 13g | 255 | 20% | £1.49 | £1.49 | **8.7** | not_halal | high |
| 4 | Double Cheeseburger | mcdonalds | 27g | 452 | 24% | £3.19 | £3.19 | **8.5** | not_halal | high |
| 5 | Vegan Sausage Roll | greggs | 11g | 312 | 14% | £1.30 | £1.30 | **8.5** | not_halal | medium |
| 6 | Cheeseburger | mcdonalds | 16g | 303 | 21% | £1.99 | £1.99 | **8.0** | not_halal | high |
| 7 | Double Sausage & Egg McMuffin | mcdonalds | 36g | 552 | 26% | £4.49 | £4.49 | **8.0** | not_halal | high |
| 8 | **The OG Kebab (50% first app order)** | gdk | 34g | 720 | 19% | £8.49 | **£4.25** | **8.0** | **halal** | medium |
| 9 | Double Quarter Pounder w/ Cheese | mcdonalds | 50g | 749 | 27% | £6.29 | £6.29 | **7.9** | not_halal | high |
| 10 | Chicken Breast Footlong | subway | 52g | 600 | 35% | £7.49 | £6.74 (student) | **7.7** | unverified | medium |
| 11 | Sausage Roll | greggs | 10g | 329 | 12% | £1.30 | £1.30 | **7.7** | not_halal | medium |
| 12 | Mayo Chicken | mcdonalds | 12g | 282 | 17% | £1.59 | £1.59 | **7.5** | not_halal | high |
| 13 | Bacon Double Cheeseburger | burger_king | 25g | 380 | 26% | £3.49 | £3.49 | **7.2** | not_halal | medium |
| 14 | 2pc Signature Chicken (20% app) | popeyes | 40g | 560 | 29% | £6.99 | £5.59 | **7.2** | not_halal | medium |
| 15 | Big Arch with Bacon | mcdonalds | 62g | 1103 | 22% | £8.79 | £8.79 | **7.1** | not_halal | high |

## Findings — does the metric pass the sniff test?

1. **The 35% filter is brutal, and that's the product.** Only **6 items** within a mile of SM1 4FR meet protein ≥ 35% of calories. Nando's dominates (grilled chicken, no bun), Subway's salad bowls and leaner subs follow, and GDK only qualifies via the breadless salad bowl. This is exactly the manual research pain MacroMeter kills: you cannot find these 6 items without opening ten nutrition PDFs.

2. **McDonald's has *zero* qualifying items** — confirmed against their own live API data (highest-confidence data in the set). Every burger sits at 17–27% protein-kcal. The fried-chicken and bread tax is real: batter, buns and sauces dilute every mainstream item below the gym threshold.

3. **KFC is the sharpest lesson in why the threshold needs a "near miss" view.** Original Recipe chicken lands at **34%** — misses the filter by one point but is the **best protein-per-£ in Sutton (≈10 g/£)**. The UI should show a relaxed tier rather than silently hiding it (already in the scoring script). Bucket deals via the KFC app would push it well past 10 g/£.

4. **Discounts change the leaderboard, not just prices.** The GDK first-order deal takes the OG Kebab from mid-table to joint-#7 overall at £4.25 — and it's the **top halal-verified value item** in the dataset. Popeyes' 20% app offer moves it two places. Discount rules are load-bearing, validating plan §3.4.

5. **The halal column is mostly "unverified" — and that honesty is a feature.** Only GDK is halal-verified chain-wide near SM1 4FR. KFC and Nando's publish official halal-branch lists that Phase 1 must ingest (plan §3.3, evidence tier 2) — resolving the Sutton branches' status is the single highest-value data task left, since KFC tops the value table and Nando's tops the macro table.

6. **The long tail is invisible without Phase 4.** Morley's, Dallas Chicken, Sam's Chicken, Ollie's Kebab, Legends Kebab (0.05–0.76mi) publish no nutrition — they're under the 250-employee threshold of the calorie-labelling law. Photo/OCR ingestion is the only route; chicken-shop territory is likely competitive on protein-per-£.

## Gaps → Phase 1 backlog (in priority order)

1. **Per-outlet price adapters** (chain click-&-collect APIs) — every price here is an estimate; prices move rankings more than nutrition does.
2. **KFC + Nando's halal-branch-list ingestion** — flips the two best performers from "unverified" to a definitive yes/no for Sutton.
3. **Playwright-based nutrition scrapers** for the JS-rendered chains (GDK, KFC, Nando's, Subway, Taco Bell, Greggs all blocked plain HTTP; McDonald's-style plain JSON is the exception, not the rule).
4. **Verify the curated discount rules** (GDK/Popeyes first-order terms, Subway student %) and add KFC/McDonald's app bucket deals — they likely own the top of the value table.
5. **Meal-deal optimiser teaser**: Sainsbury's (0.06mi), Tesco Express (0.14mi), Boots (0.25mi) are all closer than most chains — Phase 2 data will compete hard at the £3.60–£3.99 price point.

## Files

```
data/phase0/outlets.csv       24 real outlets (FSA FHRS: address, lat/lng, hygiene, distance)
data/phase0/chains.csv        dietary/halal status with evidence tiers + sources
data/phase0/menu_items.csv    84 items (45 live-scraped McDonald's + 39 curated)
data/phase0/discounts.csv     curated discount rules
data/phase0/raw/              raw API snapshots (audit trail per plan §4)
scripts/phase0_rank.py        scoring engine v0.1 (density filter + protein/£ + discounts)
```
