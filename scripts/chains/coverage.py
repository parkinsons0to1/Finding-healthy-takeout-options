#!/usr/bin/env python3
"""How much of the recognised chain estate we can actually rank.

Three different things get confused when talking about "coverage", so this
reports them separately:

  recognised  — the app identifies the brand, so it appears in "chains nearby"
  ingested    — we hold nutrition for it, so its items can be scored
  priced      — we hold prices, so it can actually enter the ranking

A chain can be recognised but not ingested (Domino's), or ingested but not
priced — and only the intersection reaches the user as a result. Reporting a
single number would flatter the system.

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


def main() -> int:
    recognised, seen = [], set()
    for _pattern, chain_id in CHAIN_PATTERNS:
        if chain_id not in seen:
            seen.add(chain_id)
            recognised.append(chain_id)

    food = [c for c in recognised if c not in SUPERMARKET_CHAINS]
    retail = [c for c in recognised if c in SUPERMARKET_CHAINS]
    have = ingested()
    priced = set(ESTIMATED_PRICES)

    ranked = sorted(set(food) & set(have) & priced)
    ingested_unpriced = sorted((set(food) & set(have)) - priced)
    missing = sorted(set(food) - set(have))

    print(f"recognised food chains : {len(food)}")
    print(f"retail/convenience     : {len(retail)}  (Open Food Facts pipeline, "
          f"not menu adapters)\n")

    print(f"RANKABLE (nutrition + price): {len(ranked)}")
    for c in ranked:
        print(f"   {c:16s} {have[c]:5d} items")

    if ingested_unpriced:
        print(f"\nINGESTED, NO PRICES YET: {len(ingested_unpriced)}")
        for c in ingested_unpriced:
            print(f"   {c:16s} {have[c]:5d} items")

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

    print(f"\ntotal ingested menu items: {sum(have.get(c, 0) for c in food)}")
    print("note: every price is still an estimate — see REMEDIATION_PLAN.md E3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
