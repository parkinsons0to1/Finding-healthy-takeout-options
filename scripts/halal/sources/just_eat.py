"""Just Eat — platform halal tagging (corroboration tier).

`https://uk.api.just-eat.io/restaurants/bypostcode/{postcode}` is open (no auth)
and returns every restaurant serving a postcode, each with a `cuisines` list
that includes "Halal" where the merchant has claimed it.

**Tier 4, and it can never prove a negative.** The halal tag is merchant-entered
and unaudited: a genuinely halal outlet may simply not have ticked the box, and
the tag can be stale. So a missing tag means nothing, and even a present tag is
weaker than the chain's own store page.

Its real value is *corroboration*: an independent signal that agrees or
disagrees with our tier-1 brand sources. On 2026-07-28 for SM1 4FR it agreed
with the brand data on every outlet we had resolved — KFC Sutton halal, KFC Rose
Hill not, Popeyes halal, GDK halal — which is meaningful precisely because it
was derived independently. Where it *disagrees* with a tier-1 source, the
resolver's same-tier conflict rule doesn't fire (different tiers), but the
disagreement is worth surfacing to a reviewer.
"""
from __future__ import annotations

import re

from ..evidence import Evidence, Status, Tier, now_iso, sha256, unverified

SOURCE = "Just Eat platform listing"
API = "https://uk.api.just-eat.io/restaurants/bypostcode/{postcode}"

can_prove_negative = False


def fetch_restaurants(session, postcode: str) -> tuple[list[dict], str | None]:
    url = API.format(postcode=postcode.replace(" ", "").upper())
    try:
        # 8s, not the 40s this used to be — see hmc_registry.py's identical
        # note; this runs live per search, often for dozens of outlets.
        r = session.get(url, headers={"Accept": "application/json"}, timeout=8)
        r.raise_for_status()
    except Exception:
        return [], None
    data = r.json()
    return data.get("restaurants", []), sha256(r.text)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def check_outlet(session, outlet_name: str, postcode: str,
                 address_hint: str = "") -> Evidence:
    url = API.format(postcode=postcode.replace(" ", "").upper())
    restaurants, snap = fetch_restaurants(session, postcode)
    if not restaurants:
        return unverified(SOURCE, url, "no Just Eat results (or fetch failed)")

    target = _norm(outlet_name)
    hint = _norm(address_hint)
    best = None
    for r in restaurants:
        name = _norm(r.get("name", ""))
        if not name or not target:
            continue
        first_word = target.split()[0]
        if first_word and first_word in name:
            addr = r.get("address", {}) or {}
            line = _norm(f"{addr.get('firstLine','')} {addr.get('postalCode','')}")
            score = 2 if hint and any(w in line for w in hint.split() if len(w) > 3) else 1
            if best is None or score > best[0]:
                best = (score, r)

    if best is None:
        return unverified(SOURCE, url,
                          f"no Just Eat listing matched '{outlet_name}'")

    r = best[1]
    cuisines = [c.get("name") if isinstance(c, dict) else c
                for c in (r.get("cuisines") or [])]
    if any((c or "").lower() == "halal" for c in cuisines):
        return Evidence(
            Status.HALAL, Tier.PLATFORM_LISTING, SOURCE, url,
            f"'{r.get('name')}' is tagged Halal on Just Eat "
            f"(merchant-declared, unaudited)",
            now_iso(), snap, marker="Halal cuisine tag")

    return unverified(
        SOURCE, url,
        f"'{r.get('name')}' has no Halal tag on Just Eat — merchant-entered "
        f"data, absence proves nothing")
