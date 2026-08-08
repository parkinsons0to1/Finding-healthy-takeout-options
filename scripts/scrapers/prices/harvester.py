"""Harvester UK — REAL per-branch prices from its Just Eat storefront.

WHICH BUSINESS
    `harvester.co.uk` (a Mitchells & Butlers brand) exposes its own
    anonymous Click & Collect handshake — `GET
    /cborms/pub/brands/9/outlets/{bunCode}` confirms
    `serviceSwitches.cac.status: "Online"` with no auth needed, and an
    anonymous session (`POST /cborms/pub/brands/login/anonymous
    {"login": true}`) sets working CSRF cookies. But the actual menu-items
    call needs three extra IDs (`scalableBrandId`,
    `scalableBusinessEntityId`, `scalableBusinessEntitySalesAreaId`) that
    are only ever populated client-side onto `window.Estate` by the Vue
    ordering widget, and the specific call/action that populates it was
    not found across ~7.2MB of the widget's own JS bundles (searched both
    as literal API paths and as Redux/Vuex `SET_ESTATE`-style action-type
    strings) nor as an undocumented field on the anonymously-reachable
    outlet JSON. That path is parked, not solved.

    Instead: `miller_carter.py` established that M&B brands carry a
    priced, anonymous, collection-eligible storefront on Just Eat even
    though their own sites are booking-only. The same discovery-API name
    filter finds Harvester branches immediately (e.g. "Harvester -
    George", SM4 5PJ, `isCollection: true, isDelivery: true`), and the
    exact same three-step Just Eat handshake that works for Miller &
    Carter works for Harvester unmodified. See `_mb_just_eat.py` for the
    shared trace and `toby_carvery.py` for the sibling brand this also
    transferred to cleanly.

STORE — Harvester - George (SM4 5PJ)
    First collection-eligible Harvester found on Just Eat searching out
    from Wimbledon (SW19 1EJ); 104 non-deal items.
"""
from __future__ import annotations

from ._mb_just_eat import fetch_je_menu

CHAIN = "harvester"

#: Harvester - George — see STORE in the module docstring.
DEFAULT_STORE_SLUG = "harvester-george"

_NAME_PREFIXES = ("harvester",)


def find_stores(postcode: str) -> list[dict]:
    """Harvester branches Just Eat lists for a UK postcode."""
    from ._mb_just_eat import find_stores as _find
    return _find(postcode, _NAME_PREFIXES, brand=CHAIN)


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one Harvester branch.

    Give a `store_id` (the Just Eat slug), or a `postcode` to use the
    nearest listed branch — check its `isCollection`/`isDelivery` flags
    via `find_stores` first, since not every branch carries either.
    """
    return fetch_je_menu(
        brand=CHAIN, default_store_slug=DEFAULT_STORE_SLUG,
        name_prefixes=_NAME_PREFIXES, display_name_fallback="Harvester",
        store_id=store_id, basis=basis, postcode=postcode)


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:30]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
