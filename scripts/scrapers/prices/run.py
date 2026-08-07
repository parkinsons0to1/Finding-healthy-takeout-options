#!/usr/bin/env python3
"""Fetch real collection prices from chain ordering APIs and cache them.

Until now every price in MacroMeter was a hand-typed estimate, which is the
biggest remaining source of wrong rankings: price moves an item further up or
down the board than a wrong macro does. These adapters reproduce each chain's
*anonymous* ordering handshake (guest session / public service token — no
account, no basket, no order) and read the priced menu a real customer would
see for a specific store.

    python3 -m scripts.scrapers.prices.run                 # all chains
    python3 -m scripts.scrapers.prices.run --chains nandos

Output goes to ``data/db/prices_{chain}.json`` and is consumed by
``scripts/api/prices.py``, which prefers it over the estimate table.

**Prices are per store.** A cached table records which store it came from, and
that store's name travels with every quote so the UI can say so. A price from
one branch is a far better estimate for another branch than a number typed
from memory, but it is still that branch's price — the honest framing is
"collection price at <store>", never "the price".
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback

from ..base import now_iso
from . import ADAPTERS

DB = pathlib.Path(__file__).resolve().parents[3] / "data" / "db"


def cache_path(chain_id: str) -> pathlib.Path:
    return DB / f"prices_{chain_id}.json"


def save(chain_id: str, rows: list[dict]) -> pathlib.Path:
    DB.mkdir(parents=True, exist_ok=True)
    stores = sorted({r.get("store") for r in rows if r.get("store")})
    bases = sorted({r.get("basis") for r in rows if r.get("basis")})
    payload = {
        "chain_id": chain_id,
        "fetched_at": now_iso(),
        "store": stores[0] if stores else None,
        "stores": stores,
        "basis": bases[0] if len(bases) == 1 else (bases or [None])[0],
        "item_count": len(rows),
        "prices": {r["name"].strip().lower(): {
            "price_gbp": r["price_gbp"], "basis": r.get("basis", "collection"),
            "store": r.get("store"), "name": r["name"]}
            for r in rows if r.get("name") and r.get("price_gbp") is not None},
    }
    path = cache_path(chain_id)
    path.write_text(json.dumps(payload, indent=1))
    return path


def load(chain_id: str) -> dict | None:
    path = cache_path(chain_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", default=",".join(sorted(ADAPTERS)),
                    help="comma-separated subset of: " + ", ".join(sorted(ADAPTERS)))
    args = ap.parse_args()

    failures = 0
    for chain_id in [c.strip() for c in args.chains.split(",") if c.strip()]:
        module = ADAPTERS.get(chain_id)
        if module is None:
            print(f"unknown price adapter: {chain_id}")
            failures += 1
            continue
        print(f"== {chain_id}")
        try:
            rows = module.fetch_prices()
            if not rows:
                print("   no prices returned")
                failures += 1
                continue
            path = save(chain_id, rows)
            store = rows[0].get("store")
            basis = rows[0].get("basis")
            print(f"   {len(rows)} prices ({basis}, {store}) -> {path.name}")
        except Exception:
            failures += 1
            print(f"   FAILED:\n{traceback.format_exc()}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
