"""Krispy Kreme UK — REAL prices from Krispy Kreme's own Magento shop, plus a
DISCLOSED derived per-doughnut price for the nutrition table's single-item
rows this shop never sells individually.

WHICH PLATFORM
    `www.krispykreme.co.uk/shop/...` is a standard Magento 2 storefront
    (Luma-family theme; product markup carries `itemprop="sku"`/`"name"`
    and `data-price-amount` microdata) — prices are server-rendered into
    the category-page HTML with no auth needed. Magento's own `/rest/V1/`
    REST API is *not* usable here (it 503s through every TLS profile tried,
    unlike the HTML pages, which return 200 directly) — this module parses
    the rendered category pages instead, which is still plain HTTP with no
    browser/JS.

TWO DIFFERENT THINGS THIS PROJECT CALLS "THE MENU"
    `data/db/krispy_kreme.json` is Krispy Kreme's *café* menu — one row per
    single doughnut (Original Glazed, Biscoff, ...) and one row per drink
    (lattes, shakes), the thing a customer buys one of. The Magento shop is
    Krispy Kreme's *nationwide delivery/click-and-collect shop* — and it
    sells doughnuts exclusively as boxes (Dozen / 24 Pack / 48 Pack), never
    a single doughnut, and sells no drinks at all. There is no page on this
    platform where "Original Glazed" itself has its own price — checked
    across `/shop/click-collect.html`, `/shop/doughnuts-by-range/*.html`,
    and the personalised/vegan/best-selling range pages.

WHAT THIS MODULE DOES ABOUT IT — real box prices AND a disclosed derived
    per-doughnut tier price, clearly labelled as derived
    Every box product is emitted under its own real name/price
    undecomposed (e.g. "Original Glazed Dozen", £14.99) — these will not
    join to the nutrition table's per-doughnut rows, but they're the
    honest, real prices this platform actually charges.

    Separately — because this project's price column exists specifically to
    support a protein-per-price ranking, and a whole £14.99 dozen simply
    cannot answer "what does one doughnut cost" without division — this
    module ALSO emits a derived per-doughnut "collection" price computed as
    `box_price / box_count` for two pricing TIERS this platform genuinely
    prices uniformly:

    - **Original Glazed tier**: "Original Glazed™ Dozen" (£14.99/12 =
      £1.25). Verified uniform: the Vegan Original Glazed Dozen is priced
      *identically* (£14.99/12) — Krispy Kreme is confirmed pricing this
      tier by doughnut type, not by box variant.
    - **Assorted/specialty tier**: "Favourites Dozen" (£21.99/12 = £1.83,
      also sold as "Choose Your Own Dozen"/"Assorted Dozen" at the same
      £21.99). Verified uniform the same way: "Vegan Selection Dozen" is
      priced identically (£21.99/12) to the non-vegan assorted dozen.
    - **Bites tier**: "Doughnut Bites - 24 box" (£11.99/24, OG bites) and
      "Variety Bites 24 Pack" (£12.99/24, flavoured bites), each doubled
      since the nutrition table's own bites rows are a 2-bite serving
      ("OG Bites (1 serving = 2 bites)").

    This is division, not decomposition — every doughnut in a "Favourites
    Dozen" genuinely is one of the named specialty flavours at one shared
    price, unlike (say) `gdk.py`'s meat/sauce split, where dividing would
    require guessing *which* combination a shopper picked. Still, a
    computed unit price is a materially different kind of fact than a
    literal SKU price, so every derived row's `store` field says so in
    plain language rather than reading like an ordinary till price.

NOT COVERED, HONESTLY
    Minis (no mini-doughnut pack exists on this platform at any price),
    every drink (no drinks are sold here at all — café-only), and
    "Hand Piped Original Glazed" (real name overlap with the OG tier, but
    it's a premium item on the in-café menu with no clear box counterpart —
    left unpriced rather than guessed).

STORE
    Nationwide online shop — no per-branch pricing exists on this platform,
    same as `gails.py`/`paul.py`.
"""
from __future__ import annotations

import html
import re

from ..base import fetch_protected

CHAIN = "krispy_kreme"

_PAGES = [
    "https://www.krispykreme.co.uk/shop/click-collect.html",
    "https://www.krispykreme.co.uk/shop/doughnuts-by-range/vegan.html",
    "https://www.krispykreme.co.uk/shop/doughnuts-by-range/best-selling-doughnuts.html",
    "https://www.krispykreme.co.uk/shop/doughnuts-by-range/personalised.html",
]

_PRODUCT_BLOCK_RE = re.compile(
    r'<li class="\s*item\s*product\s*product-item')
_NAME_RE = re.compile(
    r'itemprop="name">\s*<a class="product-item-link"[^>]*>\s*([^<]+)')
_PRICE_RE = re.compile(r'data-price-amount="([^"]+)"')
_SKU_RE = re.compile(r'itemprop="sku" content="([^"]+)"')

#: Doughnut-flavour nutrition-table names (`data/db/krispy_kreme.json`)
#: priced from the "Original Glazed" box tier (£14.99/dozen) — verified
#: uniform against the Vegan OG Dozen, same price. See module docstring.
_OG_TIER_NAMES = [
    "Original Glazed", "Vegan Original Glazed", "Vegan Original Glazed (NWD only)",
]

#: Priced from the "Favourites"/"Assorted" box tier (£21.99/dozen) —
#: verified uniform against the Vegan Selection Dozen, same price. Every
#: name here is read directly off `data/db/krispy_kreme.json` (this is not
#: a guess at which flavours exist — it's this project's own flavour list).
_ASSORTED_TIER_NAMES = [
    "Chocolate Sprinkles", "Biscoff", "Nutty Chocolatta", "Strawberry Sprinkles",
    "White Marble Chocolatta", "Cookies & Kreme", "Strawberry Sundae",
    "Triple Choc Indulgence", "Salted Caramel Sensation", "Glazed Raspberry",
    "Biscoff Iced", "Double Chocolate Glaze", "Vegan Choc Orange",
    "Brownie Biscuit", "Cookie Crumble", "Choc Duo Ring",
    "Chocolate Strawberry Surprise", "White Chocolate Kreme",
    "Speculoos Sensation", "Choco Caramel Crunch", "Party Sprinkles",
    "Orange Brownie Bliss", "Strawberry Pop",
]

#: Priced from "Personalised Happy Birthday Box Original Glazed Dozen"
#: (£23.95/12) — the personalisation-tier OG price.
_PERSONALISED_OG_TIER_NAMES = ["Personalised OG", "Personalised Original Glazed"]

#: (nutrition name, bites-per-serving) priced from the OG-flavour bites box
#: ("Doughnut Bites - 24 box", £11.99/24).
_OG_BITES_TIER = [("OG Bites (1 serving = 2 bites)", 2)]

#: Priced from the flavoured bites box ("Variety Bites 24 Pack", £12.99/24).
_ASSORTED_BITES_TIER = [
    ("Rainbow Sprinkle Bites (1 serving = 2 bites)", 2),
    ("Milk Chocolate Sprinkle Bites (1 serving = 2 bites)", 2),
    ("Choc & Salted Caramel Bites (1 serving = 2 bites)", 2),
]

_DERIVED_STORE_NOTE = (
    "Krispy Kreme UK online shop — DERIVED per-doughnut price (box price "
    "÷ box count; this platform sells no single doughnuts, see "
    "krispy_kreme.py's module docstring)")
_REAL_STORE_NOTE = ("Krispy Kreme UK online shop (nationwide catalogue "
                    "price — no per-branch pricing exists on this platform)")


def _fetch_products() -> dict[str, tuple[str, float]]:
    """sku -> (name, price_gbp) for every box product across the range pages."""
    out: dict[str, tuple[str, float]] = {}
    for url in _PAGES:
        r = fetch_protected(url)
        if r is None:
            raise RuntimeError(f"krispy_kreme: GET {url} failed (Cloudflare "
                               f"handshake never succeeded through any "
                               f"browser profile)")
        for block in _PRODUCT_BLOCK_RE.split(r.text)[1:]:
            name_m = _NAME_RE.search(block)
            price_m = _PRICE_RE.search(block)
            sku_m = _SKU_RE.search(block)
            if not (name_m and price_m):
                continue
            name = html.unescape(name_m.group(1)).strip()
            price = float(price_m.group(1))
            sku = sku_m.group(1) if sku_m else name.lower()
            out.setdefault(sku, (name, price))
    return out


def _find_price(products: dict[str, tuple[str, float]], *name_fragments: str
                ) -> float | None:
    """First product whose name contains every fragment (case-insensitive)."""
    for name, price in products.values():
        low = name.lower()
        if all(f.lower() in low for f in name_fragments):
            return price
    return None


def fetch_prices() -> list[dict]:
    products = _fetch_products()
    if not products:
        raise RuntimeError("krispy_kreme: no products parsed from any range "
                           "page — the handshake broke, not that the shop "
                           "is bare")

    out: list[dict] = []
    seen: set[str] = set()

    def emit(name: str, price: float, store: str):
        key = name.strip().lower()
        if not name.strip() or key in seen:
            return
        seen.add(key)
        out.append({"name": name.strip(), "price_gbp": round(price, 2),
                   "basis": "collection", "store": store, "category": None})

    # 1. Real box products, undecomposed.
    for name, price in products.values():
        emit(name, price, _REAL_STORE_NOTE)

    # 2. Derived per-doughnut tier prices.
    og_dozen = _find_price(products, "Original Glazed", "Dozen")
    assorted_dozen = (_find_price(products, "Favourites", "Dozen")
                      or _find_price(products, "Assorted", "Dozen"))
    personalised_og_dozen = _find_price(
        products, "Personalised", "Birthday", "Original Glazed", "Dozen")
    og_bites_box = _find_price(products, "Doughnut Bites", "24")
    variety_bites_box = _find_price(products, "Variety Bites", "24")

    if og_dozen:
        per_og = og_dozen / 12.0
        for name in _OG_TIER_NAMES:
            emit(name, per_og, _DERIVED_STORE_NOTE)

    if assorted_dozen:
        per_assorted = assorted_dozen / 12.0
        for name in _ASSORTED_TIER_NAMES:
            emit(name, per_assorted, _DERIVED_STORE_NOTE)

    if personalised_og_dozen:
        per_personalised = personalised_og_dozen / 12.0
        for name in _PERSONALISED_OG_TIER_NAMES:
            emit(name, per_personalised, _DERIVED_STORE_NOTE)

    if og_bites_box:
        per_bite = og_bites_box / 24.0
        for name, count in _OG_BITES_TIER:
            emit(name, per_bite * count, _DERIVED_STORE_NOTE)

    if variety_bites_box:
        per_bite = variety_bites_box / 24.0
        for name, count in _ASSORTED_BITES_TIER:
            emit(name, per_bite * count, _DERIVED_STORE_NOTE)

    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} priced rows")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  {row['name']}")
