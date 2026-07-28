# Phase 0 results — SM1 4FR (Sutton, London)

**v2 — 2026-07-28.** First built by hand, then re-based on live-scraped and brand-published data from the new plain-HTTP scraper pipeline (`scripts/scrapers/`, see [DATA_SOURCES.md](DATA_SOURCES.md)). v1's curated estimates got several rankings materially wrong — the corrections are themselves the main finding.

## What's real vs. estimated

| Layer | Status |
|---|---|
| **Location** | Real: SM1 4FR → (51.360125, −0.190664) via postcodes.io |
| **Outlets** | Real: 24 chain outlets + supermarkets within 1 mile from the **FSA FHRS open API** — `data/phase0/outlets.csv` |
| **McDonald's nutrition** | **Live** — mcdonalds.com dnaapp JSON API (45 items) |
| **Popeyes nutrition** | **Live** — Popeyes UK ordering API, 197 items with full macros + veg/vegan flags (found via their Angular bundle; tender multi-pack kcal derived per-piece × n because the brand's per-serving kcal is wrong at source) |
| **Greggs nutrition** | **Live** — open Greggs API, 225 published items with full macros |
| **KFC nutrition** | **Official PDF** — brand-uk.assets.kfc.co.uk/nutrition-allergens.pdf (June 2026 V2) |
| **Subway nutrition** | **Official PDF** — June 2026 UKI nutrition PDF (includes separate HALAL build rows) |
| **GDK / BK / Nando's / Taco Bell** | Still curated (medium confidence) — their sites need app-API adapters, see DATA_SOURCES.md |
| **Prices** | All **estimated** London walk-in prices — per-outlet price adapters are Phase 1 |
| **Halal** | Verified where possible: GDK halal (chain-wide); **KFC Sutton NOT halal** (per kfc.co.uk/halal — nearest halal: Morden London Rd, Colliers Wood); **Nando's Sutton NOT halal** (user-confirmed + brand list); Subway/Kokoro/Morley's per-store unverified |
| **Discounts** | Curated rules; scoring assumes max eligibility (student + first app order) |

## Rankings

(Regenerate: `python3 scripts/phase0_rank.py`. Scrapers: `python3 -m scripts.scrapers.run_all`.)

### MacroScore ranking — protein ≥ 35% of calories

| # | Item | Chain | Protein | kcal | P% kcal | Price | Final | g protein/£ | Halal | Conf |
|--:|------|-------|--------:|-----:|--------:|------:|------:|------------:|-------|------|
| 1 | 12 Hot Wings | popeyes | 112g | 1109 | 40% | £10.99 | £8.79 (app 1st order) | **12.7** | not_halal | high |
| 2 | 3pc Signature Louisiana Chicken | popeyes | 83g | 710 | 47% | £8.49 | £6.79 (app 1st order) | **12.2** | not_halal | high |
| 3 | 6 Hot Wings | popeyes | 56g | 554 | 40% | £6.49 | £5.19 (app 1st order) | **10.8** | not_halal | high |
| 4 | 3 Piece Original Recipe | kfc | 66g | 723 | 37% | £6.49 | £6.49 | **10.2** | not_halal | high |
| 5 | 2pc Signature Louisiana Chicken | popeyes | 55g | 473 | 47% | £6.99 | £5.59 (app 1st order) | **9.8** | not_halal | high |
| 6 | Original Recipe Chicken (1 piece) | kfc | 22g | 241 | 37% | £2.29 | £2.29 | **9.6** | not_halal | high |
| 7 | 5 Tenders | kfc | 66g | 625 | 42% | £7.49 | £7.49 | **8.7** | not_halal | high |
| 8 | 3 Tenders | kfc | 39g | 375 | 42% | £5.49 | £5.49 | **7.2** | not_halal | high |
| 9 | 1/2 Chicken | nandos | 74g | 637 | 46% | £10.75 | £10.75 | **6.9** | not_halal | medium |
| 10 | Chicken Butterfly Breast | nandos | 54g | 330 | 65% | £9.95 | £9.95 | **5.4** | not_halal | medium |
| 11 | 4 Chicken Thighs | nandos | 44g | 448 | 39% | £9.75 | £9.75 | **4.5** | not_halal | medium |
| 12 | Doner Salad Bowl (chicken) | gdk | 32g | 360 | 36% | £7.99 | £7.99 | **4.0** | **halal** | medium |

### Near-miss tier (30–35%) worth knowing about

| Item | Chain | Protein | P% kcal | Final price | g/£ |
|---|---|--:|--:|--:|--:|
| 5 Spicy Tenders & a dip | popeyes | 65g | 34% | £5.99 (app 1st order) | 10.8 |
| 3 Spicy Tenders & a dip | popeyes | 39g | 34% | £4.39 (app 1st order) | 8.9 |
| Spicy Chicken Sandwich | popeyes | 41g | 31% | £5.19 (app 1st order) | 7.9 |
| Chicken Breast Footlong | subway | 52g | 31% | £6.74 (student) | 7.7 |
| Chicken Tikka 6-inch | subway | 28g | 32% | £4.31 (student) | 6.5 |

### Raw protein-per-£ leaderboard (no density filter) — top 10

| # | Item | Chain | Protein | P% kcal | Final | g/£ |
|--:|------|-------|--------:|--------:|------:|----:|
| 1 | 12 Hot Wings | popeyes | 112g | 40% | £8.79 | **12.7** |
| 2 | 3pc Signature Louisiana Chicken | popeyes | 83g | 47% | £6.79 | **12.2** |
| 3 | 5 Spicy Tenders & a dip | popeyes | 65g | 34% | £5.99 | **10.8** |
| 4 | 6 Hot Wings | popeyes | 56g | 40% | £5.19 | **10.8** |
| 5 | 3 Piece Original Recipe | kfc | 66g | 37% | £6.49 | **10.2** |
| 6 | 2pc Signature Louisiana Chicken | popeyes | 55g | 47% | £5.59 | **9.8** |
| 7 | Original Recipe Chicken (1 pc) | kfc | 22g | 37% | £2.29 | **9.6** |
| 8 | 3 Spicy Tenders & a dip | popeyes | 39g | 34% | £4.39 | **8.9** |
| 9 | 5 Tenders | kfc | 66g | 42% | £7.49 | **8.7** |
| 10 | Hamburger | mcdonalds | 13g | 20% | £1.49 | **8.7** |

## Findings (v2 — what the real data changed)

1. **v1 was wrong about fried chicken, and the user called it.** With brand-published data: **KFC Tenders are 42% protein-kcal (PASS)**, KFC Original Recipe is 37% (PASS, not 34%), **Popeyes wings are 40% (PASS)** and Popeyes Signature Louisiana Chicken is **47%** — the single most protein-dense cheap item in Sutton. Twelve items now clear the strict 35% filter, not six. Hand-curated numbers were wrong by 1–13 points at the margin, in both directions (Subway's 6-inch subs *dropped* from 35% to 31% on official data). **Estimates cannot be trusted at threshold boundaries; only scraped brand data can.**
2. **Popeyes Sutton is the protein king of SM1 4FR** — top 4 of the overall leaderboard, up to **12.7g protein/£** with the 20% first-app-order discount. Nando's, the v1 winner, drops to #9 on price despite the best macros.
3. **Tenders nuance:** KFC's tender passes easily (42%); Popeyes' tenders sit at 31–34% (per-piece derivation) — spicy beats classic by ~3 points. Popeyes' own per-serving kcal for tender multi-packs is *wrong at source* (3 tenders listed at fewer kcal than 1), caught by the pipeline's plausibility check — the cross-validation layer in the plan §3.1 is not optional.
4. **The halal picture is now definitive for the two chains that matter:** KFC Sutton and Nando's Sutton are both **not halal** (KFC's own halal page; nearest halal KFCs are Morden London Rd and Colliers Wood). For a halal user in Sutton the strict-filter answer is **GDK's Doner Salad Bowl** — or the Morden/Colliers Wood KFC trip. Subway Sutton is worth resolving: Subway publishes separate HALAL nutrition builds, so some stores are certified.
5. **Five chains now have automated, no-Playwright data feeds** (McDonald's, Popeyes, Greggs, KFC, Subway = 716 items) storable to Firebase in one command. BK/Nando's/Taco Bell/GDK need the app-API tier (documented in DATA_SOURCES.md).

## Files

```
scripts/scrapers/             plain-HTTP scraper package (5 chains, Firestore/local sink)
data/db/                      scraped output: 716 normalized items across 5 chains
data/phase0/                  outlets, chains (halal evidence), menu items, discounts
docs/DATA_SOURCES.md          endpoint registry: working, blocked, and how each was found
scripts/phase0_rank.py        scoring engine v0.1
```
