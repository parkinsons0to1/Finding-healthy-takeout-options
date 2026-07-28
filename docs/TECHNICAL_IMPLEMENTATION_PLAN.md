# MacroMeter — Technical Implementation Plan

> *A thermometer for your macros.* Input your location, get the cheapest protein near you — ranked by protein-per-pound after every discount you're entitled to, filtered by your dietary requirements.

**Target market for v1: United Kingdom** (StudentBeans, UNiDAYS, £3.85 meal deals, GDK, and mandatory calorie labelling all point here — and UK law is unusually favourable to this product, see §3.1).

---

## 1. Product definition

### 1.1 The core loop

1. User grants location access (browser Geolocation API — on iPhone/iPad Safari this is backed by Apple's Core Location framework, which satisfies the "use Apple's frameworks" preference on the web) **or** types a postcode.
2. User sets dietary filters: **halal / kosher / vegetarian / vegan** (multi-select) and a macro target (default: **protein ≥ 35% of calories**).
3. MacroMeter finds fast-food outlets and supermarkets nearby, pulls their menus/meal deals with **nutrition + live prices**, applies **applicable discounts** (StudentBeans, UNiDAYS, first-order app offers, vouchers), and computes the **final effective price**.
4. Results are ranked by **MacroScore** — grams of protein per £ spent, constrained by the user's macro target.

### 1.2 The ranking metric (be precise about "calorie:protein:price ratio")

Three separate numbers, all shown, one used for ranking:

| Metric | Formula | Purpose |
|---|---|---|
| **Protein density** | `protein_g × 4 / total_kcal` | The gym filter. User default: ≥ 0.35 (35% of calories from protein). Hard filter, not a ranking term. |
| **Protein per £** | `protein_g / final_price_gbp` | **Primary ranking key.** "Final price" = list price − best applicable discount. |
| **Calories per £** | `kcal / final_price_gbp` | Secondary sort / shown for bulkers; user can flip the ranking to this. |

**MacroScore (default)** = protein-per-£ among items passing the protein-density filter and dietary filters. This is deliberately simple and explainable; a blended weighted score can come later as a user setting (e.g. `w₁·protein/£ + w₂·kcal/£`).

Meal deals are scored as a **bundle**: the combination of main + snack + drink that maximises protein at the fixed price (see §6).

### 1.3 Explicit non-goals for v1

- No ordering/checkout — we deep-link to the restaurant's app/site.
- No independent restaurants (no structured data) — that's Phase 4 with photo/OCR ingestion.
- No delivery-price mode (Uber Eats prices are inflated ~20–40%; we track **walk-in/collection** prices for v1 and clearly label any price whose provenance is a delivery platform).

---

## 2. Why this needs a data platform, not just an app

The hard part of MacroMeter is not the web app — it's building and keeping fresh a **joined dataset that exists nowhere else**:

```
outlet (location) ⋈ menu item ⋈ nutrition ⋈ live price ⋈ dietary status ⋈ applicable discounts
```

Each of those columns has a *different* source of truth, different freshness requirements, and different reliability. The architecture (§5) is therefore an ingestion/normalisation pipeline feeding a query API, with the web app as a thin client on top.

---

## 3. Sources of truth

### 3.1 Nutrition data (per chain menu item)

**The UK regulatory tailwind:** the Calorie Labelling (Out of Home Sector) (England) Regulations 2021 (in force since April 2022) forces every food business with 250+ employees — i.e. every chain we care about — to publish calories on menus and websites. Every major chain therefore maintains a public **nutrition & allergen document or endpoint**. This is our primary source of truth.

| Source | What it gives us | Access method | Reliability |
|---|---|---|---|
| **Chain nutrition pages/PDFs** (McDonald's, KFC, Burger King, Subway, Greggs, Popeyes UK, GDK, Nando's, Taco Bell UK, Wendy's UK…) | Full macros (kcal, protein, carbs, fat, salt) + allergens per item, straight from the brand | Scrape HTML tables / JSON endpoints; parse PDFs (many chains publish a quarterly "Nutrition & Allergen" PDF) | **Highest** — legally mandated, brand-published |
| **Chain ordering apps' internal APIs** | Same nutrition attached to live menu objects (and prices — see §3.2) | Reverse-engineered JSON endpoints their own web-ordering front-ends call | High, but fragile to app changes |
| **Nutritionix API** (restaurant database) | Structured macros for major chains, normalised | Commercial REST API (free tier available) | Good bootstrap/cross-check; US-weighted, UK coverage partial |
| **Open Food Facts** | Crowdsourced barcode-level nutrition — essential for **supermarket meal-deal products** | Free open API, bulk dumps | Variable per item; great coverage of UK supermarket SKUs |
| **Supermarket product pages** (Tesco, Sainsbury's, Boots, Co-op, Morrisons) | Nutrition per meal-deal-eligible SKU | Scrape product detail pages / internal search APIs (Tesco's official public API was discontinued, so scraping it is) | High — retailer-published, mandated back-of-pack data |

**Strategy:** brand-published data is canonical. Nutritionix/Open Food Facts are used to bootstrap, cross-validate (flag any item where two sources disagree by >10% on protein), and fill gaps. Every nutrition record stores its `source`, `source_url`, and `fetched_at` — provenance is a first-class column.

### 3.2 Live prices (the hardest column)

Fast-food prices in the UK vary **by outlet** (franchise pricing) and are not centrally published. Options, in order of preference:

1. **Chain web-ordering APIs (click & collect):** most chains (McDonald's, KFC, BK, GDK, Popeyes, Subway) let you pick a store on their website/app and see that store's collection menu with prices. The underlying JSON endpoints take a store ID → return the per-outlet priced menu. This is the truest walk-in price available programmatically. Build one adapter per chain.
2. **Delivery aggregators (Deliveroo / Uber Eats / Just Eat storefronts):** complete per-outlet menus with prices, one integration covers many chains — but prices are inflated. Use only as **fallback**, stored with `price_basis = 'delivery'` and visually flagged; optionally apply a learned per-chain deflation estimate, clearly labelled as an estimate.
3. **Community price reports (Phase 3+):** users confirm/correct the price at the till, à la petrol-price apps. Cheap trust-building mechanism once there's traffic.
4. **Meal deal prices:** trivially easy — the whole point is the price is fixed (£3.85 Tesco Clubcard, £3.60 Sainsbury's, £3.99 Boots…). One record per retailer per deal tier, updated by a weekly scrape; the work is in the *eligible product lists* (scraped from each retailer's meal-deal category pages).

**Freshness model:** prices re-scraped per outlet on a rolling schedule (target: every 72h for outlets near active users, weekly elsewhere), nutrition monthly, meal-deal eligibility weekly. Every displayed price shows "as of \<date\>".

### 3.3 Dietary status (halal / kosher / vegetarian / vegan)

This is a **trust-critical** column — a wrong halal flag is a product-killing error. Rules:

- **Vegetarian / vegan:** chains label this themselves in the nutrition/allergen docs (mandated-ish, universally provided). Machine-ingested alongside macros. Confidence: high.
- **Halal:** *never inferred*. Three evidence tiers, stored per **outlet** (not per chain — KFC is halal in ~130 specific UK branches, not everywhere):
  1. **Certifier registries:** HMC (Halal Monitoring Committee) publishes its certified outlet list; HFA (Halal Food Authority) certifies at supplier/chain level. Scrape/ingest both.
  2. **Brand statements:** KFC UK and Nando's publish official lists of their halal branches; GDK and most kebab chains are halal chain-wide and say so. Curated ingestion with `source_url`.
  3. Anything else → displayed as **"unverified — ask in store"**, never as halal.
- **Kosher:** structurally identical (KLBD / Manchester Beth Din certification lists), but UK fast-food kosher coverage is near-zero — the filter mostly matters for supermarket products (kosher-certified SKUs on Open Food Facts / retailer data). Ship the filter, set expectations in UI.
- Each dietary flag carries `evidence_tier` (certified / brand-stated / community / unverified) and the UI always shows *why* an item is flagged halal ("HMC-certified outlet", link).

### 3.4 Discounts

Model discounts as **rules**, not prices, because applicability depends on the user (student? first order? has the app?):

| Discount type | Source of truth | Ingestion |
|---|---|---|
| Student platforms (**StudentBeans, UNiDAYS, TOTUM**) | Their offer listings (auth-walled) | Curated table maintained via a weekly review job + community reports. Terms are simple and few (~30–50 food offers live at any time in the UK), so manual curation is genuinely viable and more accurate than fighting their login walls. |
| **First-order app offers** (e.g. GDK ~50% off the OG Kebab on first app order, Popeyes 20% off first app order, McDonald's app deals) | The chains' own apps/T&Cs | Curated table with `conditions: first_order`, `requires_app: true`, expiry, and source link |
| Voucher aggregators (VoucherCodes, hotukdeals) | Their listings | Phase 3: scraped feed → human-review queue (high junk rate) |
| Loyalty schemes (McDonald's Rewards, Greggs App, Subway Rewards) | Chain apps | Phase 3+; modelled as "effective % back" toggle |

**Discount rule schema (sketch):** `{chain_id, scope (item|order), item_matcher, type (percent|fixed|bogof), value, conditions {student_platform?, first_order?, requires_app?, min_spend?}, valid_from/to, source_url, last_verified_at}`.

The user profile stores eligibility booleans ("I have UNiDAYS", "I've never ordered on the GDK app") and the scoring engine applies the **single best applicable discount** per item (UK offers almost never stack). Final price and the applied discount are both shown ("£3.49 → **£1.75** with GDK app first order").

### 3.5 Outlets near me

- **Geocoding manual input:** [postcodes.io](https://postcodes.io) — free, open, UK postcode → lat/lng.
- **Outlet locations:** each chain's own store-locator API (needed anyway for per-store pricing, §3.2) is the primary source; cross-checked against the **FSA Food Hygiene Ratings (FHRS) open API** (free, every food business in the UK with address + hygiene score — the hygiene rating is a nice free bonus column) and OpenStreetMap/Overpass.
- **Maps on the front end:** **Apple MapKit JS** — Apple's official web framework (fits the "Apple frameworks" preference; free tier: 250k map views/day with an Apple Developer account). Fallback: Leaflet + OSM tiles at zero cost.

### 3.6 Legal & compliance notes on the sources

- **Scraping:** UK has no general anti-scraping statute; publicly available factual data (prices, nutrition — facts are not copyrightable) is the defensible end of the spectrum. Mitigations: respect robots.txt where feasible, rate-limit politely, scrape brand sites (whose data they're legally obliged to publish) rather than aggregators where possible, cache rather than hammer, and keep per-source kill switches. Auth-walled sources (StudentBeans/UNiDAYS) are curated by humans, not scraped through logins.
- **GDPR:** location is personal data. Process it transiently for the query (don't store precise location by default), lawful basis = consent via the browser permission prompt + our own consent copy. Postcode-only mode as the privacy-friendly path.
- **Accuracy disclaimers:** allergen/halal/price data shown with provenance and "verify in store" language. This is both ethically necessary and the standard liability shield.

---

## 4. System architecture

```
┌────────────────────────────  Data plane  ────────────────────────────┐
│                                                                      │
│  Scraper workers (Playwright/HTTP, one adapter per source)           │
│    chains: mcdonalds, kfc, gdk, popeyes, subway, greggs, bk, …       │
│    supermarkets: tesco, sainsburys, boots, coop                      │
│    registries: hmc, fsa_fhrs, openfoodfacts                          │
│         │  raw JSON/HTML/PDF snapshots → S3 (audit trail)            │
│         ▼                                                            │
│  Normalisation & entity resolution  (raw → canonical menu items,     │
│    unit normalisation, cross-source validation, diff vs previous)    │
│         ▼                                                            │
│  PostgreSQL + PostGIS  (canonical store)                             │
│         ▼                                                            │
│  Human review queue (Retool/internal page) for: new items, price     │
│    outliers, dietary-flag changes, discount curation                 │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌────────────────────────────  Serving plane  ─────────────────────────┐
│  Query API (tRPC/REST): /search?lat&lng&filters → scored results     │
│    PostGIS radius query → join menus/prices/diet → apply user's      │
│    discount eligibility → score → rank   (Redis cache per geohash)   │
│                                                                      │
│  Web app: Next.js (TypeScript) PWA                                   │
│    Geolocation API (Core Location on iOS Safari) / postcode input    │
│    MapKit JS map + ranked list, filter chips, MacroScore badges      │
└──────────────────────────────────────────────────────────────────────┘
```

**Stack choices (boring on purpose):**

- **Monorepo:** TypeScript end-to-end. Next.js (App Router) on Vercel for the app; API routes/tRPC for serving.
- **Scrapers:** TypeScript + Playwright where a browser is needed, plain `fetch` for JSON endpoints, `pdf-parse`/Camelot-style extraction for nutrition PDFs. Run as scheduled jobs (Fly.io machines / Railway cron / GitHub Actions for the cheapest start). Each adapter implements a common interface: `fetchOutlets()`, `fetchMenu(outletId)`, `fetchNutrition()` → emits versioned raw snapshots.
- **DB:** Postgres + PostGIS (Supabase or Neon to start). Redis (Upstash) for query caching keyed on `(geohash5, filters)`.
- **Observability:** per-adapter freshness dashboards + alerting when a scrape yields >X% diff or fails N times (scrapers rot silently; this is the #1 operational risk).

### 4.1 Core data model (sketch)

```sql
chains(id, name, dietary_default, app_url, ...)
outlets(id, chain_id, geog GEOGRAPHY(Point), address, source_ids jsonb,
        halal_status enum, halal_evidence_tier, halal_source_url, fhrs_rating)
menu_items(id, chain_id, name, category, is_vegetarian, is_vegan, active)
nutrition_records(item_id, kcal, protein_g, carbs_g, fat_g, salt_g,
                  serving_desc, source, source_url, fetched_at)
prices(item_id, outlet_id, price_pence, price_basis enum('collection','delivery','community'),
       fetched_at)
discount_rules(id, chain_id, scope, item_matcher, type, value_pct, value_pence,
               conditions jsonb, valid_to, source_url, last_verified_at)
-- Supermarket side
retailers(id, name)
meal_deals(id, retailer_id, price_pence, clubcard_required, tiers jsonb)
deal_products(deal_id, product_id, slot enum('main','snack','drink'))
products(id, retailer_id, name, barcode, kcal, protein_g, ..., off_source_url)
```

---

## 5. Scoring engine

Pure function, unit-tested to death, versioned (`score_version` in every response so results are reproducible):

```
eligible(item, user)   = passes dietary filters (evidence tier ≥ user's strictness)
                         ∧ protein_kcal_share(item) ≥ user.min_protein_share  (default 0.35)
final_price(item,o,u)  = price(item, o) − best_discount(item, o, u.eligibility)
score(item, o, u)      = protein_g(item) / final_price(item, o, u)
```

Edge handling: missing protein → excluded from ranking (never guess); missing price at the user's nearest outlet → fall back to chain-median price, badge as "estimated"; free items (100% first-order discounts) → capped display, sorted by protein.

## 6. Meal-deal optimiser

The search space is tiny — enumerate, don't optimise cleverly. Tesco: ~400 mains × ~500 snacks × ~500 drinks ≈ 10⁸ raw combos, but after the protein-density pre-filter on each slot (drop the 90% of snacks/drinks with negligible protein, keep water/zero drinks as the "protein-neutral" choice) it's thousands of combos: brute-force per request in milliseconds, or precompute **top-50 bundles per retailer per dietary profile** nightly and just re-rank. Bundle score = `Σ protein / deal_price`; also surface the "max kcal" bundle. Availability caveat: eligible lists vary by store size — badge as "subject to availability" (per-store meal-deal stock is not obtainable in v1).

## 7. Phased roadmap

**Phase 0 — Prove the metric by hand (1–2 weeks).** Hand-build the dataset for **3 chains near one postcode** (suggest: GDK, KFC, McDonald's) in a spreadsheet/SQL dump; validate the MacroScore ranking passes the sniff test ("would I actually buy #1?"). This de-risks everything downstream and produces marketing content ("cheapest 50g of protein in Manchester") for free.

**Phase 1 — MVP web app (4–6 weeks).** 5–8 chain adapters (nutrition + store locator + collection prices where the endpoint is friendly), halal registry ingestion (HMC + KFC/Nando's lists + chain-wide flags), veg/vegan flags, geolocation + postcode search, ranked list + map, protein-share slider. Curated discount table for the top ~20 offers (student platforms + first-order app deals) with an eligibility questionnaire. No accounts needed — eligibility lives in localStorage.

**Phase 2 — Supermarket meal deals (3–4 weeks).** Tesco + Sainsbury's + Boots eligible-product scrapers, Open Food Facts nutrition join (barcode match), bundle optimiser, "Meal deals" tab. This is high-value-per-effort: fixed prices kill the hardest data problem.

**Phase 3 — Discount & freshness engine.** Voucher-aggregator feed + review queue, loyalty modelling, community price confirmation ("is this still £X?" one-tap), accounts + saved profiles, price-drop alerts.

**Phase 4 — The long tail.** Photo/OCR menu ingestion for independents (VLM extraction → macro *estimation* clearly labelled as estimates → community verification), more cities/countries, native iOS app (now Core Location + MapKit natively).

## 8. Top risks

| Risk | Mitigation |
|---|---|
| Scraper rot (sites change) | Adapter interface + raw-snapshot audit trail + freshness alerting; budget ~30% of ongoing eng time for adapter maintenance |
| Wrong halal/allergen data | Evidence tiers, outlet-level (not chain-level) halal, provenance shown in UI, "verify in store" copy, fast correction path |
| Per-outlet price coverage gaps | Chain-median fallback with "estimated" badge; community confirmation in Phase 3; meal deals (fixed price) carry the product early |
| Legal pushback on scraping | Scrape legally-mandated brand data first, factual data only, polite rates, per-source kill switch, curate rather than scrape auth-walled sources |
| Discount staleness | `last_verified_at` on every rule, weekly verification job, auto-hide rules unverified > 30 days |

---

*Next step after this plan: Phase 0 — pick the postcode and the first three chains, and build the hand-rolled dataset that proves the ranking.*
