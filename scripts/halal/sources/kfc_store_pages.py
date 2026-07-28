"""KFC UK — per-store halal status from the chain's own store pages.

This is the strongest source type we have: brand-published, per-outlet, and
plain HTTP (no browser). Store pages live at
``https://www.kfc.co.uk/kfc-near-me/{slug}`` and are enumerable from
``https://www.kfc.co.uk/sitemap.xml``.

**Why this source may prove a negative** (unlike a certifier registry): the
marker "100% HALAL CERTIFIED" was verified to discriminate against known
controls on 2026-07-28 —

    sutton-high-street   marker present   (halal — confirmed by the user)
    morden-london-road   marker present   (halal)
    sutton-rose-hill     marker absent    (not halal)
    mitcham-london-road  marker absent    (not halal — dropped halal 2025-02)

Because the same successfully-rendered template carries the marker for halal
stores and omits it for others, a 200-response store page without the marker is
genuine evidence of absence. Any non-200, or a page that fails the
sanity check (doesn't look like a store page at all), yields UNVERIFIED —
never NOT_HALAL.

`CONTROLS` is exercised by `verify_marker_discriminates()` and should be re-run
whenever KFC changes their template; if a control flips, the marker is no
longer trustworthy and the adapter must fail loudly rather than emit statuses.
"""
from __future__ import annotations

import re

from ..evidence import Evidence, Status, Tier, now_iso, sha256, unverified

SOURCE = "KFC UK store page"
STORE_URL = "https://www.kfc.co.uk/kfc-near-me/{slug}"
SITEMAP_URL = "https://www.kfc.co.uk/sitemap.xml"
MARKER = "100% HALAL CERTIFIED"

#: Slugs with known ground truth, used to prove the marker still discriminates.
CONTROLS = {"sutton-high-street": True, "morden-london-road": True,
            "sutton-rose-hill": False, "mitcham-london-road": False}

#: A real store page always contains this; guards against soft-404s / error
#: pages that would otherwise read as "marker absent" => false negative.
_PAGE_SANITY = re.compile(r"kfc-near-me|restaurant|opening", re.I)

can_prove_negative = True


def list_store_slugs(session) -> list[str]:
    """Every KFC UK store slug, from their sitemap."""
    xml = session.get(SITEMAP_URL, timeout=40).text
    slugs = re.findall(r"<loc>https://www\.kfc\.co\.uk/kfc-near-me/([^<]+)</loc>", xml)
    # 'lab*' entries are KFC's internal test stores, not real outlets.
    return sorted({s for s in slugs if not s.startswith("lab")})


def check_slug(session, slug: str) -> Evidence:
    url = STORE_URL.format(slug=slug)
    try:
        r = session.get(url, timeout=30)
    except Exception as e:
        return unverified(SOURCE, url, f"fetch failed: {e}")
    if r.status_code != 200:
        return unverified(SOURCE, url, f"HTTP {r.status_code} — cannot prove absence")
    html = r.text
    if not _PAGE_SANITY.search(html):
        return unverified(SOURCE, url, "page did not look like a store page")

    present = MARKER.lower() in html.lower()
    return Evidence(
        status=Status.HALAL if present else Status.NOT_HALAL,
        tier=Tier.BRAND_PER_OUTLET,
        source_name=SOURCE, source_url=url,
        detail=("store page carries the halal marker" if present else
                "store page rendered without the halal marker (marker is "
                "discriminating — see CONTROLS)"),
        fetched_at=now_iso(), snapshot_sha256=sha256(html), marker=MARKER,
    )


def verify_marker_discriminates(session) -> tuple[bool, dict[str, str]]:
    """Re-check the marker against known-halal and known-non-halal stores.

    Returns (ok, report). Callers must treat ok=False as "this adapter's
    output is untrustworthy", not as a data point.
    """
    report, ok = {}, True
    for slug, expected_halal in CONTROLS.items():
        ev = check_slug(session, slug)
        expected = Status.HALAL if expected_halal else Status.NOT_HALAL
        good = ev.status is expected
        ok &= good
        report[slug] = f"{'ok' if good else 'MISMATCH'}: expected {expected}, got {ev.status}"
    return ok, report
