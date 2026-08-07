# Phase 0 results — SM1 4FR (Sutton, London)

**v3 — 2026-07-28.** v1 was hand-curated estimates. v2 rebased nutrition on a live/official scraper pipeline. **v3 corrects two wrong halal calls the user caught: KFC Sutton and Popeyes are both halal**, not `not_halal` as v2 said. See "Halal correction" below — it's the most important finding in this document, because halal is the one column where being wrong is worse than not having an answer at all.

## Halal correction (read this first)

v2 marked KFC Sutton and Popeyes as `not_halal`. Both were wrong, for two different reasons:

- **KFC Sutton:** the previous session ran a partial page fetch of `kfc.co.uk/halal`, which is actually a JS app backed by an API the fetch couldn't execute. The text it returned named three unrelated branches and explicitly said no full list was available — "Sutton not mentioned" got misread as "Sutton confirmed not halal." **Absence in a non-exhaustive fetch is not evidence of absence.** Corrected to `halal`, evidenced by Uber Eats/Just Eat halal-category listings plus user confirmation.
- **Popeyes:** the `not_halal` entry was never sourced in the first place — it was written with a plausible-sounding fake citation and no actual search was run. Corrected to `halal` (chain-wide, supplier-level — Popeyes UK states its chicken is halal-sourced, though only the Stratford branch is independently HMC-certified; most branches share fryers with non-halal items like pork bacon sides, worth an in-store check for strict standards).

Because two of the wrong calls happened to be false negatives (marking real halal options as not-halal), the rest of the halal table was re-verified from scratch rather than assumed correct just for agreeing with intuition — McDonald's, Burger King, Taco Bell, Greggs, and Pret's `not_halal` status all now trace to an actual search performed this session (full log: [DATA_SOURCES.md](DATA_SOURCES.md)).

**Effect on the ranking: it's large.** Under the corrected halal column, **7 of the top 8 items on the entire MacroScore leaderboard are halal** — Popeyes and KFC dominate. Under v2's wrong data, the best halal answer looked like GDK's salad bowl at 4.0 g protein/£; the real best halal answer is Popeyes 12 Hot Wings at **12.7 g protein/£**, more than 3x better.

## What's real vs. estimated

| Layer | Status |
|---|---|
| **Location** | Real: SM1 4FR → (51.360125, −0.190664) via postcodes.io |
| **Outlets** | Real: 24 chain outlets + supermarkets within 1 mile from the **FSA FHRS open API** — `data/phase0/outlets.csv` |
| **McDonald's / Popeyes / Greggs nutrition** | **Live-scraped** from each chain's own API (467 items) |
| **KFC / Subway nutrition** | **Official brand PDFs** (June 2026 editions) |
| **GDK / BK / Nando's / Taco Bell** | Still curated (medium confidence) — app-API adapters not yet built, see DATA_SOURCES.md |
| **Prices** | All **estimated** London walk-in prices — per-outlet price adapters are Phase 1 |
| **Halal** | Corrected 2026-07-28: **KFC halal, Popeyes halal, GDK halal**; McDonald's/BK/Taco Bell/Greggs/Pret/Nando's not halal (all re-verified by search); Subway/Kokoro/Morley's per-store unverified |
| **Discounts** | Curated rules; scoring assumes max eligibility (student + first app order) |

## Rankings

(Regenerate: `python3 scripts/phase0_rank.py`. Scrapers: `python3 -m scripts.scrapers.run_all`.)

### MacroScore ranking — protein ≥ 35% of calories

| # | Item | Chain | Protein | kcal | P% kcal | Price | Final | g protein/£ | Halal | Conf |
|--:|------|-------|--------:|-----:|--------:|------:|------:|------------:|-------|------|
| 1 | 12 Hot Wings | popeyes | 112g | 1109 | 40% | £10.99 | £8.79 (app 1st order) | **12.7** | **halal** | high |
| 2 | 3pc Signature Louisiana Chicken | popeyes | 83g | 710 | 47% | £8.49 | £6.79 (app 1st order) | **12.2** | **halal** | high |
| 3 | 6 Hot Wings | popeyes | 56g | 554 | 40% | £6.49 | £5.19 (app 1st order) | **10.8** | **halal** | high |
| 4 | 3 Piece Original Recipe | kfc | 66g | 723 | 37% | £6.49 | £6.49 | **10.2** | **halal** | high |
| 5 | 2pc Signature Louisiana Chicken | popeyes | 55g | 473 | 47% | £6.99 | £5.59 (app 1st order) | **9.8** | **halal** | high |
| 6 | Original Recipe Chicken (1 piece) | kfc | 22g | 241 | 37% | £2.29 | £2.29 | **9.6** | **halal** | high |
| 7 | 5 Tenders | kfc | 66g | 625 | 42% | £7.49 | £7.49 | **8.7** | **halal** | high |
| 8 | 3 Tenders | kfc | 39g | 375 | 42% | £5.49 | £5.49 | **7.2** | **halal** | high |
| 9 | 1/2 Chicken | nandos | 74g | 637 | 46% | £10.75 | £10.75 | **6.9** | not_halal | medium |
| 10 | Chicken Butterfly Breast | nandos | 54g | 330 | 65% | £9.95 | £9.95 | **5.4** | not_halal | medium |
| 11 | 4 Chicken Thighs | nandos | 44g | 448 | 39% | £9.75 | £9.75 | **4.5** | not_halal | medium |
| 12 | Doner Salad Bowl (chicken) | gdk | 32g | 360 | 36% | £7.99 | £7.99 | **4.0** | halal | medium |

### Raw protein-per-£ leaderboard (no density filter) — top 10

| # | Item | Chain | Protein | P% kcal | Final | g/£ | Halal |
|--:|------|-------|--------:|--------:|------:|----:|---|
| 1 | 12 Hot Wings | popeyes | 112g | 40% | £8.79 | **12.7** | halal |
| 2 | 3pc Signature Louisiana Chicken | popeyes | 83g | 47% | £6.79 | **12.2** | halal |
| 3 | 5 Spicy Tenders & a dip | popeyes | 65g | 34% | £5.99 | **10.8** | halal |
| 4 | 6 Hot Wings | popeyes | 56g | 40% | £5.19 | **10.8** | halal |
| 5 | 3 Piece Original Recipe | kfc | 66g | 37% | £6.49 | **10.2** | halal |
| 6 | 2pc Signature Louisiana Chicken | popeyes | 55g | 47% | £5.59 | **9.8** | halal |
| 7 | Original Recipe Chicken (1 pc) | kfc | 22g | 37% | £2.29 | **9.6** | halal |
| 8 | 3 Spicy Tenders & a dip | popeyes | 39g | 34% | £4.39 | **8.9** | halal |
| 9 | 5 Tenders | kfc | 66g | 42% | £7.49 | **8.7** | halal |
| 10 | Hamburger | mcdonalds | 13g | 20% | £1.49 | **8.7** | not_halal |

## Findings

1. **The halal correction dominates everything else in this dataset.** Getting nutrition macros wrong by a few points misranks items; getting halal wrong tells a Muslim user to eat somewhere they can't, or steers them away from the best option available to them. It's the one column the plan (§3.3) singled out as trust-critical, and it's the one column where an unverified process actually shipped a wrong answer. See DATA_SOURCES.md's "Lessons learned" for the process fix.
2. **With the correction, Popeyes and KFC aren't just good value — they're the best *halal* value in Sutton by a wide margin**, not a fallback after excluding the non-halal winners. Nando's (not halal at this branch) has the best raw macros but falls to #9 on price.
3. **Fried chicken clears the 35% filter more often than assumed.** KFC Original Recipe (37%), KFC Tenders (42%), Popeyes Hot Wings (40%), Popeyes Signature Louisiana Chicken (47%) all pass — brand-published data corrected several hand-estimated numbers that had sat just under the line.
4. **Confidence in this dataset should now be read per-row, not per-chain.** McDonald's/Popeyes/Greggs/KFC/Subway nutrition is high-confidence (live or official-PDF); GDK/BK/Nando's/Taco Bell nutrition is still medium-confidence curated data pending their own adapters; every halal flag in `chains.csv` now carries a real, checkable source — but that's a new discipline as of this correction, not a property of the earlier rows.

## Files

```
scripts/scrapers/             plain-HTTP scraper package (5 chains, Firestore/local sink)
data/db/                      scraped output: 716 normalized items across 5 chains
data/phase0/                  outlets, chains (halal evidence — see correction above), menu items, discounts
docs/DATA_SOURCES.md          endpoint registry + halal verification log + lessons-learned
scripts/phase0_rank.py        scoring engine v0.1
```
