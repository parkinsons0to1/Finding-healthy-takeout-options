"""Wingstop UK — REAL per-store prices, cracked directly off the Vita Mojo
(VMOS) ordering platform that powers `wingstop.vmos.io`.

WHERE THE PRIOR PASS STOPPED, AND WHAT UNSTUCK IT
    Wingstop has no Just Eat listing anywhere in London and its Uber Eats
    storefront 403s outright (both re-checked here, both still true).
    `wingstop.co.uk` redirects collection ordering to `wingstop.vmos.io`, a
    Vita Mojo single-spa kiosk app whose own runtime config call —
    `GET /config.json`, issued with no query string or special headers by
    the app's own bootstrap code (read directly out of the downloaded
    `main.js`) — previously 500'd on every request shape tried
    (`{"status":500,"error":"Invalid URL string."}`), including plain
    `requests`, curl_cffi, with and without `Referer`/`Origin`.

    The unlock: **`Origin` alone, with no `Referer`, returns 200.** Every
    header combination tried this pass:
      - no headers at all              -> 500 "Invalid URL string."
      - `Referer` only                 -> 403 (Cloudflare WAF block page)
      - `Origin` + `Referer` together  -> 403 (matches the prior pass's note)
      - `Origin` alone                 -> 200, real config JSON
    So the 500 was never a broken endpoint — it is a request-URL-building
    bug in Vita Mojo's own edge function that only reconstructs a valid URL
    when an `Origin` header is present and a `Referer` is not, which no
    browser ever sends on a same-origin `fetch()` (browsers omit `Referer`
    for many same-origin/`no-referrer-when-downgrade` cases while always
    setting `Origin` on CORS-eligible requests) but which is easy to miss
    when replaying the call by hand. `base.fetch_protected` now takes an
    optional `headers` dict for exactly this.

    `config.json`'s `API_ROOT` (`https://vmos2.vmos.io`) is Vita Mojo's
    shared multitenant API — confirmed generic, not Wingstop-specific: its
    CSP allowlists `media.subway.com` and the same config carries a
    `SUBWAY_API_ROOT` key, because Subway UK is on the same platform and
    ships the same build template. Wingstop's tenant is resolved from the
    `Origin` header on `GET {API_ROOT}/tenant/v1/bootstrap`. A public
    Vita Mojo utility script (`vita-mojo/menu` on GitHub, `menu_export.py`)
    and a third-party VMOS API client (`alexechoi/gails-bakery-mcp`, built
    against Gail's Bakery's own VMOS tenant) between them confirm every
    endpoint shape used below, including the one this pass would not have
    found by bundle-reading alone: **`/tenant/v1/stores/tenant`**, the
    public (no-auth) store finder, which needs lat/long (not just a
    postcode — geocoded here via postcodes.io, same as the Gail's client
    does) plus a `weekday` query param. `/catalog/v2/menu` and
    `/catalog/categories/{uuid}/bundles` (both public, no auth — the
    `gails-bakery-mcp` README states this outright and it checks out here:
    every call below carries only a `tenant`/`store`/`menu` header, never an
    `Authorization` bearer) round out the chain: menu -> categories ->
    per-category bundles, and the priced catalogue falls out of the last
    call directly — no separate items/bundles endpoint needed, unlike
    `menu_export.py`'s older `/catalog/menu` (v1) flow, because the v2
    bundles response already inlines each item's
    `customizations[].variations[].price`.

HANDSHAKE
    1. ``GET https://vmos2.vmos.io/tenant/v1/bootstrap`` with header
       ``Origin: https://wingstop.vmos.io`` -> ``payload.tenant.uuid``
       (pinned below as `TENANT_UUID`; re-derived live by `_tenant_uuid()`
       so a Vita Mojo-side rotation doesn't silently go stale).
    2. Geocode a postcode via `api.postcodes.io` (no key, no auth) for
       lat/long.
    3. ``GET {API_ROOT}/tenant/v1/stores/tenant?lat=..&long=..&postcode=..&
       weekday=..&status=1&sortBy[]=name&sortBy[]=sortOrder&
       sortBy[]=distance&sortDir=ASC`` with header ``tenant: {uuid}`` ->
       every Wingstop branch (this endpoint is tenant-scoped already, no
       name filter needed, unlike the Just Eat discovery APIs other
       adapters use).
    4. ``GET {API_ROOT}/catalog/v2/menu`` with headers ``tenant``, ``store``
       -> the takeaway menu's UUID and its category list.
    5. ``GET {API_ROOT}/catalog/categories/{uuid}/bundles`` per category,
       with headers ``tenant``, ``store``, ``menu`` -> priced bundles. Each
       bundle's own top-level `price` is always 0 (a placeholder); the real
       price is `items[].customizations[].variations[].price` — one
       variation per purchasable size/flavour (checked: every customization
       across all 11 categories is `type: "size"`, nothing else).
    Every request goes through `fetch_protected` — Cloudflare sits in front
    of both `wingstop.vmos.io` and `vmos2.vmos.io` (confirmed by the
    `server: cloudflare` response header on both), and only curl_cffi's
    browser TLS fingerprint gets past it even once the header shape above
    is right.

PRICE BASIS — collection
    This is Wingstop's own kiosk/click-and-collect ordering flow (what
    `wingstop.co.uk`'s "Order Now" hands off to), not a marketplace. Rows
    are labelled "collection".

NUTRITION-DB JOIN — aliased to `data/db/wingstop.json`'s naming, verified by
    exact kcal match, not guessed
    `data/db/wingstop.json` comes from a transposed, stale (2022, archived
    2023) allergen PDF whose product names are page headings ("WINGS"),
    never the catalogue's own item names ("8 Wings"). Live catalogue items
    are aliased to the PDF's exact spelling only where the API's own
    `nutritionalMeta.calories` matches the PDF's `kcal` for that item
    *exactly* — the same standard `itsu.py`/`tortilla.py` use for their PDF
    aliases:
      - "8/10/12 Wings"            -> kcal 625/782/939, matches
        "Wings (N Pieces) ...g" exactly.
      - "8/10/12 Pieces Boneless"  -> kcal 420/526/631, matches
        "Boneless (N Pieces) ...g" exactly.
      - "3/5 Tenders"              -> kcal 337/562, matches
        "Tenders (N Pieces) ...g" exactly.
      - "Big Flavour Burger"       -> kcal 629, matches
        "Big Flavour Burger (240g)" exactly.
      - "Ranch" (a House Dip)      -> kcal 197, matches
        "Ranch Dip (42g)" exactly.
      - "Blue Cheese" (a House Dip) -> kcal 105, matches the PDF's generic
        "Dips (42g)" row exactly (the PDF row has no flavour of its own to
        disambiguate; this is the only dip whose kcal lands on it).
    Every other live item (seasoning packets, sauces, fries by weight, the
    PDF's oddly-labelled "Sides (200g)"/"Sides (250g)" rows — themselves a
    symptom of the transposition bug `wingstop.py` documents, since the
    live catalogue's fries kcal is per-100g, not per a "200g"/"250g"
    serving) has no confident 1:1 kcal match and is emitted only under its
    own live catalogue name, same as itsu's/tortilla's "NOT MATCHED"
    sections — nothing here is force-aliased on a name-only guess.

NOT PRICED HERE — meal-deal combos
    "Real Deals" category items (`"The Flavour Fix" Boneless (For 1)`,
    `Meal Deal for 3`, etc.) are emitted under their own combo names with
    the deal's `pricesFrom.price` — real prices, but for a fixed multi-item
    combo with no single-item nutrition-DB counterpart, so they were never
    going to join and aren't aliased.

PER STORE
    Wingstop - Wandsworth (SW18 4FT) is the default — nearest Wingstop
    branch the store finder returns for SW19 3RU (Wimbledon), this
    project's other south-London default postcode (itsu.py, tortilla.py).
"""
from __future__ import annotations

import datetime
import re

from ..base import fetch_protected, session

CHAIN = "wingstop"

API_ROOT = "https://vmos2.vmos.io"
ORIGIN = "https://wingstop.vmos.io"

#: Wingstop's tenant UUID on the Vita Mojo multitenant platform. Re-derived
#: live by `_tenant_uuid()`; pinned here only as the value to fall back on
#: if that call ever fails, and so a diff shows if it ever changes.
TENANT_UUID = "ae9f4d36-8fac-499a-8f99-8b777f5e55e2"

#: Wingstop - Wandsworth, SW18 4FT — nearest branch the store finder
#: returns for SW19 3RU (Wimbledon), this project's other south-London
#: default postcode.
DEFAULT_STORE_UUID = "8d55fd4f-cef2-462c-805c-2e9dc34f0c85"
DEFAULT_STORE_LABEL = "Wingstop - Wandsworth (SW18 4FT)"
DEFAULT_POSTCODE = "SW19 3RU"

#: Live catalogue item name (lowercased) -> the nutrition PDF's exact
#: spelling in `data/db/wingstop.json`. Every pairing verified by an exact
#: kcal match between the API's `nutritionalMeta.calories` and the PDF's
#: `kcal` — see the module docstring's NUTRITION-DB JOIN section.
_PDF_ALIASES = {
    "8 wings": "Wings (8 Pieces) 370g",
    "10 wings": "Wings (10 Pieces) 462g",
    "12 wings": "Wings (12 Pieces) 555g",
    "8 pieces boneless": "Boneless (8 Pieces) 176g",
    "10 pieces boneless": "Boneless (10 Pieces) 220g",
    "12 pieces boneless": "Boneless (12 Pieces) 264g",
    "3 tenders": "Tenders (3 Pieces) 135g",
    "5 tenders": "Tenders (5 Pieces) 225g",
    "big flavour burger": "Big Flavour Burger (240g)",
    "ranch": "Ranch Dip (42g)",
    "blue cheese": "Dips (42g)",
}


def _get(url: str, headers: dict) -> dict:
    r = fetch_protected(url, headers={"Origin": ORIGIN, **headers})
    if r is None:
        raise RuntimeError(f"wingstop: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    if r.status_code != 200:
        raise RuntimeError(f"wingstop: GET {url} HTTP {r.status_code}: "
                           f"{r.text[:200]!r}")
    try:
        return r.json()
    except ValueError as exc:
        raise RuntimeError(f"wingstop: GET {url} did not return JSON "
                           f"({exc})") from None


def _tenant_uuid() -> str:
    """Wingstop's tenant UUID, resolved live from the `Origin` header —
    see the module docstring for why `Origin` alone (no `Referer`) is what
    gets this call past the 500 "Invalid URL string." every other header
    shape hits."""
    try:
        data = _get(f"{API_ROOT}/tenant/v1/bootstrap",
                    {"x-requested-from": "online"})
        uuid = ((data.get("payload") or {}).get("tenant") or {}).get("uuid")
        if uuid:
            return uuid
    except Exception:
        pass
    return TENANT_UUID


def _geocode(postcode: str) -> tuple[float, float]:
    """UK postcode -> (lat, long) via postcodes.io — free, keyless, no auth.
    The Vita Mojo store finder requires lat/long; a postcode alone is not
    enough (confirmed against `alexechoi/gails-bakery-mcp`'s client, which
    geocodes the same way for the same reason)."""
    s = session()
    r = s.get(f"https://api.postcodes.io/postcodes/{postcode.replace(' ', '')}",
              timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"wingstop: postcodes.io HTTP {r.status_code} "
                           f"for {postcode!r}")
    result = (r.json() or {}).get("result") or {}
    lat, lng = result.get("latitude"), result.get("longitude")
    if lat is None or lng is None:
        raise RuntimeError(f"wingstop: postcodes.io returned no "
                           f"coordinates for {postcode!r}")
    return float(lat), float(lng)


def find_stores(postcode: str, tenant_uuid: str | None = None) -> list[dict]:
    """Wingstop branches Vita Mojo's public store finder lists for a UK
    postcode, nearest first. No name filter needed — this endpoint is
    already scoped to the Wingstop tenant."""
    tenant_uuid = tenant_uuid or _tenant_uuid()
    lat, lng = _geocode(postcode)
    weekday = datetime.datetime.now().isoweekday()  # ISO 1=Mon..7=Sun
    params = "&".join([
        "offset=0", "limit=15", f"postcode={postcode.replace(' ', '%20')}",
        f"lat={lat}", f"long={lng}", "sortBy%5B%5D=name",
        "sortBy%5B%5D=sortOrder", "sortBy%5B%5D=distance", "sortDir=ASC",
        "status=1", f"weekday={weekday}",
    ])
    data = _get(f"{API_ROOT}/tenant/v1/stores/tenant?{params}",
               {"tenant": tenant_uuid, "x-requested-from": "online"})
    stores = data.get("payload") or []
    if not stores:
        raise RuntimeError(f"wingstop: no Wingstop branches found near "
                           f"{postcode!r}")
    return stores


def _menu(tenant_uuid: str, store_uuid: str) -> dict:
    data = _get(f"{API_ROOT}/catalog/v2/menu", {
        "tenant": tenant_uuid, "store": store_uuid,
        "x-requested-from": "online", "locale": "en-GB",
    })
    menus = data.get("payload") or []
    if not menus:
        raise RuntimeError(f"wingstop: empty menu for store {store_uuid!r} "
                           f"— either a bad store UUID or the catalogue "
                           f"shape moved")
    return menus[0]


def _category_bundles(tenant_uuid: str, store_uuid: str, menu_uuid: str,
                      category_uuid: str) -> dict:
    return _get(
        f"{API_ROOT}/catalog/categories/{category_uuid}/bundles",
        {"tenant": tenant_uuid, "store": store_uuid, "menu": menu_uuid,
         "x-requested-from": "online"})


_WS = re.compile(r"\s+")


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Vita Mojo catalogue for one Wingstop branch.

    Give a `store_id` (a Vita Mojo store UUID from `find_stores`), or a
    `postcode` to use the nearest listed branch. Only "collection" is
    offered — this is Wingstop's own kiosk/click-and-collect ordering flow,
    there is no separate delivery channel to read a price from.
    """
    if basis != "collection":
        raise ValueError(f"wingstop: unknown basis {basis!r} (only "
                         f"'collection' — see module docstring)")

    tenant_uuid = _tenant_uuid()

    label = DEFAULT_STORE_LABEL
    if store_id is None and postcode:
        found = find_stores(postcode, tenant_uuid)
        record = found[0]
        store_uuid = record["uuid"]
        name = (record.get("name") or "").strip() or store_uuid
        addr = record.get("address")
        label = f"Wingstop - {name} ({addr})" if addr else f"Wingstop - {name}"
    else:
        store_uuid = store_id or DEFAULT_STORE_UUID

    menu = _menu(tenant_uuid, store_uuid)
    menu_uuid = menu["uuid"]
    categories = menu.get("categories") or []
    if not categories:
        raise RuntimeError(f"wingstop: menu {menu_uuid!r} has no categories "
                           f"— the catalogue shape moved")

    out: list[dict] = []
    seen: set[str] = set()

    def _emit(name: str, price, category: str, kcal=None):
        name = _WS.sub(" ", name).strip()
        if not name or price is None:
            return
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        out.append({
            "name": name, "price_gbp": round(float(price), 2),
            "basis": "collection", "store": label, "category": category,
            "kcal": kcal,
        })
        alias = _PDF_ALIASES.get(key)
        if alias:
            akey = alias.lower()
            if akey not in seen:
                seen.add(akey)
                out.append({
                    "name": alias, "price_gbp": round(float(price), 2),
                    "basis": "collection", "store": label,
                    "category": category, "kcal": kcal,
                })

    for cat in categories:
        cat_uuid, cat_name = cat["uuid"], cat.get("name") or ""
        payload = _category_bundles(tenant_uuid, store_uuid, menu_uuid,
                                    cat_uuid).get("payload") or {}

        for bundle in payload.get("bundles") or []:
            bundle_name = (bundle.get("name") or "").strip()
            for it in bundle.get("items") or []:
                item_name = (it.get("name") or "").strip() or bundle_name
                kcal = (it.get("nutritionalMeta") or {}).get("calories")
                for cu in it.get("customizations") or []:
                    for var in cu.get("variations") or []:
                        var_name = (var.get("name") or "").strip()
                        price = var.get("price")
                        full_name = (f"{item_name} ({var_name})" if var_name
                                    else item_name)
                        _emit(full_name, price, cat_name, kcal)

        # Fixed-recipe combo deals (module docstring's NOT PRICED HERE
        # section) — priced but never aliased to a single-item nutrition row.
        for deal in payload.get("deals") or []:
            name = (deal.get("name") or "").strip()
            price = (deal.get("pricesFrom") or {}).get("price")
            _emit(name, price, cat_name)

    if not out:
        raise RuntimeError(
            f"wingstop: {len(categories)} categories for {label} but no "
            f"priced items survived parsing — the catalogue shape moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
