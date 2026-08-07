#!/usr/bin/env python3
"""How much of the recognised chain estate we can actually rank.

Three different things get confused when talking about "coverage", so this
reports them separately:

  recognised  — the app identifies the brand, so it appears in "chains nearby"
  ingested    — we hold nutrition for it, so its items can be scored
  rankable    — those rows survive the orderability filter
  priced      — we hold prices, so it can actually enter the ranking

A chain can be recognised but not ingested (Domino's), or ingested but not
priced — and only the intersection reaches the user as a result. Reporting a
single number would flatter the system.

"Ingested" and "rankable" come apart more sharply than they look. Half of
Papa John's rows are per-slice pizzas nobody can buy; every Five Guys row is
per 100g, which is unrankable against a whole-item price however good the
nutrition is. A chain with items but nothing rankable is the failure mode most
likely to pass unnoticed, so it gets its own section rather than a zero.

    python3 -m scripts.chains.coverage
"""
from __future__ import annotations

import glob
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.api.prices import ESTIMATED_PRICES          # noqa: E402
from scripts.geo.location import CHAIN_PATTERNS, SUPERMARKET_CHAINS  # noqa: E402

DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "db"
_INTERNAL = ("store_index", "mealdeal", "halal_cache", "offers",
             "unknown_chains", "chain_discovery", "kfc_halal_registry")


def ingested() -> dict[str, int]:
    out = {}
    for path in glob.glob(str(DB / "*.json")):
        name = os.path.basename(path)[:-5]
        if name.startswith(_INTERNAL):
            continue
        try:
            out[name] = json.loads(pathlib.Path(path).read_text()).get("item_count", 0)
        except Exception:
            continue
    return out


def rankable() -> dict[str, int]:
    """Ingested rows that survive the orderability filter, per chain."""
    from scripts.api.search import _is_orderable, load_menu

    out = {}
    for chain_id in ingested():
        items = load_menu(chain_id)
        out[chain_id] = sum(1 for i in items
                            if _is_orderable({**i, "chain_id": chain_id}))
    return out


def live_priced() -> dict[str, dict]:
    """Chains with real scraped prices, and which store each came from."""
    out = {}
    for path in glob.glob(str(DB / "prices_*.json")):
        try:
            payload = json.loads(pathlib.Path(path).read_text())
        except Exception:
            continue
        chain_id = payload.get("chain_id") or os.path.basename(path)[7:-5]
        out[chain_id] = payload
    return out


def _why_unrankable(chain_id: str) -> str:
    """The commonest reason this chain's rows were rejected, stated plainly.

    For the per-100g case specifically, checks whether fixing it would even
    matter: protein *share* is scale-invariant (it cancels the /100g), so it
    can be read off the existing rows even though absolute kcal/protein can't
    be. Hotel Chocolat's highest-protein row is Iced Chocolate at 16% — well
    under the ranking floor — so getting real portion weights would spend
    engineering time to move zero items into the ranking. Better to say so
    than to leave a "needs portion weights" note that reads as a to-do with a
    payoff that doesn't exist.
    """
    from scripts.api.scoring import DEFAULT_MIN_PROTEIN_SHARE
    from scripts.api.search import _PER_100_RE, load_menu

    items = load_menu(chain_id)
    per_100 = sum(1 for i in items
                  if isinstance(i.get("serving_desc"), str)
                  and _PER_100_RE.search(i["serving_desc"]))
    if per_100 > len(items) / 2:
        shares = [i["protein_g"] * 4 / i["kcal"] for i in items
                 if i.get("kcal") and i.get("protein_g") is not None]
        best = max(shares) if shares else 0.0
        if best < DEFAULT_MIN_PROTEIN_SHARE:
            return (f"nutrition is per 100g, but even its best item is only "
                    f"{best:.0%} protein by calories (floor is "
                    f"{DEFAULT_MIN_PROTEIN_SHARE:.0%}) — real portion weights "
                    f"would not add any rankable items")
        return ("nutrition is published per 100g, which cannot be ranked "
                "against a whole-item price; needs portion weights")
    no_macros = sum(1 for i in items
                    if not i.get("kcal") or i.get("protein_g") is None)
    if no_macros > len(items) / 2:
        return "rows carry no kcal or protein"
    return "rows rejected by the orderability filter"


def main() -> int:
    recognised, seen = [], set()
    for _pattern, chain_id in CHAIN_PATTERNS:
        if chain_id not in seen:
            seen.add(chain_id)
            recognised.append(chain_id)

    food = [c for c in recognised if c not in SUPERMARKET_CHAINS]
    retail = [c for c in recognised if c in SUPERMARKET_CHAINS]
    have = ingested()
    live = live_priced()
    usable = rankable()
    priced = set(ESTIMATED_PRICES) | set(live)

    no_rankable_rows = sorted(c for c in set(food) & set(have)
                              if have[c] and not usable.get(c))
    ranked = sorted((set(food) & set(have) & priced) - set(no_rankable_rows))
    ingested_unpriced = sorted((set(food) & set(have))
                               - priced - set(no_rankable_rows))
    missing = sorted(set(food) - set(have))

    print(f"recognised food chains : {len(food)}")
    print(f"retail/convenience     : {len(retail)}  (Open Food Facts pipeline, "
          f"not menu adapters)\n")

    print(f"RANKABLE (nutrition + price): {len(ranked)}")
    for c in ranked:
        cache = live.get(c)
        where = (f"LIVE {cache.get('basis') or 'collection'} @ "
                 f"{cache.get('store')}" if cache else "estimated prices")
        print(f"   {c:16s} {usable.get(c, 0):5d}/{have[c]:<5d} rankable   {where}")

    if ingested_unpriced:
        print(f"\nINGESTED, NO PRICES YET: {len(ingested_unpriced)}")
        for c in ingested_unpriced:
            print(f"   {c:16s} {usable.get(c, 0):5d}/{have[c]:<5d} rankable")

    if no_rankable_rows:
        # Not "no data" — data we hold and cannot honestly use. Naming the
        # reason is the point: these are fixable in the adapter, and a silent
        # zero would read as "this chain publishes nothing".
        print(f"\nINGESTED BUT NOTHING RANKABLE: {len(no_rankable_rows)}")
        for c in no_rankable_rows:
            print(f"   {c:16s} {have[c]:5d} items, 0 usable — "
                  f"{_why_unrankable(c)}")

    print(f"\nRECOGNISED, NO NUTRITION: {len(missing)}")
    discovery = DB / "chain_discovery.json"
    types: dict[str, str] = {}
    if discovery.exists():
        for r in json.loads(discovery.read_text()).get("results", []):
            types[r["chain_id"]] = r["best"]["type"]
    buckets: dict[str, list[str]] = {}
    for c in missing:
        buckets.setdefault(types.get(c, "unprobed"), []).append(c)
    print("   (buckets describe what discovery found, NOT what a chain "
          "publishes — see discover.py)")
    for bucket, ids in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f"   {bucket:11s} {len(ids):3d}  {', '.join(ids[:10])}"
              f"{' …' if len(ids) > 10 else ''}")

    print(f"\ntotal ingested menu items : {sum(have.get(c, 0) for c in food)}")
    print(f"total rankable menu items: {sum(usable.get(c, 0) for c in food)}")
    if live:
        rows = sum(len(p.get('prices') or {}) for p in live.values())
        print(f"chains on LIVE prices    : {len(live)} ({rows} scraped prices) "
              f"— {', '.join(sorted(live))}")
    print("every other price is a typed estimate — see REMEDIATION_PLAN.md E3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
