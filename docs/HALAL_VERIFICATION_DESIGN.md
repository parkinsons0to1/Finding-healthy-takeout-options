# Halal verification: design and implementation

Answering the question directly: **not an MCP server, not a runtime web search, and no usable third-party API exists — so we build a resolver library with a CLI, fed by per-outlet scrapes of sources the brands and certifiers already publish.** Reasoning below, then the implementation, which is built and working.

## What already exists (researched 2026-07-28, not assumed)

| Candidate | Verdict |
|---|---|
| **HMC** (Halal Monitoring Committee) | No public API. But their certified-outlet directory at `halalhmc.org/outlets/` is a **plain GET form** (`lat`, `lang`[sic, longitude], `distance`, `cat`) returning server-rendered HTML. Scrapeable, no browser. ✅ used |
| **HFA** (Halal Food Authority) | Site returns 403 to non-browser clients; no accessible registry found. ❌ blocked |
| **Zabihah** (53k+ halal venues, since 1998) | Largest halal directory in the world, but **no public API** — app-only. Community-sourced, so it would be tier-4 evidence anyway. ❌ |
| **Delivery platforms** (Uber Eats/Just Eat halal categories) | Queryable in principle, but the halal flag is merchant-entered and unaudited — useful corroboration, never primary. Tier 4. |
| **Chain store pages** | **The big win.** KFC and Nando's both publish per-branch halal status in server-rendered HTML. ✅ used — see below |

**Conclusion:** there is no halal API to call. The authoritative data is per-outlet and lives on the brands' own store pages, which are scrapeable over plain HTTP. So MacroMeter builds its own resolver.

## Why a library + CLI, not an MCP server or a web search

- **Not an MCP server.** MCP exposes tools to an LLM agent at conversation time. Halal status is batch-ingested reference data that must be identical for every user and auditable after the fact — it belongs in the data pipeline next to the nutrition scrapers, not behind a conversational tool call. (If we ever want an agent to answer halal questions, it should query our resolved database, not re-derive the answer live.)
- **Not a runtime web search.** This is the important one: **a web search is exactly what produced the wrong KFC Sutton answer.** Search results are non-deterministic, unversioned, mix SEO content farms with brand statements, and can't be re-checked later. Web search is fine for *discovering* which URL holds the truth (that's how the KFC and Nando's pages were found), but must never be the thing consulted per query.
- **A library + CLI**, because the output is a table other things read: the scoring engine, the API, the web app. The CLI exists for operators — backfilling, re-verifying, and re-running controls when a chain changes its template.

## The architecture

```
scripts/halal/
├── evidence.py                    Status / Tier / Evidence — provenance model
├── resolver.py                    combines sources under the negative-evidence rule
├── cli.py                         verify | resolve | batch | kfc-registry
└── sources/
    ├── kfc_store_pages.py         per-outlet, brand      (can prove negatives)
    ├── nandos_halal_list.py       per-outlet, brand      (can prove negatives)
    ├── hmc_registry.py            certifier registry     (CANNOT prove negatives)
    └── chain_policy.py            curated chain-wide     (only if exhaustive)
```

### The core idea: `can_prove_negative`

Every source declares whether it is capable of establishing that an outlet is *not* halal. This single flag is the fix for the bug that shipped in Phase 0.

- A source that **lists halal outlets** — a certifier registry, a delivery platform category — can only prove a **positive**. Absence has innocent explanations: certified by a different body (KFC's halal branches are HFA-approved and correctly absent from HMC's registry), stale listing, search radius clipped it, pagination. `hmc_registry` therefore returns UNVERIFIED, never NOT_HALAL, and says so in its message.
- A source that is **authoritative and exhaustive for that outlet** can prove a negative: the chain's own store page, or the chain's own complete halal list.

### Evidence tiers

| Tier | Meaning | Example |
|--:|---|---|
| 1 | `BRAND_PER_OUTLET` | KFC's page for that exact store; Nando's halal list |
| 2 | `CERTIFIER_REGISTRY` | HMC listing this outlet |
| 3 | `BRAND_CHAIN_WIDE` | "all our meat is halal" (GDK, Popeyes) |
| 4 | `PLATFORM_LISTING` | Uber Eats halal category |
| 5 | `COMMUNITY` | user reports, directories |

Resolution: gather all evidence → discard UNVERIFIED → **strongest tier wins** → if two sources at the *same* tier disagree, return UNVERIFIED with the conflict recorded for human review rather than guessing. Every resolution keeps the full evidence list plus a SHA-256 of the fetched page, so the UI can show *why* and a reviewer can re-check by hand.

### Marker validation (guarding against silent template changes)

KFC's halal status is detected by the string `100% HALAL CERTIFIED` on the store page. A marker is only trustworthy if it *discriminates*, so `verify_marker_discriminates()` tests it against known controls on every run, and the batch/registry commands **refuse to emit any status if a control fails**:

```
sutton-high-street   ok: expected halal,     got halal
morden-london-road   ok: expected halal,     got halal
sutton-rose-hill     ok: expected not_halal, got not_halal
mitcham-london-road  ok: expected not_halal, got not_halal
marker discriminates: True
```

(The Mitcham control is independently meaningful: it dropped halal in Feb 2025, and the page reflects that — evidence the marker tracks reality rather than being static boilerplate.)

## Results for SM1 4FR

`python3 -m scripts.halal.cli batch` → `data/phase0/halal_status.csv`

| Outlet | Status | Tier | Basis |
|---|---|---|---|
| **KFC Sutton High St** | **halal** | brand_per_outlet | KFC's own store page carries the halal marker |
| **Nando's Sutton High St** | **not_halal** | brand_per_outlet | in Nando's 491-branch estate, absent from their complete 107-branch halal list |
| **Popeyes Sutton** | **halal** | brand_chain_wide | chain-wide supplier-level halal claim |
| **GDK Sutton** | **halal** | brand_chain_wide | chain-wide |
| McDonald's / Greggs / Pret / Taco Bell | not_halal | brand_chain_wide | exhaustive chain statements |
| Burger King, Subway | **unverified** | — | chain policy is non-exhaustive and no per-outlet source exists yet — honest "ask in store" |

### The finding that justifies the whole design

There are **two Nando's in Sutton**. The one 0.05mi from SM1 4FR (High Street) is **not halal**. The one on Oldfields Road, about a mile away, **is halal** — it's on Nando's official list. A chain-level halal flag physically cannot express that; it would have told you either that both were halal or that neither was, and both answers are wrong. This is why the model resolves per outlet.

## Roadmap for this subsystem

1. **Per-outlet sources for the remaining chains.** Burger King and Subway are the honest `unverified` gaps; both have per-store halal variation. Subway is especially worth it — they publish separate HALAL nutrition builds, so the data exists somewhere.
2. **National KFC registry.** `cli.py kfc-registry` already enumerates all ~950 KFC stores from their sitemap and resolves each; run it fully and store to Firebase so halal KFC lookup is instant nationwide.
3. **Kosher**, structurally identical: KLBD and Manchester Beth Din publish certified-establishment lists; same tiering, same `can_prove_negative` discipline.
4. **Community corroboration** (tier 5) once there's traffic — one-tap "was this right?" — never overriding a tier-1 source, only flagging conflicts for review.
5. **Staleness.** Every resolution stores `fetched_at`; halal status changes (Mitcham). Re-resolve on a rolling schedule and surface the check date in the UI.
