"""HMC (Halal Monitoring Committee) — third-party certifier registry.

Their certified-outlet directory at https://halalhmc.org/outlets/ is a plain
GET form (``q``, ``lat``, ``lang`` [sic — longitude], ``distance``, ``cat``)
returning server-rendered HTML. No API key, no browser needed.

**This source can never prove a negative.** HMC is one of several UK certifiers;
KFC's halal branches are HFA-approved and correctly absent from HMC's registry.
Reading "not in HMC's list" as "not halal" is precisely the mistake that
produced MacroMeter's wrong KFC Sutton call. Accordingly `can_prove_negative`
is False and a no-match yields UNVERIFIED.
"""
from __future__ import annotations

import html as html_mod
import re

from ..evidence import Evidence, Status, Tier, now_iso, sha256, unverified

SOURCE = "HMC certified outlet registry"
SEARCH_URL = "https://halalhmc.org/outlets/"

can_prove_negative = False

_BLOCK = re.compile(
    r'<div class="col-sm-6 single-post single-outlet-post[^"]*"[^>]*id="([\d.]+)"[^>]*>(.*?)</article>',
    re.S)


def _text(fragment: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def search(session, lat: float, lng: float, distance_miles: int = 5) -> list[dict]:
    """Certified outlets near a point. Returns [] on any fetch problem."""
    params = {"q": f"{lat},{lng}", "lat": lat, "lang": lng,
              "distance": distance_miles, "cat": 0}
    try:
        r = session.get(SEARCH_URL, params=params, timeout=40)
        r.raise_for_status()
    except Exception:
        return []
    out = []
    for dist, block in _BLOCK.findall(r.text):
        name = re.search(r"<h3>(.*?)</h3>", block, re.S)
        addr = re.search(r'class="outlet-address">(.*?)</p>', block, re.S)
        cat = re.search(r"cat-([a-z]+)\.png", block)
        if not name:
            continue
        out.append({
            "name": _text(name.group(1)),
            "address": re.sub(r"\s+", " ", _text(addr.group(1))) if addr else "",
            "category": cat.group(1) if cat else None,
            "distance_miles": float(dist),
            "snapshot_sha256": sha256(r.text),
        })
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def check_outlet(session, outlet_name: str, lat: float, lng: float,
                 distance_miles: int = 5) -> Evidence:
    """Look for a specific outlet in HMC's registry near its coordinates."""
    matches = search(session, lat, lng, distance_miles)
    if not matches:
        return unverified(SOURCE, SEARCH_URL,
                          "no HMC results for this area (or fetch failed) — "
                          "HMC cannot prove a negative")
    target = _norm(outlet_name)
    for m in matches:
        n = _norm(m["name"])
        if target and (target in n or n in target):
            return Evidence(
                Status.HALAL, Tier.CERTIFIER_REGISTRY, SOURCE, SEARCH_URL,
                f"HMC-certified: {m['name']} ({m['address']}), "
                f"{m['distance_miles']}mi from search point",
                now_iso(), m["snapshot_sha256"], marker="HMC registry entry")
    return unverified(
        SOURCE, SEARCH_URL,
        f"not among {len(matches)} HMC-certified outlets within "
        f"{distance_miles}mi — NOT evidence of non-halal (other certifiers exist)")
