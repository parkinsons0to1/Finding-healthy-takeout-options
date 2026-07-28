"""Evidence model for halal (and other dietary) status resolution.

The core of this module is the distinction that caused MacroMeter's worst data
error: **not every source is capable of proving a negative.**

A source that lists halal outlets (a certifier registry, a delivery platform's
halal category) can prove a POSITIVE — "this outlet is on the list". It cannot
prove a NEGATIVE, because absence has many innocent explanations: the outlet is
certified by a different body, the listing is stale, the search radius clipped
it, the page was paginated. KFC's halal branches are HFA-approved and therefore
absent from HMC's registry — absence there means nothing.

Only a source that is *authoritative and exhaustive for that specific outlet*
can prove a negative: the chain's own store page for that exact store, fetched
successfully, that carries a halal marker for its halal stores and omits it for
the rest (a discriminating marker, verified against known-halal and
known-non-halal controls).

Every source therefore declares `can_prove_negative`. A source that cannot
returns UNKNOWN instead of NOT_HALAL when it finds nothing, and the resolver
will never downgrade to NOT_HALAL on that basis.
"""
from __future__ import annotations

import dataclasses
import datetime
import enum
import hashlib


class Status(enum.StrEnum):
    HALAL = "halal"
    NOT_HALAL = "not_halal"
    UNVERIFIED = "unverified"


class Tier(enum.IntEnum):
    """Lower value = stronger evidence. Resolver prefers the strongest tier."""
    BRAND_PER_OUTLET = 1      # chain's own page for this exact store
    CERTIFIER_REGISTRY = 2    # HMC / HFA / KLBD listing this outlet
    BRAND_CHAIN_WIDE = 3      # chain states all branches are halal
    PLATFORM_LISTING = 4      # Uber Eats / Just Eat halal category
    COMMUNITY = 5             # user reports, directories
    NONE = 9


@dataclasses.dataclass(frozen=True)
class Evidence:
    """One source's finding about one outlet, with a checkable provenance trail."""
    status: Status
    tier: Tier
    source_name: str
    source_url: str
    detail: str
    fetched_at: str
    snapshot_sha256: str | None = None
    #: Marker text that was searched for, so a reviewer can re-check by hand.
    marker: str | None = None

    @property
    def is_actionable(self) -> bool:
        return self.status is not Status.UNVERIFIED


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def unverified(source_name: str, source_url: str, detail: str) -> Evidence:
    """The safe default. Used whenever a fetch fails, returns partial content,
    or the source simply has nothing to say about this outlet."""
    return Evidence(Status.UNVERIFIED, Tier.NONE, source_name, source_url,
                    detail, now_iso())
