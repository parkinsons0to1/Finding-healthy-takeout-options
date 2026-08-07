"""Resolve an outlet's halal status from all available sources.

Resolution rules, in order:

1. Gather evidence from every applicable source. Sources that cannot speak to
   this outlet return UNVERIFIED and are discarded.
2. If nothing actionable came back -> UNVERIFIED ("ask in store"). This is a
   perfectly good answer and must never be dressed up as NOT_HALAL.
3. Otherwise take the strongest tier available. A per-outlet brand page (tier 1)
   beats a chain-wide statement (tier 3): that is how KFC Sutton resolves to
   halal even though "KFC" has no chain-wide halal policy, and how an
   individually-certified Burger King branch could resolve to halal despite BK's
   chain-wide non-halal prior.
4. If two sources at the *same* tier disagree, do not guess: return UNVERIFIED
   with the conflict recorded, and let a human resolve it. A visible "we don't
   know" is cheaper than a confident wrong answer.

The returned Resolution carries every piece of evidence considered, so the UI
can show *why* ("KFC's own store page says 100% Halal Certified") and a
reviewer can re-check by hand.
"""
from __future__ import annotations

import dataclasses

from ..chains import store_index
from .evidence import Evidence, Status, Tier
from .sources import (chain_policy, hmc_registry, just_eat, kfc_store_pages,
                      nandos_halal_list)


@dataclasses.dataclass
class Resolution:
    outlet_name: str
    chain_id: str
    status: Status
    tier: Tier
    reason: str
    evidence: list[Evidence]
    conflict: bool = False

    def to_row(self) -> dict:
        best = next((e for e in self.evidence
                     if e.status is self.status and e.tier is self.tier), None)
        return {
            "outlet_name": self.outlet_name,
            "chain_id": self.chain_id,
            "halal_status": str(self.status),
            "evidence_tier": self.tier.name.lower(),
            "reason": self.reason,
            "source_url": best.source_url if best else "",
            "source_name": best.source_name if best else "",
            "snapshot_sha256": (best.snapshot_sha256 or "") if best else "",
            "fetched_at": best.fetched_at if best else "",
            "conflict": self.conflict,
            "sources_consulted": len(self.evidence),
        }


#: chain_id -> callable(session, outlet) -> Evidence, for per-outlet sources.
def _resolve_slug(chain_id: str, outlet: dict) -> str | None:
    """Find this chain's own branch record for wherever the outlet actually is.

    Never hardcode a slug: the user could be anywhere in the country, so the
    branch is matched from the outlet's coordinates (or postcode) against the
    chain's national store index.
    """
    if outlet.get("store_slug"):
        return outlet["store_slug"]
    lat, lng = outlet.get("lat"), outlet.get("lng")
    if lat is not None and lng is not None:
        rec = store_index.nearest_store(chain_id, float(lat), float(lng))
        if rec:
            return rec["slug"]
    if outlet.get("postcode"):
        rec = store_index.find_by_postcode(chain_id, outlet["postcode"])
        if rec:
            return rec["slug"]
    return None


PER_OUTLET_SOURCES = {
    "kfc": lambda s, o: (
        kfc_store_pages.check_slug(s, slug)
        if (slug := _resolve_slug("kfc", o)) else None),
    "nandos": lambda s, o: nandos_halal_list.check_outlet(
        s, o.get("name", ""), o.get("address", ""), _resolve_slug("nandos", o)),
}


def resolve(session, outlet: dict) -> Resolution:
    """`outlet` needs: name, chain_id; optionally store_slug, lat, lng."""
    chain_id = outlet.get("chain_id", "")
    name = outlet.get("name", "")
    evidence: list[Evidence] = []

    per_outlet = PER_OUTLET_SOURCES.get(chain_id)
    if per_outlet:
        ev = per_outlet(session, outlet)
        if ev:
            evidence.append(ev)

    if outlet.get("lat") is not None and outlet.get("lng") is not None:
        evidence.append(hmc_registry.check_outlet(
            session, name, outlet["lat"], outlet["lng"]))

    if outlet.get("postcode"):
        evidence.append(just_eat.check_outlet(
            session, name, outlet["postcode"], outlet.get("address", "")))

    evidence.append(chain_policy.check_chain(chain_id))

    actionable = [e for e in evidence if e.is_actionable]
    if not actionable:
        return Resolution(
            name, chain_id, Status.UNVERIFIED, Tier.NONE,
            "no source could establish a status — show as 'unverified, ask in "
            "store'", evidence)

    best_tier = min(e.tier for e in actionable)
    top = [e for e in actionable if e.tier is best_tier]
    statuses = {e.status for e in top}

    if len(statuses) > 1:
        return Resolution(
            name, chain_id, Status.UNVERIFIED, Tier.NONE,
            "sources at the same evidence tier disagree — needs human review: "
            + "; ".join(f"{e.source_name} says {e.status}" for e in top),
            evidence, conflict=True)

    winner = top[0]
    return Resolution(name, chain_id, winner.status, winner.tier,
                      winner.detail, evidence)
