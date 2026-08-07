#!/usr/bin/env python3
"""Halal status resolution CLI.

    # prove the KFC store-page marker still discriminates (run before trusting output)
    python3 -m scripts.halal.cli verify

    # resolve one outlet
    python3 -m scripts.halal.cli resolve --chain kfc --name "KFC Sutton" \
        --slug sutton-high-street --lat 51.360125 --lng -0.190664

    # resolve every outlet in data/phase0/outlets.csv and write halal_status.csv
    python3 -m scripts.halal.cli batch

    # build a national KFC halal registry from their sitemap
    python3 -m scripts.halal.cli kfc-registry --limit 200
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import pathlib
import sys

from ..chains import store_index
from ..geo.location import find_outlets, resolve_location
from ..scrapers.base import session
from ..scrapers.store import get_sink
from .evidence import Status
from .resolver import resolve
from .sources import kfc_store_pages


def cmd_build_index(args) -> int:
    idx = store_index.BUILDERS[args.chain](session(), **(
        {"limit": args.limit} if args.chain == "kfc" else {}))
    path = store_index.save(idx)
    halal = sum(1 for r in idx["stores"].values() if r.get("halal"))
    print(f"{args.chain}: {idx['store_count']} stores ({halal} halal) -> {path}")
    return 0

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"

# Chain identification and branch matching are location-general: chains are
# recognised by name (geo.location.identify_chain) and the specific branch is
# matched from the outlet's coordinates against that chain's national store
# index. Nothing here is tied to a particular town.


def cmd_verify(args) -> int:
    s = session()
    ok, report = kfc_store_pages.verify_marker_discriminates(s)
    for slug, line in report.items():
        print(f"  {slug:24s} {line}")
    print(f"\nmarker discriminates: {ok}")
    if not ok:
        print("REFUSING to trust KFC store-page output until controls pass.",
              file=sys.stderr)
    return 0 if ok else 1


def cmd_resolve(args) -> int:
    s = session()
    outlet = {"name": args.name, "chain_id": args.chain, "store_slug": args.slug,
              "lat": args.lat, "lng": args.lng}
    res = resolve(s, outlet)
    print(f"\n{res.outlet_name} -> {res.status.upper()} "
          f"(tier: {res.tier.name.lower()})")
    print(f"reason: {res.reason}\n")
    print("evidence considered:")
    for e in res.evidence:
        print(f"  [{e.status:11s}] {e.source_name}: {e.detail}")
        if e.source_url:
            print(f"                {e.source_url}")
    return 0


def cmd_batch(args) -> int:
    """Resolve every chain outlet near ANY postcode the user gives."""
    s = session()
    ok, _ = kfc_store_pages.verify_marker_discriminates(s)
    if not ok:
        print("KFC marker controls FAILED — aborting batch.", file=sys.stderr)
        return 1

    loc = resolve_location(postcode=args.postcode, lat=args.lat, lng=args.lng, s=s)
    if not loc:
        print(f"could not resolve location: {args.postcode or (args.lat, args.lng)}",
              file=sys.stderr)
        return 1
    print(f"location: {loc.get('postcode') or ''} "
          f"({loc.get('district') or '?'}) {loc['lat']:.5f},{loc['lng']:.5f}")

    outlets = find_outlets(loc["lat"], loc["lng"], args.radius, s)
    chains = [o for o in outlets if o["kind"] == "chain"]
    print(f"{len(outlets)} outlets within {args.radius}mi, {len(chains)} chain outlets\n")

    rows = []
    for o in chains:
        outlet = {"name": o["business_name"], "chain_id": o["chain_id"],
                  "lat": o["lat"], "lng": o["lng"], "postcode": o["postcode"],
                  "address": o["address"]}
        res = resolve(s, outlet)
        row = res.to_row()
        row.update(address=o["address"], distance_miles=o["distance_miles"],
                   postcode=o["postcode"])
        rows.append(row)
        print(f"  {o['business_name'][:32]:32s} {o['distance_miles']:>5}mi -> "
              f"{res.status:11s} ({res.tier.name.lower()})")

    if not rows:
        print("no chain outlets to resolve here")
        return 0

    out = pathlib.Path(args.out) if args.out else (
        DATA / "halal" / f"{(loc.get('postcode') or 'location').replace(' ', '')}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {len(rows)} resolutions -> {out}")
    return 0


def cmd_kfc_registry(args) -> int:
    """Build a national per-store halal registry for KFC."""
    s = session()
    ok, _ = kfc_store_pages.verify_marker_discriminates(s)
    if not ok:
        print("KFC marker controls FAILED — aborting.", file=sys.stderr)
        return 1

    slugs = kfc_store_pages.list_store_slugs(s)
    if args.limit:
        slugs = slugs[:args.limit]
    print(f"checking {len(slugs)} KFC stores...")

    results = {}
    with cf.ThreadPoolExecutor(args.workers) as ex:
        futures = {ex.submit(kfc_store_pages.check_slug, s, sl): sl for sl in slugs}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            slug = futures[fut]
            ev = fut.result()
            results[slug] = {"slug": slug, "status": str(ev.status),
                             "source_url": ev.source_url,
                             "fetched_at": ev.fetched_at,
                             "snapshot_sha256": ev.snapshot_sha256}
            if i % 50 == 0:
                print(f"  {i}/{len(slugs)}")

    halal = [r for r in results.values() if r["status"] == Status.HALAL]
    unknown = [r for r in results.values() if r["status"] == Status.UNVERIFIED]
    out = DATA / "db" / "kfc_halal_registry.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"chain_id": "kfc", "store_count": len(results),
                               "halal_count": len(halal),
                               "stores": results}, indent=1))
    print(f"\n{len(halal)} halal / {len(results)} stores "
          f"({len(unknown)} unresolved) -> {out}")
    for r in sorted(halal, key=lambda r: r["slug"])[:25]:
        print(f"  halal: {r['slug']}")
    if args.push:
        sink = get_sink()
        print("sink:", sink.upsert_items("kfc_halal", list(results.values())))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("verify").set_defaults(fn=cmd_verify)

    r = sub.add_parser("resolve")
    r.add_argument("--chain", required=True)
    r.add_argument("--name", required=True)
    r.add_argument("--slug")
    r.add_argument("--lat", type=float)
    r.add_argument("--lng", type=float)
    r.set_defaults(fn=cmd_resolve)

    b = sub.add_parser("batch", help="resolve every chain outlet near a location")
    b.add_argument("--postcode", help="any UK postcode")
    b.add_argument("--lat", type=float, help="or coordinates from the browser")
    b.add_argument("--lng", type=float)
    b.add_argument("--radius", type=float, default=1.0, help="miles (default 1)")
    b.add_argument("--out", help="output CSV path")
    b.set_defaults(fn=cmd_batch)

    i = sub.add_parser("build-index", help="build a chain's national store index")
    i.add_argument("chain", choices=sorted(store_index.BUILDERS))
    i.add_argument("--limit", type=int, default=0)
    i.set_defaults(fn=cmd_build_index)

    k = sub.add_parser("kfc-registry")
    k.add_argument("--limit", type=int, default=0)
    k.add_argument("--workers", type=int, default=8)
    k.add_argument("--push", action="store_true")
    k.set_defaults(fn=cmd_kfc_registry)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
