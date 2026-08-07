# MacroMeter remediation plan

Every known defect and gap, why it happens, and the fix. Written 2026-07-28 after a run of field-found bugs — several caught by the user, not by us, which is itself the most important signal in this document.

## Severity model

Ranked by **how wrong the user's decision becomes**, not by how hard the fix is:

| Sev | Meaning |
|---|---|
| **S1** | Tells the user something false they'd act on (wrong halal status, invented price, a shop reported absent that they can see) |
| **S2** | Silently omits something real (unrecognised chain, unscraped menu) — user can't tell the difference between "not there" and "we don't know" |
| **S3** | Degrades ranking quality (estimated prices, ineligible meal-deal items) |
| **S4** | Missing capability, honestly labelled (independents, kosher) |

---

## E1 — Chain recognition is a hardcoded list (S2) ✅ fixed + hardened

**What happened.** A Papa John's inside a Cornwall holiday park was classified as an *independent* because `"papa john"` wasn't in `CHAIN_PATTERNS`. The app reported "1 chain nearby" when there were four. An unrecognised chain loses its menu *and* vanishes from the count, so the app under-reports reality — and the user could disprove it by looking out of the window.

**Root cause.** Recognition depended on a 22-entry regex list, with no mechanism to notice what it was missing. A missing entry fails silently and looks identical to "no chain here".

**Fix.**
1. ✅ Expanded to ~60 UK chains, and widened supermarket coverage.
2. ✅ Split `chains_ranked` from `chains_unranked` and *name* the unranked ones in the UI.
3. **A regex list will always lag reality**, so add a data-driven safety net: a business name appearing at many distinct locations nationally is a chain, whatever our list says. `scripts/chains/detect.py` samples FHRS across the country, counts normalised names by distinct postcode district, and reports frequent names that we don't recognise — turning a silent miss into a review queue item.

## E2 — Cloudflare-blocked chains (S2) ✅ unblocked

**What happened.** Papa John's (the chain literally in the user's resort) and GDK returned 403 to every request, including their official nutrition PDFs. Marked "blocked, needs a browser".

**Root cause.** Not bot-*detection* in the behavioural sense — a TLS fingerprint check. Plain `requests` presents a Python TLS handshake that Cloudflare rejects regardless of headers.

**Fix.** ✅ `curl_cffi` with browser TLS impersonation. Note the environment detail: `impersonate="chrome"` has its connection reset by this session's egress proxy, while `impersonate="safari"` succeeds — so the fetcher tries a sequence of profiles rather than assuming one works. Still no browser automation, still plain HTTP.

Unblocks: **Papa John's** ✅ (86-page PDF, per-slice and per-100g), **GDK** ✅.

## E3 — Prices are all estimates (S1/S3) — the biggest open item

**What happens.** Every price is a typical UK walk-in estimate. Price drives ranking more than nutrition does: a wrong price moves an item further than a wrong macro would.

**Why it's hard.** UK chain prices are set per franchise and never centrally published. Chain click-and-collect APIs need an ordering session (Popeyes, Greggs); app clients need auth (KFC, BK); Just Eat's menu endpoint 401s and its prices are delivery-inflated anyway.

**Fix, in order of tractability.**
1. **Session-bearing collection scrape.** Chain ordering flows issue an anonymous basket/session token before showing a priced menu. Reproduce that handshake per chain (Popeyes' Azure ordering API is the best-documented candidate — we already have its store IDs). Yields true per-outlet collection prices.
2. **Delivery-platform floor.** Where collection is unavailable, take the aggregator price, store `price_basis='delivery'`, and apply a per-chain deflation factor learned from chains where we have both. Label it as an estimate — never launder it into a firm price.
3. **Community confirmation.** One-tap "still £X?" once there's traffic; `price_basis='community'`.
4. **Until then:** the UI already flags every estimate, and `as_of` makes staleness visible. Keep it that way — an estimate rendered like a scraped price is an S1 defect.

## E4 — Meal-deal eligibility is inferred, not known (S3)

**What happens.** Candidates come from Open Food Facts categories, which know nutrition but not what a shop will sell you inside a deal. The optimiser hunts extremes, so it surfaces exactly the wrong rows: a 300 g salad at 1155 kcal, squash listed at 19 g protein, 150 g pistachios *in shell*, raw burger packs.

**Fix.**
1. ✅ Guards added — energy-density and per-pack protein ceilings, single-serve size bounds, multipack/ingredient name filters.
2. **Scrape the retailers' own meal-deal pages** for the authoritative eligible-product lists (Tesco, Sainsbury's, Boots, Co-op), and join to OFF nutrition by barcode/name. This replaces inference with fact and is the real fix.
3. Add a `eligibility_basis` field (`retailer_list` vs `inferred`) so the UI can distinguish them.

## E5 — Halal coverage gaps (S4, correctly labelled)

Burger King and Subway vary per store and have no per-outlet source, so they resolve `unverified`. That's the honest answer, not a defect — but it's addressable:

- **Subway:** publishes separate HALAL nutrition builds, so the data exists; find the per-store indicator.
- **Burger King:** individually-certified branches exist; no published list found yet.
- **Kosher:** not implemented. KLBD and Manchester Beth Din publish certified-establishment lists — structurally identical to the HMC adapter, same `can_prove_negative` discipline.
- **Staleness:** halal status changes (KFC Mitcham dropped it in Feb 2025). Re-resolve on a schedule and surface `fetched_at`.

## E6 — Independents are invisible (S4)

Near St Ives, independents outnumber chains 99:0; at the holiday park, 64:4. They publish nothing because they're under the 250-employee calorie-labelling threshold. This is Phase 5 (photo/OCR + VLM extraction, clearly labelled as estimates, community-verified) and the largest remaining product gap.

## E7 — No regression tests (S2, meta)

**The real lesson of this session.** Four defects reached the user: wrong halal calls, `2 Hot Wings` priced at the 12-wing price, Subway ingredient rows ranked as meals, Papa John's misclassified. Each was cheap to fix and would have been caught by a test.

**Fix.** ✅ `tests/` covering the specific regressions:
- price lookup must not substring-match across portion sizes
- ingredient-only rows must not be orderable
- known chains must be recognised (incl. Papa John's, Domino's, Costa)
- a source that cannot prove a negative must never return `not_halal`
- scoring must exclude items with missing macros rather than impute

## E8 — Operational blind spots (S2)

- **Scraper rot is silent.** Adapters keep "succeeding" with fewer items. Add per-adapter freshness/count alerting: a drop beyond a threshold fails loudly.
- **Halal resolution is slow** — live per-outlet fetches on every search, cached only in-process. Persist resolutions with a TTL so a search is a lookup, not a crawl.
- **Marker validation already exists** for KFC and must stay a hard gate.

---

## Order of work

1. ✅ E2 Cloudflare unlock → Papa John's + GDK adapters
2. ✅ E1 chain-detection safety net
3. ✅ E7 regression tests
4. ✅ E8 persistent halal cache
5. E3 prices (session handshake) — largest remaining ranking risk
6. E4 retailer eligibility lists
7. E5 Subway/BK per-outlet halal, kosher
8. E6 independents via photo/OCR

---

## E9 — Limited-time offers and new menu items (S3) ✅ implemented

**What was missing.** The model knew standard menu items and percentage
discounts, but not **fixed-price bundles** — "10 Tenders Bucket, £7.99". These
are routinely the best protein-per-pound available: that KFC bucket is 131 g of
protein at 42% protein-kcal for £7.99, i.e. **16.4 g/£**, better than any
standard menu item and competitive with a supermarket meal deal. Missing them
meant missing the actual answer.

**Why a discount rule couldn't express it.** A discount modifies a known list
price. An offer *is its own product*, assembled from menu items, with no list
price to discount and macros that exist only as the sum of its parts.

**Design.** `scripts/offers/`:
- `model.py` — `Offer` + `Component`; `expand()` derives macros from real
  scraped rows (10 x the per-piece tender), preferring per-unit rows so a
  multi-pack row can't multiply an already-multiplied quantity.
- `sources/kfc_deals.py` — parses KFC's own deals page, which carries current
  promotions in prose. Deliberately narrow: it emits only what it can turn into
  a resolvable composition.
- `registry.py` — merges **scraped**, **curated** (app-only deals with no
  scrapeable page) and **community** (user-reported) tiers.

**Two safety properties, both tested.**
1. *Composition must resolve.* An unmatched component drops the offer rather
   than publishing guessed macros — an invented bundle would top the ranking
   by construction, exactly because it looks too good.
2. *Expiry is enforced.* Past `valid_to`, or unverified for more than 21 days,
   an offer is withheld. Limited-time offers turn over fast, and a price the
   user cannot get is worse than showing no price.

**Still open.** App-only deals (McDonald's app, KFC app bundles) have no
scrapeable page and rely on the curated/community tiers; a user-submission
route in the UI is the cheapest way to cover the long tail, and
`registry.add_community_offer` already accepts them.
