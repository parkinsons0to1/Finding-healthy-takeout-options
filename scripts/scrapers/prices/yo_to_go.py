"""YO! To Go UK — REAL per-kiosk prices from YO!'s Just Eat storefront.

WHICH BUSINESS
    YO! To Go is the grab-and-go kiosk format of YO! (found inside Tesco
    stores and similar), distinct from the full-service "YO! Sushi"
    restaurant chain `yo_sushi.py` prices — `data/db/yo_to_go.json`'s
    nutrition source is YO!'s own March-2022 "Allergen Guide - YO! To Go"
    PDF, a different document from the Tenkites allergen menu `yo_sushi.py`
    uses. Just Eat's discovery-by-postcode API lists these kiosks under
    names like "YO! sushi counter - (New Malden Tesco)" and "Yo! Tesco
    Kiosk - Tooley Street" — separate restaurant listings from any
    full-service "YO! Sushi {town}" branch, confirming the two are priced
    and catalogued independently on this marketplace too. Like every other
    Just-Eat-only chain in this project, the per-kiosk priced menu here is
    read from Just Eat (`www.just-eat.co.uk`) — public, no account — and is
    labelled as a Just Eat price throughout, never implied to be a price YO!
    publishes itself. (See `yo_sushi.py` for why YO!'s first-party ordering
    app, built on the Vita Mojo platform, wasn't used instead — the same
    reasoning applies here.)

Handshake
---------
Identical three-step shape to `subway.py`/`itsu.py`; see `subway.py` for the
full trace of how each URL was found. Every request goes through
`scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of both
the site and its API host; curl_cffi's safari profile gets through).

1. ``GET https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}``
   — filter `restaurants[].name` for "Yo"/"YO!" + "Tesco"/"kiosk"/"counter",
   distinguishing kiosks from full-service "YO! Sushi {town}" restaurants.
2. ``GET https://www.just-eat.co.uk/restaurants-{slug}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN
   base (read live, not pinned), `...cdn.restaurant.itemsUrl` is the
   catalogue filename.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

NOT A TRAP HERE — no channel split, no DealOnly stubs
    Every one of the 55 items at the Tooley Street kiosk carries BOTH
    menuGroupIds (delivery and collection) on its single variation, the
    same shape as `itsu.py`/`pret.py`/`tortilla.py` — checked exhaustively,
    55/55. All are `DealOnly: false`. Rows are labelled "collection".

NAME DRIFT — a "(VE)"/"(V)" dietary tag on the Just Eat name blocks an
    otherwise-exact match
    This kiosk's catalogue suffixes several plant-based items with " (VE)"
    ("avocado maki (VE)", "cucumber maki (VE)") where the nutrition PDF's
    row carries no such tag ("Avocado Maki", "Cucumber Maki") — confirmed by
    calorie proximity (203 vs PDF 199.3; 152 vs PDF 145.5). This module
    strips a trailing "(VE)"/"(V)" tag before matching and before emitting
    the row name, the same kind of decoration-stripping `pret.py` does for
    invisible Unicode characters. Checked for collisions first: only one
    pair of names in this catalogue coincides after stripping ("Korean Beef
    Rice Bowl" appears twice already, unrelated to any VE tag), so the
    strip does not conflate a vegan and non-vegan version of anything.

CAUTION — this kiosk's menu has drifted a long way from the March-2022 PDF,
    and NOT every exact-name match is trustworthy
    Only a handful of nutrition-PDF rows have any Just Eat counterpart at
    this kiosk at all — most of the PDF's "Bowl" range (Glow/Nourish/Power/
    Vitality Bowl), several roll flavours, and the "Pick 'n' Mix"/sharer
    items it names have no product of that name here. Of the names that DO
    match exactly, several disagree sharply on kcal against the PDF ("Sushi
    Sharer": PDF 545.9 kcal vs this kiosk's 1116 kcal; "Classic Catch": PDF
    483.5 vs 1070; "O-mega Salmon": PDF 480.8 vs 600) — almost certainly a
    larger 2026 portion/recipe than the 2022 PDF describes, not a different
    product, but a real number nonetheless. This module still emits these
    rows under their real Just Eat name (suppressing a real price because
    an old PDF's calorie figure looks stale would be a worse failure mode
    than flagging the mismatch), but the mismatch is recorded here rather
    than silently trusted.

PRICE BASIS — collection, from YO!'s Just Eat storefront
    Rows are labelled "collection" (see the channel-duplication section
    above for why collection and delivery are the same number here). This
    is a real per-kiosk price a customer pays today, but it is YO!'s price
    on a third-party marketplace, not necessarily the walk-up kiosk price;
    no channel for that comparison exists online (see `subway.py` for the
    identical caveat).

PER STORE
    Yo! Tesco Kiosk - Tooley Street (SE1 2RS) is the default — in Southwark,
    consistent with this project's other south-London defaults (e.g.
    `wasabi.py`'s Borough branch is a few minutes' walk away); "YO! sushi
    counter - (New Malden Tesco)" is the only other kiosk Just Eat lists
    near this project's usual postcodes and was checked too (62 items, even
    less nutrition-PDF overlap: 1/46 before the VE-strip fix).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "yo_to_go"

DISCOVERY = "https://uk.api.just-eat.io/discovery/uk/restaurants/enriched/bypostcode/{postcode}"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: Yo! Tesco Kiosk - Tooley Street, SE1 2RS — in Southwark, consistent with
#: this project's other south-London defaults.
DEFAULT_STORE_SLUG = "yo-tesco-kiosk---tooley-street-southwark"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)
#: A trailing "(VE)"/"(V)" dietary tag — see the module docstring's NAME
#: DRIFT section.
_DIET_TAG_RE = re.compile(r'\s*\((ve|v)\)\s*$', re.I)


def _clean_name(raw: str) -> str:
    return _DIET_TAG_RE.sub("", (raw or "").strip()).strip()


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"yo_to_go: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores(postcode: str) -> list[dict]:
    """YO! To Go kiosks Just Eat lists for a UK postcode, nearest first —
    filtered to the kiosk naming pattern so a full-service "YO! Sushi
    {town}" restaurant (`yo_sushi.py`'s chain) is never mixed in."""
    url = DISCOVERY.format(postcode=postcode.replace(" ", "").upper())
    r = _get(url)
    if r.status_code == 404:
        raise RuntimeError(f"yo_to_go: postcode {postcode!r} rejected by "
                           f"the discovery API (check formatting)")
    if r.status_code != 200:
        raise RuntimeError(f"yo_to_go: discovery API HTTP {r.status_code}")
    restaurants = (r.json() or {}).get("restaurants") or []
    out = []
    for x in restaurants:
        nm = str(x.get("name") or "").strip().lower()
        if not (nm.startswith("yo") or "yo!" in nm):
            continue
        if "tesco" in nm or "kiosk" in nm or "counter" in nm:
            out.append(x)
    return out


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"yo_to_go: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"yo_to_go: menu page HTTP {r.status_code} for "
                           f"{slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"yo_to_go: __NEXT_DATA__ not found for {slug!r} "
                           f"— the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"yo_to_go: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("yo_to_go: no UK menu-CDN base in __NEXT_DATA__ "
                           "— clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "yo_to_go: preloadedState.menu.restaurant.cdn.restaurant "
            "missing — the Next.js state shape has moved") from None


def _category_map(restaurant: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for menu in restaurant.get("menus") or []:
        for cat in menu.get("categories") or []:
            name = cat.get("name")
            for item_id in cat.get("itemIds") or []:
                out.setdefault(item_id, name)
    return out


def _kcal(nutritional_info) -> float | None:
    text = (nutritional_info or {}).get("EnergyDisplay") or ""
    m = _ENERGY_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def fetch_prices(store_id: str | None = None, basis: str = "collection",
                 postcode: str | None = None) -> list[dict]:
    """Priced Just Eat menu for one YO! To Go kiosk.

    Give a `store_id` (the Just Eat slug, e.g.
    "yo-tesco-kiosk---tooley-street-southwark"), or a `postcode` to use the
    nearest listed kiosk. Only "collection" is offered — every item checked
    prices identically on both service types on this platform (see module
    docstring), so there is no separate delivery basis to select.
    """
    if basis != "collection":
        raise ValueError(f"yo_to_go: unknown basis {basis!r} (only "
                         f"'collection' — Just Eat delivery prices for this "
                         f"chain are identical, see module docstring)")

    record = None
    if store_id is None and postcode:
        found = find_stores(postcode)
        if not found:
            raise RuntimeError(f"yo_to_go: no YO! To Go kiosk listed on "
                               f"Just Eat for {postcode!r}")
        record = found[0]
        slug = record["uniqueName"]
    else:
        slug = store_id or DEFAULT_STORE_SLUG

    next_data = _menu_page(slug)
    cdn_base = _cdn_base(next_data)
    restaurant = _restaurant_node(next_data)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"yo_to_go: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"yo_to_go: items JSON HTTP {r.status_code} for "
                           f"{slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"yo_to_go: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"yo_to_go: items JSON for {slug!r} came back "
                           f"empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or (record or {}).get("name")
            or f"YO! To Go ({slug})").strip()
    addr = (record or {}).get("address") or {}
    town = addr.get("postalCode")
    label = f"{name} ({town})" if town else name

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        item_id = item.get("Id")
        category = categories.get(item_id)
        product_name = _clean_name(item.get("Name") or "")
        for variation in item.get("Variations") or []:
            if variation.get("DealOnly"):
                continue
            price = variation.get("BasePrice")
            if price is None or not product_name:
                continue
            key = product_name.lower()
            if key in seen:
                continue
            seen.add(key)
            kcal = _kcal(variation.get("NutritionalInfo"))
            out.append({
                "name": product_name,
                "price_gbp": round(float(price), 2),
                "basis": "collection",
                "store": label,
                "category": category,
                "kcal": kcal,
            })

    if not out:
        raise RuntimeError(
            f"yo_to_go: {len(raw_items)} items for {label} but none "
            f"survived the DealOnly filter — the catalogue shape has "
            f"changed")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
