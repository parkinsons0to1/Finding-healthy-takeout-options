"""ASK Italian UK — REAL per-branch prices from ASK's OWN ordering site.

WHICH BUSINESS
    `www.askitalian.co.uk` links every branch's "Order" button to
    `askitalian.orderswift.com/{branch-slug}` — ASK's own storefront on
    Orderswift, the same white-label platform Zizzi runs (both are Azzurri
    Group brands; see `zizzi.py` for the platform's shared handshake and how
    it was found in the JS bundle). First-party: ASK's own domain, no
    account, Deliveroo/Uber Eats/Just Eat listings exist separately alongside
    it rather than being the only option.

Handshake
---------
Identical to `zizzi.py`, just a different brand `handle`.

1. ``GET https://api.orderswift.com/sites?handle=askitalian`` — every branch
   with its slug and open channels.
2. ``GET https://api.orderswift.com/menu`` with
   ``handle=askitalian&site_handle={branch_slug}&channel={collection|delivery}&
   flow=-&distinct_id=unused`` (+ `postcode` for delivery).

PRICE BASIS AND FORMAT — same as Zizzi
    Integer pence, one size per dish (no separate portion tiers), each item
    also carries its own `calories` figure from the same catalogue (useful as
    a cross-check against `data/db/ask_italian.json`, not currently
    consumed by this module).

PER STORE
    ASK Italian has no branch in Sutton itself (checked the full `/sites`
    list, sorted by straight-line distance to SM1) — Epsom, KT19 8DD is the
    nearest, and is the default (`site_handle="epsom"`). Epsom only offers
    collection on this platform.
"""
from __future__ import annotations

from ..base import session

CHAIN = "ask_italian"

SITES_URL = "https://api.orderswift.com/sites"
MENU_URL = "https://api.orderswift.com/menu"
BRAND_HANDLE = "askitalian"

#: ASK Italian - Epsom, KT19 8DD — nearest branch to this project's Sutton
#: default (ASK has none in Sutton itself).
DEFAULT_SITE_HANDLE = "epsom"


def _get(url: str, **params):
    s = session()
    return s.get(url, params=params, timeout=30)


def list_sites() -> list[dict]:
    """Every UK ASK Italian branch Orderswift knows about, with its channels."""
    r = _get(SITES_URL, handle=BRAND_HANDLE)
    if r.status_code != 200:
        raise RuntimeError(f"ask_italian: sites API HTTP {r.status_code}")
    return (r.json() or {}).get("data") or []


def fetch_prices(site_handle: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Orderswift menu for one ASK Italian branch.

    `basis` is "collection" (default, no postcode needed) or "delivery"
    (needs `postcode`).
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"ask_italian: unknown basis {basis!r}")
    if basis == "delivery" and not postcode:
        raise ValueError("ask_italian: basis='delivery' needs a postcode")

    slug = site_handle or DEFAULT_SITE_HANDLE
    params = {"handle": BRAND_HANDLE, "site_handle": slug, "channel": basis,
              "flow": "-", "distinct_id": "unused"}
    if postcode:
        params["postcode"] = postcode.replace(" ", "").upper()

    r = _get(MENU_URL, **params)
    if r.status_code != 200:
        raise RuntimeError(f"ask_italian: menu API HTTP {r.status_code} for {slug!r}")
    payload = r.json() or {}
    errors = payload.get("errors") or {}
    if errors.get("input") or errors.get("app"):
        raise RuntimeError(f"ask_italian: menu API rejected the request for "
                           f"{slug!r} ({errors})")
    data = payload.get("data") or {}
    site = data.get("site") or {}
    menu = data.get("menu")
    if not menu:
        raise RuntimeError(f"ask_italian: no menu returned for {slug!r} — the "
                           f"branch may not offer {basis!r} (check `list_sites()`)")

    categories = menu.get("categories") or []
    if not categories:
        raise RuntimeError(f"ask_italian: menu for {slug!r} came back with zero "
                           f"categories — the response shape may have moved")

    town = site.get("address_postcode")
    name = site.get("name") or slug
    label = f"ASK Italian - {name} ({town})" if town else f"ASK Italian - {name}"

    out: list[dict] = []
    for cat in categories:
        cat_name = cat.get("name")
        for it in cat.get("items") or []:
            if it.get("is_hidden"):
                continue
            price = it.get("price")
            if price is None:
                continue
            item_name = (it.get("name") or "").strip()
            if not item_name:
                continue
            row = {
                "name": item_name,
                "price_gbp": round(price / 100, 2),
                "basis": basis,
                "store": label,
                "category": cat_name,
            }
            kcal = it.get("calories")
            if kcal:
                try:
                    row["kcal"] = float(kcal)
                except (TypeError, ValueError):
                    pass
            out.append(row)

    if not out:
        raise RuntimeError(f"ask_italian: {slug!r} had {len(categories)} "
                           f"categories but zero priced items — the item shape "
                           f"has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
