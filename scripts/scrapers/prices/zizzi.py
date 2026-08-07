"""Zizzi UK — REAL per-branch prices from Zizzi's OWN ordering site.

WHICH BUSINESS
    `www.zizzi.co.uk` links every branch's "Order" button straight to
    `zizzi.orderswift.com/{branch-slug}` — Zizzi's own storefront, built on
    Orderswift, a white-label ordering platform (also used by ASK Italian,
    see `ask_italian.py` — both brands are Azzurri Group). This is a genuine
    first-party channel, not a marketplace: it is Zizzi's own domain/brand
    (co-branded with "Powered by Orderswift" in the page `<title>`), takes no
    account to browse, and Deliveroo/Uber Eats/Just Eat listings exist
    separately alongside it (also linked from the homepage) rather than
    being the only option.

Handshake
---------
The storefront is a client-rendered React app — its JS bundle
(`/static/js/main.*.js`) was read to find the API call, not guessed. Plain
`requests`, no Cloudflare/TLS obstacle encountered.

1. ``GET https://api.orderswift.com/sites?handle=zizzi`` — every UK branch,
   with its own `handle` (a slug like "sutton", "kingston") and which
   channels it currently offers (`channels: {collection: {...}}` and/or
   `delivery`). No auth, no postcode needed for the full list.
2. ``GET https://api.orderswift.com/menu`` with query params
   ``handle=zizzi&site_handle={branch_slug}&channel={collection|delivery}&
   flow=-&distinct_id=unused`` (`postcode` is additionally required when
   `channel=delivery`) — the priced menu for that branch and channel.

TRAP — `handle` is the BRAND (site subdomain), `site_handle` is the BRANCH
    Confusing the two 404s/500s. Found by reading the bundle's `fetchSite`
    call chain: `window.location.host.split(".")[0]` (i.e. "zizzi" on
    `zizzi.orderswift.com`) is passed as `handle`; the per-branch URL slug
    (e.g. "/bradford") is `site_handle`.

NOT A TRAP HERE — delivery and collection are priced identically
    Checked at Kingston (the nearest branch offering both channels): all 115
    items, byte-identical price both ways. So this module defaults to
    "collection" (no postcode required) and does not duplicate rows per
    channel.

PRICE BASIS AND FORMAT
    Prices are integer pence (`item["price"]`, e.g. `995` = £9.95) with no
    separate size/portion split for pizza, pasta or mains — Zizzi's menu
    (unlike Pizza Express) sells one size per dish. `modifier_groups` on each
    item are optional extras (extra toppings, add chicken, etc.) with their
    own `price` in pence; this module reads only the base item price, not
    modifiers, matching how every other adapter in this project reports a
    dish's own price without upsells.

NAME DRIFT — none needed
    Every item name checked against `data/db/zizzi.json` (this project's
    nutrition table) already matches verbatim; no alias table was needed.

TRAP — the collection-channel menu serves items self-labelled "DELIVERY
       EXCLUSIVE", and nothing else marks them as channel-restricted
    "DELIVERY EXCLUSIVE ⭐ Meat Lover's Feast" and "DELIVERY EXCLUSIVE ⭐
    Double Margherita" both come back from `channel=collection`, unhidden,
    fully priced — there is no `is_hidden` flag or separate field saying so;
    the only signal is the literal string in the item's own name. Serving
    that price labelled `basis="collection"` would tell a customer they can
    walk in and buy it, which the item's own name says is false. Rows whose
    name starts "DELIVERY EXCLUSIVE" are dropped when `basis != "delivery"`.

PER STORE
    Zizzi - Sutton, SM1 1DF (`site_handle="sutton"`) is the default, matching
    every other adapter's south-London default. Sutton only offers
    collection on this platform.
"""
from __future__ import annotations

from ..base import session

CHAIN = "zizzi"

SITES_URL = "https://api.orderswift.com/sites"
MENU_URL = "https://api.orderswift.com/menu"
BRAND_HANDLE = "zizzi"

#: Zizzi - Sutton, SM1 1DF.
DEFAULT_SITE_HANDLE = "sutton"


def _get(url: str, **params):
    s = session()
    r = s.get(url, params=params, timeout=30)
    return r


def list_sites() -> list[dict]:
    """Every UK Zizzi branch Orderswift knows about, with its channels."""
    r = _get(SITES_URL, handle=BRAND_HANDLE)
    if r.status_code != 200:
        raise RuntimeError(f"zizzi: sites API HTTP {r.status_code}")
    return (r.json() or {}).get("data") or []


def fetch_prices(site_handle: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Orderswift menu for one Zizzi branch.

    `basis` is "collection" (default, no postcode needed) or "delivery"
    (needs `postcode`) — verified identically priced at every branch checked
    that offers both.
    """
    if basis not in ("collection", "delivery"):
        raise ValueError(f"zizzi: unknown basis {basis!r}")
    if basis == "delivery" and not postcode:
        raise ValueError("zizzi: basis='delivery' needs a postcode")

    slug = site_handle or DEFAULT_SITE_HANDLE
    params = {"handle": BRAND_HANDLE, "site_handle": slug, "channel": basis,
              "flow": "-", "distinct_id": "unused"}
    if postcode:
        params["postcode"] = postcode.replace(" ", "").upper()

    r = _get(MENU_URL, **params)
    if r.status_code != 200:
        raise RuntimeError(f"zizzi: menu API HTTP {r.status_code} for {slug!r}")
    payload = r.json() or {}
    errors = payload.get("errors") or {}
    if errors.get("input") or errors.get("app"):
        raise RuntimeError(f"zizzi: menu API rejected the request for {slug!r} "
                           f"({errors})")
    data = payload.get("data") or {}
    site = data.get("site") or {}
    menu = data.get("menu")
    if not menu or not site.get("is_open", True) and not menu.get("categories"):
        raise RuntimeError(f"zizzi: no menu returned for {slug!r} — the branch "
                           f"may not offer {basis!r} (check `list_sites()`)")

    categories = menu.get("categories") or []
    if not categories:
        raise RuntimeError(f"zizzi: menu for {slug!r} came back with zero "
                           f"categories — the response shape may have moved")

    town = site.get("address_postcode")
    name = site.get("name") or slug
    label = f"Zizzi - {name} ({town})" if town else f"Zizzi - {name}"

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
            if basis != "delivery" and item_name.upper().startswith("DELIVERY EXCLUSIVE"):
                continue  # served on this channel anyway, but not buyable here
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
        raise RuntimeError(f"zizzi: {slug!r} had {len(categories)} categories "
                           f"but zero priced items — the item shape has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
