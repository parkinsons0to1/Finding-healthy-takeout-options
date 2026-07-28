#!/usr/bin/env python3
"""Meal deal ingestion and optimisation.

    # cache eligible-product candidates for retailers
    python3 -m scripts.mealdeals.cli fetch --retailers tesco,sainsburys,boots

    # best bundles, optionally filtered
    python3 -m scripts.mealdeals.cli best --retailer tesco --min-protein-share 0.3
    python3 -m scripts.mealdeals.cli best --all --diet vegetarian
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from ..scrapers.base import session
from ..scrapers.store import get_sink
from .deals import DEALS, deal_for
from .optimiser import optimise, optimise_all
from .products import fetch_all

DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "db"


def _cache_path(retailer_id: str) -> pathlib.Path:
    return DB / f"mealdeal_products_{retailer_id}.json"


def load_products(retailer_id: str) -> dict | None:
    p = _cache_path(retailer_id)
    return json.loads(p.read_text()) if p.exists() else None


def cmd_fetch(args) -> int:
    s = session()
    sink = get_sink() if args.push else None
    for retailer_id in [r.strip() for r in args.retailers.split(",") if r.strip()]:
        products = fetch_all(retailer_id, s)
        DB.mkdir(parents=True, exist_ok=True)
        _cache_path(retailer_id).write_text(json.dumps(products, indent=1))
        counts = ", ".join(f"{slot}={len(v)}" for slot, v in products.items())
        print(f"{retailer_id}: {counts} -> {_cache_path(retailer_id).name}")
        if sink:
            flat = [p for v in products.values() for p in v]
            print("  ", sink.upsert_items(f"mealdeal_{retailer_id}", flat))
    return 0


def cmd_best(args) -> int:
    diet = {d.strip() for d in args.diet.split(",") if d.strip()} if args.diet else set()
    kwargs = dict(diet=diet, min_protein_share=args.min_protein_share,
                  loyalty=not args.no_loyalty)

    if args.all:
        by_retailer = {}
        for deal in DEALS:
            products = load_products(deal.retailer_id)
            if products:
                by_retailer[deal.retailer_id] = products
        if not by_retailer:
            print("no cached products — run 'fetch' first", file=sys.stderr)
            return 1
        bundles = optimise_all(DEALS, by_retailer, **kwargs)
    else:
        deal = deal_for(args.retailer)
        products = load_products(args.retailer)
        if not deal or not products:
            print(f"no deal/products for '{args.retailer}' — run 'fetch' first",
                  file=sys.stderr)
            return 1
        bundles = optimise(deal, products, limit=args.limit, **kwargs)

    if not bundles:
        print("no bundle satisfied those filters")
        return 0
    for i, b in enumerate(bundles, 1):
        print(f"{i}. {b.deal.retailer_name} £{b.price_gbp:.2f} — "
              f"{b.protein_g}g protein, {b.kcal:.0f} kcal, "
              f"{b.protein_share*100:.0f}% protein-kcal, "
              f"**{b.protein_per_pound}g/£**")
        for slot, item in b.items.items():
            print(f"     {slot:6s} {item['name'][:46]:46s} {item['protein_g']:5.1f}g P")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch")
    f.add_argument("--retailers", default="tesco")
    f.add_argument("--push", action="store_true", help="also write to the sink")
    f.set_defaults(fn=cmd_fetch)

    b = sub.add_parser("best")
    b.add_argument("--retailer", default="tesco")
    b.add_argument("--all", action="store_true", help="best from every retailer")
    b.add_argument("--diet", help="comma list: halal,vegetarian,vegan,kosher")
    b.add_argument("--min-protein-share", type=float, default=0.0)
    b.add_argument("--no-loyalty", action="store_true",
                   help="ignore Clubcard/Nectar pricing")
    b.add_argument("--limit", type=int, default=5)
    b.set_defaults(fn=cmd_best)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
