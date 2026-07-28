#!/usr/bin/env python3
"""Run MacroMeter chain scrapers and store results (Firestore or local JSON).

Usage:
    python3 -m scripts.scrapers.run_all                  # all chains
    python3 -m scripts.scrapers.run_all --chains kfc,greggs
    FIREBASE_CREDENTIALS=key.json python3 -m scripts.scrapers.run_all

Without Firebase credentials, output lands in data/db/{chain}.json — the
same normalized schema either way, so the app layer reads one shape.
"""
from __future__ import annotations

import argparse
import sys
import traceback

from . import greggs, kfc, mcdonalds, popeyes, subway
from .base import protein_share
from .store import get_sink

ADAPTERS = {
    "mcdonalds": mcdonalds,
    "popeyes": popeyes,
    "greggs": greggs,
    "kfc": kfc,
    "subway": subway,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", default=",".join(ADAPTERS),
                    help="comma-separated subset of: " + ", ".join(ADAPTERS))
    args = ap.parse_args()

    sink = get_sink()
    print(f"sink: {sink.name}")
    failures = 0
    for chain in [c.strip() for c in args.chains.split(",") if c.strip()]:
        mod = ADAPTERS.get(chain)
        if not mod:
            print(f"unknown chain: {chain}")
            failures += 1
            continue
        print(f"== {chain}")
        try:
            items = mod.fetch()
            passing = sum(1 for i in items if (protein_share(i) or 0) >= 0.35)
            dest = sink.upsert_items(chain, items)
            print(f"   {len(items)} items ({passing} at >=35% protein-kcal) -> {dest}")
        except Exception:
            failures += 1
            print(f"   FAILED:\n{traceback.format_exc()}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
