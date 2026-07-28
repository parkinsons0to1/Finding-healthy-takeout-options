"""Curated chain-wide halal policy statements.

Some chains make a statement that legitimately covers every branch ("we have no
plans to offer halal food in the UK" — McDonald's), and some make one that
covers most but explicitly not all ("no chain-wide certification, but a handful
of certified branches exist" — Burger King). Only the former can settle a
specific outlet's status on its own.

That is what `exhaustive` encodes. A non-exhaustive chain policy is a *prior*,
not a verdict: it yields UNVERIFIED for a specific outlet so that a per-outlet
source has to do the real work. Getting this wrong in either direction is how
you tell a Muslim customer the wrong thing.

Entries are curated by hand from brand statements, each with the source and the
date it was last checked. `last_verified` matters: halal status changes (KFC
Mitcham dropped it in Feb 2025), so stale entries should be re-checked rather
than trusted indefinitely.
"""
from __future__ import annotations

from ..evidence import Evidence, Status, Tier, now_iso, unverified

SOURCE = "chain halal policy (curated)"

#: chain_id -> policy. `exhaustive` = does this statement settle every branch?
POLICIES: dict[str, dict] = {
    "gdk": dict(
        status=Status.HALAL, exhaustive=True,
        detail="German Doner Kebab states all its meat is halal, chain-wide",
        url="https://www.gdk.com/", last_verified="2026-07-28"),
    "popeyes": dict(
        status=Status.HALAL, exhaustive=True,
        detail="Popeyes UK states its chicken is halal-sourced across all UK "
               "branches (supplier-level). NOT independently HMC/HFA certified "
               "except the Stratford branch; most branches share fryers with "
               "non-halal items (e.g. pork bacon) — strict-standard customers "
               "should still verify in store",
        url="https://popeyesuk.com/", last_verified="2026-07-28"),
    "mcdonalds": dict(
        status=Status.NOT_HALAL, exhaustive=True,
        detail="McDonald's UK public statement: ran a halal trial and declined "
               "to roll it out — 'no plans to offer Halal food in the UK'. No "
               "HMC/HFA/MCB certification anywhere in the UK estate",
        url="https://www.mcdonalds.com/gb/en-gb.html", last_verified="2026-07-28"),
    "greggs": dict(
        status=Status.NOT_HALAL, exhaustive=True,
        detail="Greggs official FAQ: no UK branch is halal-certified; meat from "
               "non-halal suppliers; a 2013 trial was never revived",
        url="https://www.greggs.com/", last_verified="2026-07-28"),
    "taco_bell": dict(
        status=Status.NOT_HALAL, exhaustive=True,
        detail="Taco Bell UK: no halal-certified UK locations or supply chain",
        url="https://www.tacobell.co.uk/", last_verified="2026-07-28"),
    "pret": dict(
        status=Status.NOT_HALAL, exhaustive=True,
        detail="Pret A Manger: meat incl. chicken is not halal-slaughtered; no "
               "certification from a recognised body",
        url="https://www.pret.co.uk/", last_verified="2026-07-28"),
    "burger_king": dict(
        status=Status.NOT_HALAL, exhaustive=False,
        detail="Burger King UK has no chain-wide halal certification, but a "
               "small number of individually-certified branches exist "
               "(Birmingham, Bradford, Manchester, parts of London). A specific "
               "branch therefore needs its own check",
        url="https://www.burgerking.co.uk/", last_verified="2026-07-28"),
    "nandos": dict(
        status=Status.NOT_HALAL, exhaustive=False,
        detail="Nando's operates a specific list of halal restaurants; branches "
               "not on that list are not halal. Per-branch check required",
        url="https://www.nandos.co.uk/", last_verified="2026-07-28"),
    "subway": dict(
        status=Status.UNVERIFIED, exhaustive=False,
        detail="Subway UK halal status is per-store; the chain publishes "
               "separate HALAL nutrition builds, so some franchises are "
               "certified. Ask in store",
        url="https://www.subway.com/en-gb", last_verified="2026-07-28"),
}

can_prove_negative = True   # ...but only for chains whose policy is exhaustive


def check_chain(chain_id: str) -> Evidence:
    pol = POLICIES.get(chain_id)
    if not pol:
        return unverified(SOURCE, "", f"no curated policy for chain '{chain_id}'")

    if pol["status"] is Status.UNVERIFIED:
        return unverified(SOURCE, pol["url"], pol["detail"])

    if not pol["exhaustive"]:
        # A prior, not a verdict — must not settle an individual outlet.
        return unverified(
            SOURCE, pol["url"],
            f"chain policy is non-exhaustive, per-outlet check required. "
            f"Policy: {pol['detail']}")

    return Evidence(pol["status"], Tier.BRAND_CHAIN_WIDE, SOURCE, pol["url"],
                    pol["detail"], now_iso(),
                    marker=f"chain-wide policy, last verified {pol['last_verified']}")
