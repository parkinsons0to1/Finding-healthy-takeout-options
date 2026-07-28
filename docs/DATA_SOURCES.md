# MacroMeter data source registry

Endpoint discovery log for chain nutrition/menu/store data. Every adapter in
`scripts/scrapers/` cites its entry here. Status as of **2026-07-28**.
No browser automation anywhere — plain HTTP only.

## Working sources (adapter implemented)

| Chain | Source of truth | Access | Adapter |
|---|---|---|---|
| **McDonald's** | `https://www.mcdonalds.com/dnaapp/itemDetails?country=UK&language=en&showLiveData=true&item={id}` — full nutrient facts JSON per item. Item IDs harvested from `data-product-id` attributes on the `/gb/en-gb/menu/*.html` category pages (server-rendered). | Open, no auth | `mcdonalds.py` |
| **Popeyes UK** | Ordering API found in the popeyesuk.com Angular bundle: `https://pe-uk-ordering-api-fd-eecsdkg6btfeg0cc.z01.azurefd.net`. Nutrition: `GET /en/ordering/menu/allergensandnutritions` (per-100g **and** per-serving macros, allergens, veg/vegan flags). Stores: `GET /api/v2/restaurants` (all UK, with coordinates — Sutton store id `4a5149ea-fdc9-47a5-848d-faf7ed027cf2`). | Open, no auth | `popeyes.py` |
| **Greggs** | `https://production-digital.greggs.co.uk/api/v1.0/articles/masters` — ~4,900 articles with full `nutritionalValues`, ingredients, and Greggs' own `isSourceOfProtein`/`isTaggedForProtein` tags. Shops: `/api/v1.0/shops`. | Open, no auth | `greggs.py` |
| **KFC UK** | `https://brand-uk.assets.kfc.co.uk/nutrition-allergens.pdf` — official Allergen & Nutrition guide (June 2026 V2), stable URL, parses cleanly with pdfplumber. | Open | `kfc.py` |
| **Subway UK/ROI** | Current PDF link scraped from `https://www.subway.com/en-gb/menunutrition/nutrition` (filename rotates; June 2026: `/en-gb/media/emea/europe/uk/nutrition/2026/UKI_IngredientsNutritionalInformationJune2026.pdf`). Includes **separate HALAL build rows** — Subway maintains halal-specific nutrition. | Open | `subway.py` |

## Known data-quality issues

- **Popeyes per-serving kcal** on some multi-piece items is wrong at source
  (e.g. "3 Classic Tenders & a dip" listed at 233 kcal when 1 tender = 156 kcal;
  protein alone would be 142 kcal). Adapter flags `implausible-kcal`
  (heuristic, catches the worst cases); for tender multi-packs prefer
  **per-piece × n** derivation. Per-piece tenders: Classic 156 kcal/12 g P,
  Spicy 151 kcal/13 g P.
- **Subway PDF** mixes purchasable items with ingredient-only "build" rows
  (fillings, breads, sauces). Category context is kept in `item_id`; whole-sub
  rows live in the Subs section.
- **Greggs catalog** contains internal rows ("Do Not Use …", premixes);
  adapter filters `isPublished`/`isHiddenInMenu` and the "Do Not Use" prefix.

## Blocked / future sources

| Chain | Findings | Next step |
|---|---|---|
| **Burger King UK** | RBI platform (same stack as US Whopper app). GraphQL at `https://euc1-prod-bk.rbictg.com/graphql` returns 401 without the app's client headers; menu content lives in RBI's Sanity CMS. No official UK nutrition PDF found. | Reproduce the app's public client headers (Phase 1, app-API tier) |
| **Nando's UK** | Site is a Gatsby JS shell (no data in HTML, no page-data.json at the obvious path). `api.nandos.co.uk` exists (returns 503 to blind requests, not 404) — endpoint discovery needed. No official PDF found in search. | Inspect the nutrition tool's XHR calls from a real browser session once (one-off manual capture, then plain HTTP) |
| **German Doner Kebab** | `gdk.com` is behind Cloudflare (403 to non-browser clients). No official nutrition PDF found on their domain; venue partners host GDK menu PDFs with macros (e.g. The O2's asset PDF listing a "Doner Gym Box"). GDK is halal chain-wide (brand-stated). | Try Cloudflare-tolerant fetch of their allergen page; ingest venue PDF as interim medium-confidence source |
| **Taco Bell UK** | `/nutrition` redirects to home; API not yet located. | Bundle inspection pass like Popeyes |
| **Popeyes allergen platform** | `allergensandnutritions.popeyesuk.com` frontend is public but its Strapi backend (`app-allergenplatform-prod-westeurope-001.azurewebsites.net/api`) returns 401/403 without a staff JWT — **do not attempt to bypass**; the public ordering API above carries the same data anyway. | None needed |
| **Morley's & independents** | No published nutrition (under the 250-employee calorie-labelling threshold). | Phase 4 photo/OCR |

## Halal verification log (Sutton, 2026-07-28)

| Outlet | Status | Evidence |
|---|---|---|
| GDK Sutton | **Halal** | Brand-stated chain-wide |
| KFC Sutton (200-202 High St) | **Not halal** | KFC's own halal page (kfc.co.uk/halal): ~200 of ~1,000 branches serve HFA-approved halal; Sutton not among them. Nearest halal: **KFC Morden (London Road)** and **KFC Colliers Wood**. (KFC Mitcham dropped halal 2025-02-10.) |
| Nando's Sutton | **Not halal** | User-confirmed locally; Nando's publishes an official halal restaurant list — Sutton not on it |
| Subway Sutton | Unverified (per-store) | Some UK stores are halal; Subway publishes halal-specific nutrition builds. Ask in store |
| Kokoro Sutton | Unverified | Historic claims of halal chicken chain-wide; no current certification found. Ask in store |
| Morley's Sutton | Unverified (per-store) | Most Morley's are halal, some are not; per-store |
| McDonald's / Burger King / Popeyes / Taco Bell / Greggs / Pret | Not halal | Brand statements |

## Store locators / geo

- postcodes.io — postcode → lat/lng (open)
- FSA FHRS API (`api.ratings.food.gov.uk`, header `x-api-version: 2`) — all food businesses near a point + hygiene ratings (open)
- Popeyes `/api/v2/restaurants`, Greggs `/api/v1.0/shops` — chain store locators (open)
