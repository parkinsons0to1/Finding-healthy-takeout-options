"""Find chains our regex list doesn't know about.

`geo.location.CHAIN_PATTERNS` is a hand-maintained list, and a hand-maintained
list of a moving target is always behind. Worse, the failure is silent: an
unrecognised chain is classified as an independent, so it drops out of results
*and* out of the "chains nearby" count. That is how a Papa John's inside a
holiday park came to be reported as an independent.

This module turns that silent miss into something visible. The insight is that
being a chain is an observable property of the data, not a fact we need a list
for: **a business name that appears in many separate postcode districts is a
chain**, whatever our patterns say. So sample the national FHRS register across
the country, normalise and count names by distinct district, and report frequent
names we don't recognise.

Run it periodically and work the output as a review queue:

    python3 -m scripts.chains.detect --min-districts 8
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

from ..geo.location import FHRS_API, FHRS_HEADERS, FHRS_TYPES, identify_chain
from ..scrapers.base import now_iso, session

DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "db"

#: A geographic spread of UK postcodes. Sampling widely matters: a name that
#: is common in one city may be a local mini-chain, while a genuine national
#: chain shows up everywhere.
SAMPLE_POSTCODES = [
    "SM1 4FR",   # Sutton (London)
    "M1 1AE",    # Manchester
    "B4 7DA",    # Birmingham
    "LS1 5AD",   # Leeds
    "G1 1XW",    # Glasgow
    "EH1 1YZ",   # Edinburgh
    "CF10 1EP",  # Cardiff
    "BT1 5GS",   # Belfast
    "NE1 4XF",   # Newcastle
    "BS1 4DJ",   # Bristol
    "L1 8JQ",    # Liverpool
    "NG1 5DT",   # Nottingham
    "TR27 5AF",  # Hayle (rural Cornwall)
    "IV2 3PP",   # Inverness (rural Scotland)
]

#: Strip branch qualifiers so "Greggs - Sutton" and "Greggs Plc" collapse.
_NOISE = re.compile(
    r"\b(ltd|limited|plc|uk|gb|the|store|stores|shop|restaurant|takeaway|"
    r"express|drive ?thru|kiosk|unit \d+|no\.? ?\d+|\d+)\b", re.I)
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalise(name: str) -> str:
    text = _PUNCT.sub(" ", name.lower())
    text = _NOISE.sub(" ", text)
    return " ".join(text.split())


def _district(postcode: str | None) -> str | None:
    if not postcode:
        return None
    return postcode.strip().upper().split(" ")[0] or None


def sample(postcodes: list[str], radius_miles: float = 3.0, s=None) -> list[dict]:
    """Raw establishments around each sample point."""
    from ..geo.location import geocode_postcode
    s = s or session()
    rows: list[dict] = []
    for pc in postcodes:
        loc = geocode_postcode(pc, s)
        if not loc:
            continue
        for type_name in ("takeaway", "restaurant_cafe", "retailer_other"):
            try:
                r = s.get(FHRS_API, headers=FHRS_HEADERS, params={
                    "latitude": loc["lat"], "longitude": loc["lng"],
                    "maxDistanceLimit": radius_miles, "pageSize": 250,
                    "businessTypeId": FHRS_TYPES[type_name]}, timeout=40)
                r.raise_for_status()
                rows.extend(r.json().get("establishments", []))
            except Exception:
                continue
    return rows


def find_unknown_chains(min_districts: int = 6, s=None) -> list[dict]:
    """Names appearing in >= min_districts distinct postcode districts that
    `identify_chain` does not recognise."""
    rows = sample(SAMPLE_POSTCODES, s=s)
    by_name: dict[str, set[str]] = collections.defaultdict(set)
    examples: dict[str, str] = {}

    for e in rows:
        raw = (e.get("BusinessName") or "").strip()
        if len(raw) < 3:
            continue
        key = normalise(raw)
        if not key:
            continue
        district = _district(e.get("PostCode"))
        if district:
            by_name[key].add(district)
        examples.setdefault(key, raw)

    unknown = []
    for key, districts in by_name.items():
        if len(districts) < min_districts:
            continue
        if identify_chain(examples[key]):
            continue        # already recognised — nothing to report
        unknown.append({"normalised": key, "example_name": examples[key],
                        "district_count": len(districts),
                        "districts": sorted(districts)[:12]})
    unknown.sort(key=lambda u: u["district_count"], reverse=True)
    return unknown


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-districts", type=int, default=6,
                    help="how many distinct districts before a name counts as a chain")
    ap.add_argument("--out", help="write JSON here (default data/db/unknown_chains.json)")
    args = ap.parse_args()

    unknown = find_unknown_chains(args.min_districts)
    if not unknown:
        print("no unrecognised chains above the threshold — pattern list looks current")
        return 0

    print(f"{len(unknown)} unrecognised name(s) appearing in "
          f">={args.min_districts} districts:\n")
    for u in unknown[:40]:
        print(f"  {u['example_name'][:40]:40s} {u['district_count']:3d} districts  "
              f"({', '.join(u['districts'][:6])})")

    path = pathlib.Path(args.out) if args.out else DB / "unknown_chains.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"generated_at": now_iso(), "min_districts": args.min_districts,
         "unknown": unknown}, indent=1))
    print(f"\n-> {path}")
    print("Add the real chains to geo.location.CHAIN_PATTERNS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
