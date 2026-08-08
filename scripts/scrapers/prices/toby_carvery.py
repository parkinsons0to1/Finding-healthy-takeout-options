"""Toby Carvery UK — REAL per-branch prices from its Just Eat storefront.

WHICH BUSINESS
    `tobycarvery.co.uk` is the sibling Mitchells & Butlers brand to
    `harvester.co.uk` — confirmed sharing infrastructure by Toby Carvery's
    `marketingBrandId=15` appearing inside Harvester's own anonymously-
    reachable outlet JSON. Guessing Toby Carvery's numeric `cborms` brand
    id from that (tried 1, 2, 3, 15 against
    `/cborms/pub/brands/{n}/outlets/{bunCode}`) all 404'd — `15` is a
    marketing id, not necessarily a `cborms` brand id, and those two
    turned out to be different id spaces; a proper sweep was not needed
    because of what's below.

    Same fix as `harvester.py`: skip the site's own (still-uncracked)
    Click & Collect widget entirely and use the Just Eat storefront every
    M&B brand checked so far turns out to carry. Just Eat's discovery API
    lists Toby Carvery branches directly by name (e.g. "Toby Carvery -
    Park Place", CR4 4HB, `isCollection: true, isDelivery: true`), and
    `_mb_just_eat.fetch_je_menu` — the exact same handshake proven on
    Miller & Carter and Harvester — works unmodified. 229 non-deal items
    at the default branch, including full carvery plates with `BasePrice`.

STORE — Toby Carvery - Park Place (CR4 4HB)
    First collection-eligible Toby Carvery found on Just Eat searching out
    from Wimbledon (SW19 1EJ).
"""
from __future__ import annotations

from ._mb_just_eat import fetch_je_menu

CHAIN = "toby_carvery"

#: Toby Carvery - Park Place — see STORE in the module docstring.
DEFAULT_STORE_SLUG = "tobycarveryparkplace-mitcham"

_NAME_PREFIXES = ("toby carvery",)


def find_stores(postcode: str) -> list[dict]:
    """Toby Carvery branches Just Eat lists for a UK postcode."""
    from ._mb_just_eat import find_stores as _find
    return _find(postcode, _NAME_PREFIXES, brand=CHAIN)


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Toby Carvery branch.

    Give a `store_id` (the Just Eat slug), or a `postcode` to use the
    nearest listed branch — check its `isCollection`/`isDelivery` flags
    via `find_stores` first, since not every branch carries either.
    """
    return fetch_je_menu(
        brand=CHAIN, default_store_slug=DEFAULT_STORE_SLUG,
        name_prefixes=_NAME_PREFIXES, display_name_fallback="Toby Carvery",
        store_id=store_id, basis=basis, postcode=postcode)


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:30]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
