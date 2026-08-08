"""Slim Chickens UK — REAL per-venue prices from the OrderPay platform.

WHICH PLATFORM
    `www.slimchickens.co.uk` links its "Order Now" tiles at
    `https://<venue-slug>.order.orderpay.com` — a white-label click-and-collect
    /table-service web app built by OrderPay (a UK ordering SaaS, not
    Slim Chickens' own backend). The whole storefront is a React SPA served
    from S3/CloudFront with no server-side price data; the priced menu is
    read from OrderPay's own JSON API, `device-gateway.orderpay.com/api`,
    which — unlike Pizza Hut/Taco Bell's Yum! stack — answers plain
    `requests` directly, no TLS impersonation, no token, no auth of any kind.

Handshake
---------
Three unauthenticated GET calls, chained by ID:

1. ``GET /api/1/brands/slug/{brand-slug}`` — the slug is the subdomain
   (e.g. `slim-chickens-click-and-collect`); returns ``{"id": "<brandId>"}``.
2. ``GET /api/1/venues?lat={lat}&long={lng}&brandId={brandId}&pageNumber=0&
   pageSize=10&sortBy=distance&sortOrder=ASC`` — nearby venues, nearest
   first; each has an ``id`` (venue UUID) and postal address.
3. ``GET /api/1/venues/{venueId}/menu`` — the full priced, calorie-annotated
   menu for that venue: a list of top-level sections, each with
   ``menuCategories[].products[]``, each product carrying
   ``price.units`` (pence), ``calories`` and ``isOutOfStock``.

TRAP — the venue-search param names are `lat`/`long`, not `latitude`/
`longitude`
    The React bundle's own action creator forwards its caller's params object
    straight through, so passing `latitude`/`longitude` (the names visible in
    a nearby different call) is accepted by the API with no error and
    silently ignored — the search falls back to *no* geo filter and returns
    venues in an unrelated, non-distance order (Milton Keynes and Liverpool
    ahead of every London branch when queried from London). `lat`/`long`
    (confirmed against the bundle's own dispatch call) sorts correctly.

TRAP — `calories: "-1"` means "not published for this item", not zero
    A meaningful minority of products (bundle bundles, some wing flavours)
    report ``"calories": "-1"`` — a string sentinel, not the real value.
    Passed straight through as -1 it would makes a free-calorie "6 Buffalo
    Wings Meal" look like the best protein-per-calorie item on the board.
    Treated as unknown (``None``) here.

NAME DRIFT — the till and `data/db/slim_chickens.json` (Nutritionix-derived)
    disagree in three small, systematic ways, each verified by inspecting
    both sides rather than guessed:

    1. **Plurals** — till "4 Tender Meal" vs booklet "4 Tenders Meal". Left
       alone: `scripts.api.prices`'s own token matcher already folds a
       trailing "s", so this one needs no alias.
    2. **"Crispy" is implicit on the till, explicit in the booklet** — till
       "6 Wings Meal" (the plain wing, as opposed to "6 Buffalo Wings Meal"
       or "6 Honey BBQ Wings Meal", which already carry their flavour word)
       is booklet "6 Crispy Wings Meal"/"6 Crispy Wings". Aliased by
       inserting "Crispy" whenever "Wings" appears with no flavour word
       already in front of it.
    3. **"Solo"/"Side of" wording** — till "3 Wings Solo" and "Side of 3
       Tenders" are the booklet's bare "3 Wings"/"3 Tenders". Only the
       "Solo"/"Side of" forms are stripped, never "Meal" — a meal and its
       solo counterpart are genuinely different prices for a same-count
       item, and stripping "Meal" too would alias the meal's higher price
       onto the solo-item nutrition row.
    4. **Apostrophes** — till "Kid's Tender Meal" vs booklet "Kids Tenders
       Meal". `_normalise` turns an apostrophe into a space ("Kid's" ->
       "Kid" + "s", two tokens), which does not equal "Kids" as one token —
       so an apostrophe-free alias ("Kids Tender Meal") is added rather than
       relying on the shared normaliser.

PRICE BASIS — collection
    Every venue on this platform is branded "Click & Collect" specifically
    (`slim-chickens-click-and-collect` is the brand slug itself), and the
    menu carries one price per product with no delivery/occasion split.

STORE — Edgware Road, W2 2HR
    No Slim Chickens branch sits in Wimbledon; Edgware Road came back
    nearest when the venue search was queried from Wimbledon's coordinates.
"""
from __future__ import annotations

import re

from ..base import session

CHAIN = "slim_chickens"

API = "https://device-gateway.orderpay.com/api"
BRAND_SLUG = "slim-chickens-click-and-collect"

#: Edgware Road, W2 2HR — nearest branch to Wimbledon at adapter-verify time.
DEFAULT_VENUE_ID = "29fd1667-6826-4f0a-be83-9bea3dfcdc88"

#: Wing flavour words that already make "Wings" unambiguous — anything else
#: gets "Crispy" inserted (NAME DRIFT #2).
_WING_FLAVOURS = ("buffalo", "honey bbq", "crispy")


def _get(path: str, **params) -> dict | list:
    s = session()
    r = s.get(f"{API}{path}", params=params or None, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"slim_chickens: HTTP {r.status_code} from {path} "
                           f"{r.text[:300]}")
    return r.json()


def _brand_id(slug: str = BRAND_SLUG) -> str:
    data = _get(f"/1/brands/slug/{slug}")
    brand_id = data.get("id")
    if not brand_id:
        raise RuntimeError(f"slim_chickens: no brand id for slug {slug!r}")
    return brand_id


def find_venues(lat: float, lng: float, brand_id: str | None = None,
                limit: int = 10) -> list[dict]:
    """Nearby Slim Chickens venues, nearest first. See the `lat`/`long` trap."""
    brand_id = brand_id or _brand_id()
    data = _get("/1/venues", lat=lat, long=lng, brandId=brand_id,
               pageNumber=0, pageSize=limit, sortBy="distance", sortOrder="ASC")
    return data.get("venues") or []


def _kcal(raw) -> float | None:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if val >= 0 else None  # "-1" is OrderPay's "not published"


def _names(name: str) -> list[str]:
    """Booklet-style aliases for one priced product. Additive."""
    base = re.sub(r"\s+", " ", (name or "").strip())
    if not base:
        return []
    names = [base]

    # "'" -> nothing (not a space) — "Kid's" must land on "Kids", one token.
    if "'" in base:
        names.append(base.replace("'", ""))

    # The "Slims"/"Slim's" branding is spelled both ways even within one
    # side (the till itself has "Slims Wrap Solo" and "Slim's Wrap Meal");
    # try both spellings rather than picking one.
    for root in list(names):
        if re.search(r"\bslims\b", root, flags=re.I):
            names.append(re.sub(r"\bslims\b", "Slim's", root, flags=re.I))
        if re.search(r"\bslim's\b", root, flags=re.I):
            names.append(re.sub(r"\bslim's\b", "Slims", root, flags=re.I))

    # "Chicken and Bacon Smoked Caesar Wrap" -> also bare "Smoked Caesar
    # Wrap" — the booklet doesn't name the standard filling.
    for root in list(names):
        stripped = re.sub(r"^chicken and bacon\s+", "", root, flags=re.I)
        if stripped.lower() != root.lower():
            names.append(stripped)

    # "Side of 3 Tenders" / "3 Wings Solo" -> "3 Tenders" / "3 Wings", never
    # touching "Meal" (see NAME DRIFT #3).
    for root in list(names):
        stripped = re.sub(r"^side of\s+", "", root, flags=re.I)
        stripped = re.sub(r"\s+solo$", "", stripped, flags=re.I)
        if stripped.lower() != root.lower():
            names.append(stripped)

    # Bare "Wings" (no flavour word already attached) -> "Crispy Wings".
    for root in list(names):
        if re.search(r"\bwings?\b", root, flags=re.I) and not any(
                f in root.lower() for f in _WING_FLAVOURS):
            names.append(re.sub(r"\bwings?\b", "Crispy Wings", root,
                                count=1, flags=re.I))

    # The booklet calls the flat till price "Regular Seasoned Fries".
    for root in list(names):
        if root.lower() == "seasoned fries":
            names.append(f"Regular {root}")

    return names


def fetch_prices(venue_id: str | None = None,
                 lat: float | None = None, lng: float | None = None) -> list[dict]:
    """Priced menu for one Slim Chickens UK venue.

    Give a `venue_id` (a venue UUID from `find_venues`), or a `lat`/`lng` to
    use the nearest branch. All rows are "collection" — see the module
    docstring.
    """
    if venue_id is None and lat is not None and lng is not None:
        near = find_venues(lat, lng, limit=1)
        if not near:
            raise RuntimeError(f"slim_chickens: no venue near {lat},{lng}")
        venue_id = near[0]["id"]
    venue_id = venue_id or DEFAULT_VENUE_ID

    venue = None
    try:
        brand_id = _brand_id()
        for v in find_venues(51.5072, -0.1276, brand_id=brand_id, limit=50):
            if v.get("id") == venue_id:
                venue = v
                break
    except Exception:
        pass  # menu fetch below still works without a label

    sections = _get(f"/1/venues/{venue_id}/menu")
    if not isinstance(sections, list):
        raise RuntimeError(f"slim_chickens: unexpected menu shape for {venue_id}")

    addr = (venue or {}).get("location", {}).get("address", {})
    label = (venue or {}).get("name") or f"Slim Chickens venue {venue_id}"
    postcode = (addr.get("postcode") or "").strip()
    label = f"{label} ({postcode})" if postcode else label

    out: list[dict] = []
    seen: set[str] = set()

    for section in sections:
        for menu_cat in section.get("menuCategories") or []:
            category = menu_cat.get("title") or section.get("title")
            for product in menu_cat.get("products") or []:
                pence = (product.get("price") or {}).get("units")
                if not pence:
                    continue
                kcal = _kcal(product.get("calories"))
                for name in _names(product.get("name")):
                    key = name.strip().lower()
                    if not name.strip() or key in seen:
                        continue
                    seen.add(key)
                    out.append({"name": name.strip(),
                                "price_gbp": round(pence / 100.0, 2),
                                "basis": "collection", "store": label,
                                "category": category, "kcal": kcal})

    if not out:
        raise RuntimeError(
            f"slim_chickens: no priced items for venue {venue_id} — an empty "
            f"menu means the handshake broke, not that the shop is bare")
    return out


if __name__ == "__main__":  # pragma: no cover
    for row in fetch_prices()[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
