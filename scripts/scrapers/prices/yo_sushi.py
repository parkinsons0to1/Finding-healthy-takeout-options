"""YO! Sushi UK — REAL per-store prices from YO!'s Just Eat storefront.

WHICH BUSINESS
    `yosushi.com/orderonline` hands off to four places at once:
    `deliveroo.co.uk/brands/yo`, `www.ubereats.com/gb/brand/yo`,
    `www.just-eat.co.uk/takeaway/brands/yo-sushi`, and a first-party
    ordering app at `order.yosushi.com`. That app is a genuine YO! product —
    but it is a heavy client-rendered single-spa micro-frontend built on the
    Vita Mojo ordering platform (confirmed from its webpack chunk names,
    `webpack_container_remote_vmos2_{kiosk,storeSelection,welcome}` — "vmos2"
    is Vita Mojo's own internal name for its order system) with no
    discoverable static JSON API: `api.vmos.io` resolves but only serves the
    same JS shell, and every plausible REST path tried
    (`/api/config`, `/api/v1/config`, `/config.json`) returns the SPA's
    `index.html`, not data. Reaching it would need a real browser to run the
    app's JS and observe its actual XHR calls, which is out of scope here
    (no Playwright/browser automation). So, like every other Just-Eat-only
    chain in this project, the per-branch priced menu here is read from
    YO!'s own storefront on Just Eat (`www.just-eat.co.uk`) instead —
    public, no account — and is labelled as a Just Eat price throughout,
    never implied to be a price YO! publishes itself.

TRAP — a postcode search near this project's usual south-London defaults
       does not surface YO! Sushi restaurants at all, but they exist
    Just Eat's discovery-by-postcode API only returns nearby listings, and
    no full-service "YO! Sushi" restaurant is close enough to Sutton/
    Wimbledon/Victoria to appear in that radius — only the much smaller
    "YO! Tesco Kiosk"/"YO! sushi counter" grab-and-go format shows up (that
    is `data/db/yo_to_go.json`'s chain, priced separately in `yo_to_go.py`,
    not this one). The full restaurant format is real and IS on Just Eat —
    confirmed via YO!'s own Just Eat brand page
    (`www.just-eat.co.uk/takeaway/brands/yo-sushi`), which lists dozens of
    branches nationwide by slug (`restaurants-yo-sushi-{town}`). This module
    uses one of those slugs directly rather than concluding from an empty
    postcode search that YO! Sushi isn't crackable.

Handshake
---------
Identical three-step shape to `subway.py`; see that module for the full
trace of how each URL was found. Every request goes through
`scripts.scrapers.base.fetch_protected` (Cloudflare sits in front of both
the site and its API host; curl_cffi's safari profile gets through).

1. Store discovery here is the brand page, not the by-postcode API (see the
   trap above): ``GET https://www.just-eat.co.uk/takeaway/brands/yo-sushi``
   — scrape `restaurants-{slug}` links.
2. ``GET https://www.just-eat.co.uk/restaurants-{slug}/menu`` — parse
   `__NEXT_DATA__`; `clientConfig.jeRestaurantCdnUrls.uk` is the menu-CDN
   base (read live, not pinned), `...cdn.restaurant.itemsUrl` is the
   catalogue filename.
3. ``GET {cdnBase}/{itemsUrl}`` — the priced catalogue.

NOT A TRAP HERE — no channel split, no DealOnly stubs
    YO! - Kingston upon Thames lists a single `delivery`-only menu group,
    and all 87 items checked are `Type: "menuitem"`, `DealOnly: false` — no
    Subway-style channel duplication and no Chipotle-style deal-builder
    stubs to filter.

NAME DRIFT — sixteen pairs confirmed by exact calorie match, the same
    method `subway.py` uses
    The nutrition PDF (`data/db/yo_sushi.json`, sourced from YO!'s Tenkites
    allergen menu) and this branch's Just Eat catalogue use different
    vocabulary for the same dishes: "Donburi" (PDF) is "rice bowl" (JE) —
    "Beef/Chicken/Pulled Shiitake Teriyaki Donburi" and "Korean Fried
    Chicken Donburi" all match their "… rice bowl" JE counterparts kcal for
    kcal (981/714/869/1059); "Fried Rice" (PDF) is plain "rice" (JE) for the
    smaller portions ("Chicken Bulgogi/Shiitake Teriyaki/Salmon Teriyaki
    Fried Rice" = "… rice", 409/460/441 exactly); "Noodles" (PDF) is "udon
    noodles" (JE) (339/390/317 exactly, including "Prawn Noodles" = "prawn
    teriyaki udon noodles" — the JE name adds "teriyaki" the PDF drops);
    "Korean/Japanese Fried Chicken" (PDF) adds "style" on JE (380/344
    exactly); "Sesame Tender Stem Broccoli" (PDF, two words) = "sesame
    tenderstem broccoli" (JE, one word, 42 kcal exactly); "Veggie Inari
    Taco" (PDF) = "vegetable inari taco" (JE, 143 exactly); "Soy Sauce" (PDF,
    11 kcal) = bare "soy" (JE, 11 kcal); "Pickled Ginger" (PDF, 2 kcal) =
    bare "ginger" (JE, 2 kcal). Every alias here is a same-kcal pair, not a
    guess from similar-looking words.

NOT MATCHED, and correctly so — Just Eat's sushi rolls are twice the
    nutrition PDF's portion
    "crunchy cali roll 8pc" (JE, 617 kcal) is almost exactly double the
    PDF's "Crunchy California Roll" (309 kcal); the same near-exact-double
    pattern holds for "YO! roll 8pc"/"Yo Roll" (411 vs 205), "salmon dragon
    roll 8pc"/"Salmon Dragon Roll" (486 vs 243), "yasai roll 8pc"/"Yasai
    Roll" (383 vs 191) and "spicy chicken katsu roll 8pc"/"Spicy Chicken
    Katsu Roll" (360 vs 180) — Just Eat sells the full 8-piece roll where
    the PDF's row is a half portion (or vice versa), and this module does
    not invent a half-price for a product no one can actually buy at that
    price. "Chocolate Little Moons Mochi" (256 kcal) and "Strawberry
    Cheesecake Little Moons Mochi" (194 kcal) were checked against every JE
    mochi flavour and none is a close enough kcal match to be confident
    they're the same product (closest is 228/186, off by more than the
    recipe-drift margin used elsewhere), so both are left unmatched rather
    than guessed. A large share of the PDF (ramen, bao, hand rolls, katsu
    bao, several "Bowl'd"-style items) has no Just Eat listing at this
    branch at all.

PRICE BASIS — delivery, from YO!'s Just Eat storefront
    Every row is labelled "delivery" — the only service type this branch
    lists on Just Eat. This is a real per-branch price a customer pays
    today, but it is YO!'s price on a third-party platform, not necessarily
    the in-restaurant menu price; no channel for that comparison exists
    online (see `subway.py` for the identical caveat).

PER STORE
    YO! - Kingston upon Thames is the default — the nearest full-service
    YO! Sushi restaurant to this project's other south-London defaults
    listed on YO!'s Just Eat brand page (postcode search near Sutton
    surfaces no YO! Sushi restaurant at all — see the trap above).
"""
from __future__ import annotations

import json
import re

from ..base import fetch_protected

CHAIN = "yo_sushi"

BRAND_PAGE = "https://www.just-eat.co.uk/takeaway/brands/yo-sushi"
MENU_PAGE = "https://www.just-eat.co.uk/restaurants-{slug}/menu"
JE_HOME = "https://www.just-eat.co.uk/"

#: YO! - Kingston upon Thames — nearest full-service YO! Sushi to this
#: project's other south-London defaults on Just Eat's brand page.
DEFAULT_STORE_SLUG = "yo-sushi-kingston-upon-thames"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENERGY_RE = re.compile(r'([\d.]+)\s*kcal', re.I)
_SLUG_RE = re.compile(r'restaurants-([a-z0-9-]*yo[a-z0-9-]*)')

#: Just Eat product name (lowercased) -> the nutrition PDF's spelling of the
#: same dish (`data/db/yo_sushi.json`). Every pairing verified by an exact
#: calorie match — see the NAME DRIFT section in the module docstring.
_PDF_ALIASES = {
    "beef teriyaki rice bowl": "Beef Teriyaki Donburi",
    "chicken teriyaki rice bowl": "Chicken Teriyaki Donburi",
    "shiitake teriyaki rice bowl": "Pulled Shiitake Teriyaki Donburi",
    "korean fried chicken rice bowl": "Korean Fried Chicken Donburi",
    "chicken bulgogi rice": "Chicken Bulgogi Fried Rice",
    "shiitake teriyaki rice": "Shiitake Teriyaki Fried Rice",
    "salmon teriyaki rice": "Salmon Teriyaki Fried Rice",
    "chicken bulgogi udon noodles": "Chicken Bulgogi Noodles",
    "shiitake teriyaki udon noodles": "Shiitake Teriyaki Noodles",
    "prawn teriyaki udon noodles": "Prawn Noodles",
    "korean style fried chicken": "Korean Fried Chicken",
    "japanese style fried chicken": "Japanese Fried Chicken",
    "sesame tenderstem broccoli": "Sesame Tender Stem Broccoli",
    "vegetable inari taco": "Veggie Inari Taco",
    "soy": "Soy Sauce",
    "ginger": "Pickled Ginger",
}


def _get(url: str, referer: str = JE_HOME):
    r = fetch_protected(url, referer=referer)
    if r is None:
        raise RuntimeError(f"yo_sushi: GET {url} failed (Cloudflare "
                           f"handshake never succeeded through any browser "
                           f"profile)")
    return r


def find_stores() -> list[str]:
    """YO! Sushi restaurant slugs listed on Just Eat's brand page (there is
    no usable by-postcode search near this project's defaults — see the
    module docstring's trap)."""
    r = _get(BRAND_PAGE)
    if r.status_code != 200:
        raise RuntimeError(f"yo_sushi: brand page HTTP {r.status_code}")
    slugs = sorted(set(_SLUG_RE.findall(r.text)))
    return [s for s in slugs if "sushi" in s or "yo---" in s]


def _menu_page(slug: str) -> dict:
    r = _get(MENU_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"yo_sushi: no restaurant page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"yo_sushi: menu page HTTP {r.status_code} for "
                           f"{slug!r}")
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"yo_sushi: __NEXT_DATA__ not found for {slug!r} "
                           f"— the page template changed")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"yo_sushi: __NEXT_DATA__ was not valid JSON "
                           f"({exc})") from None


def _cdn_base(next_data: dict) -> str:
    urls = ((next_data.get("props") or {}).get("appProps") or {}).get(
        "clientConfig", {}).get("jeRestaurantCdnUrls") or {}
    base = urls.get("uk")
    if not base:
        raise RuntimeError("yo_sushi: no UK menu-CDN base in __NEXT_DATA__ "
                           "— clientConfig shape has moved")
    return base.rstrip("/")


def _restaurant_node(next_data: dict) -> dict:
    try:
        return (next_data["props"]["appProps"]["preloadedState"]["menu"]
                ["restaurant"]["cdn"]["restaurant"])
    except (KeyError, TypeError):
        raise RuntimeError(
            "yo_sushi: preloadedState.menu.restaurant.cdn.restaurant "
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


def fetch_prices(store_id: str | None = None,
                 basis: str = "delivery") -> list[dict]:
    """Priced Just Eat menu for one YO! Sushi branch.

    Give a `store_id` (the Just Eat slug, e.g.
    "yo-sushi-kingston-upon-thames") to use a different branch — see
    `find_stores()` for the full list on Just Eat's brand page. Only
    "delivery" is offered — the default branch lists no collection service
    type on Just Eat.
    """
    if basis != "delivery":
        raise ValueError(f"yo_sushi: unknown basis {basis!r} (only "
                         f"'delivery' — this branch's Just Eat storefront "
                         f"has no collection service type)")

    slug = store_id or DEFAULT_STORE_SLUG

    next_data = _menu_page(slug)
    cdn_base = _cdn_base(next_data)
    restaurant = _restaurant_node(next_data)
    items_url = restaurant.get("itemsUrl")
    if not items_url:
        raise RuntimeError(f"yo_sushi: no itemsUrl for {slug!r}")
    categories = _category_map(restaurant)

    r = _get(f"{cdn_base}/{items_url}")
    if r.status_code != 200:
        raise RuntimeError(f"yo_sushi: items JSON HTTP {r.status_code} for "
                           f"{slug!r}")
    try:
        payload = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"yo_sushi: items JSON for {slug!r} was not JSON "
                           f"({exc})") from None
    raw_items = payload.get("Items") or []
    if not raw_items:
        raise RuntimeError(f"yo_sushi: items JSON for {slug!r} came back "
                           f"empty")

    info = restaurant.get("restaurantInfo") or {}
    name = (info.get("name") or f"YO! Sushi ({slug})").strip()
    label = name

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        item_id = item.get("Id")
        category = categories.get(item_id)
        product_name = (item.get("Name") or "").strip()
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
            for out_name in [product_name, _PDF_ALIASES.get(key)]:
                if not out_name:
                    continue
                out.append({
                    "name": out_name,
                    "price_gbp": round(float(price), 2),
                    "basis": "delivery",
                    "store": label,
                    "category": category,
                    "kcal": kcal,
                })

    if not out:
        raise RuntimeError(
            f"yo_sushi: {len(raw_items)} items for {label} but none "
            f"survived the DealOnly filter — the catalogue shape has "
            f"changed")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']}")
