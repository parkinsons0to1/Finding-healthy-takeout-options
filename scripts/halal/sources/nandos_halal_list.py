"""Nando's UK — official per-branch halal list.

Nando's publishes an explicitly exhaustive list of its halal restaurants at
https://www.nandos.co.uk/halal (107 branches as of 2026-07-28), and its full
estate at https://www.nandos.co.uk/restaurants (491 branches). Both are
server-rendered Next.js pages with the restaurant data embedded as escaped
JSON — plain HTTP, no browser.

**Why this source may prove a negative:** the halal page is not a sample or a
search result, it is the brand's complete published list of which branches are
halal. So for any branch we can confirm exists in the estate, membership of the
halal list is a genuine yes/no. A branch we cannot find in *either* list yields
UNVERIFIED (we may simply have failed to match the name).

Worked example (the case that started all this): the estate contains
`sutton-high-street`, `sutton-oldfields-road` and `sutton-coldfield`. Only
`sutton-oldfields-road` is on the halal list. So the Nando's on Sutton High
Street — the one 0.05mi from SM1 4FR — is not halal, while the Oldfields Road
branch about a mile away is. Chain-level halal flags cannot express that;
per-outlet resolution is the whole point.
"""
from __future__ import annotations

import re

from ..evidence import Evidence, Status, Tier, now_iso, sha256, unverified

SOURCE = "Nando's official halal restaurant list"
HALAL_URL = "https://www.nandos.co.uk/halal"
ESTATE_URL = "https://www.nandos.co.uk/restaurants"

can_prove_negative = True

_SLUG = re.compile(r"/restaurants/([a-z0-9-]+)")
#: Restaurant objects carry an amenities array; HALAL appears there.
_OBJ = re.compile(r'\{"amenities":\[(.*?)\],"banner":.*?"details":\{"name":"(.*?)","slug":"(.*?)"')


def _unescape(html: str) -> str:
    return html.replace('\\"', '"').replace("\\\\", "\\")


def fetch_halal_slugs(session) -> tuple[set[str], str | None]:
    """Slugs of every branch Nando's lists as halal."""
    try:
        r = session.get(HALAL_URL, timeout=40)
        r.raise_for_status()
    except Exception:
        return set(), None
    body = _unescape(r.text)
    slugs = {slug for amenities, _name, slug in _OBJ.findall(body)
             if "HALAL" in amenities}
    # Fall back to plain slug harvest if the JSON shape changes but the page
    # still only lists halal branches.
    if not slugs:
        slugs = set(_SLUG.findall(body))
    return slugs, sha256(r.text)


def fetch_estate_slugs(session) -> set[str]:
    """Slugs of every Nando's branch, halal or not."""
    try:
        r = session.get(ESTATE_URL, timeout=60)
        r.raise_for_status()
    except Exception:
        return set()
    return set(_SLUG.findall(_unescape(r.text)))


def _candidates(outlet_name: str, address: str) -> list[str]:
    """Plausible slug fragments for matching, most specific first."""
    text = f"{outlet_name} {address}".lower()
    text = re.sub(r"nando'?s", " ", text)
    words = [w for w in re.split(r"[^a-z0-9]+", text) if len(w) > 2]
    out = []
    for i in range(len(words) - 1):
        out.append(f"{words[i]}-{words[i+1]}")
    out.extend(words)
    return out


def check_outlet(session, outlet_name: str, address: str = "",
                 slug: str | None = None) -> Evidence:
    halal_slugs, snap = fetch_halal_slugs(session)
    if not halal_slugs:
        return unverified(SOURCE, HALAL_URL, "could not fetch the halal list")
    estate = fetch_estate_slugs(session)

    if slug is None:
        for cand in _candidates(outlet_name, address):
            exact = [s for s in estate if s == cand]
            if exact:
                slug = exact[0]
                break
            partial = [s for s in estate if cand in s]
            if len(partial) == 1:
                slug = partial[0]
                break
    if slug is None:
        return unverified(SOURCE, HALAL_URL,
                          f"could not identify a Nando's branch matching "
                          f"'{outlet_name}' — cannot conclude anything")

    if slug in halal_slugs:
        return Evidence(Status.HALAL, Tier.BRAND_PER_OUTLET, SOURCE, HALAL_URL,
                        f"branch '{slug}' appears on Nando's official halal list",
                        now_iso(), snap, marker="HALAL amenity")

    if slug in estate:
        return Evidence(
            Status.NOT_HALAL, Tier.BRAND_PER_OUTLET, SOURCE, HALAL_URL,
            f"branch '{slug}' is in Nando's estate ({len(estate)} branches) but "
            f"absent from their complete halal list ({len(halal_slugs)} branches)",
            now_iso(), snap, marker="absent from exhaustive HALAL list")

    return unverified(SOURCE, HALAL_URL,
                      f"branch '{slug}' not found in the estate listing")
