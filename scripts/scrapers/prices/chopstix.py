"""Chopstix Noodle Bar UK — REAL prices from Chopstix's own Slerp storefront.

WHICH PLATFORM
    `chopstixnoodles.co.uk`'s "Click & Collect" link goes to
    `chopstixnoodles.slerp.com` — Slerp, a white-label click-and-collect
    ordering SaaS (the same category of platform as `slim_chickens.py`'s
    OrderPay), not Chopstix's own backend. Slerp's storefront is a JS SPA
    that talks to a public GraphQL API at
    `https://mobile.graph.api.slerp.com/v1/graphql` — found by fetching the
    SPA's own JS chunks and grepping for the host (the inline page config
    only advertises the *wrong* path, `.../graphql`, which 404s; the real
    path, `.../v1/graphql`, is compiled into `chunk-CImnQ4tU.js`'s Sentry
    network-allowlist). The endpoint answers plain `requests` with the
    page's own public `x-slerp-api-key` header and no other auth — this is
    the same public key every visitor's browser sends, not a secret.

Handshake
---------
One unauthenticated POST, no discovery/store-lookup step needed:

    ``POST /v1/graphql`` with a Hasura-style `product_variants(where:
    {merchant_id: {_eq: "<id>"}}) { name price vat calorie_data archived_at
    sku }` query. `_MERCHANT_ID` (Chopstix's UUID on this platform) was read
    from the page's own inline `partnerData.id` config.

    `product_variants.price` is the **ex-VAT** price — Slerp's own
    storefront displays `price * (1 + vat/100)`, confirmed by checking that
    108 of 192 active variants land exactly on a round, real-menu-looking
    figure (`£4.99`, `£9.49`, `£12.99`...) only after applying that formula;
    the raw `price` field alone lands on nothing recognisable (e.g. `10.825`
    for a £12.99 box). This module applies the same formula.

    Prices are catalogue-wide, not per-branch — like `gails.py`/`paul.py`,
    Slerp prices once per SKU here with no visible per-store override, so
    there is no branch to name (see STORE below).

SCOPE — a "build your own box" menu vs. a per-serving-size nutrition table
    `data/db/chopstix.json` is Nutritionix-derived and enumerates every base
    (Chow Mein/Egg Fried Rice/Cauli Rice) and topping at five serving sizes
    each (Taster/Small/Regular/Large/Topper Pot). Chopstix's actual ordering
    flow sells a box at ONE size with a topping choice included, plus
    "Extra {Topping}" and "{Topping} Box" as separately priced add-ons/mains
    — there is no priced SKU for "Taster" or "Topper Pot" portions at all,
    and no SKU for a base (Chow Mein etc.) on its own outside a box. This is
    a real menu-model mismatch, not a scraping gap.

NAME DRIFT, VERIFIED BY EXACT KCAL MATCH
    Checked systematically, not assumed: for every topping checked, Slerp's
    "Extra {Topping}" kcal exactly matches the nutrition table's "{Topping}
    - Small" row, and "{Topping} Box" exactly matches "{Topping} - Regular"
    (which is itself kcal-identical to "- Large" in this nutrition table —
    a quirk of the source data, not this module). E.g. Slerp "Extra Salt &
    Pepper Chicken" = 208 kcal = nutrition "Salt & Pepper Chicken - Small"
    (208 kcal); Slerp "Coconut Crave Chicken Box" = 113 kcal = nutrition
    "Coconut Crave Chicken - Regular" (113 kcal) = "...- Large" (113 kcal,
    same figure). `_generate_aliases` applies this pattern generically
    (regex-driven, not a per-topping table) since it held for every topping
    checked. A "NEW" suffix appears on some nutrition rows as literal text
    (not decoration, unlike Slerp's "⭐NEW⭐" stars) — both the plain and
    "... NEW"-suffixed alias are emitted since which toppings currently
    carry it is not discoverable from the Slerp side.

    "Go Large! {Base}" is aliased to "{Base} - Large"; Slerp's "Skinny
    Cauliflower Rice" is separately aliased to the nutrition table's "Cauli
    Rice" (same dish, this project's own shorter name for it).

NOT ALIASED, HONESTLY
    Several Slerp toppings/items (Kung Po Chicken, Hoisin Duck, K-POP BBQ
    Chicken/Wings, Massaman Chicken & Potato Curry, Smoky Seoul Chicken,
    Zesty Lemon Chicken, Salt & Pepper Cauli Bites) have no counterpart
    anywhere in `data/db/chopstix.json` at all — newer menu additions the
    nutrition table hasn't caught up with yet, not a naming mismatch.
    Drink sizes don't line up either: Slerp sells cans/bottles in metric
    (330ml, 500ml) while the nutrition table's cans are in imperial
    (12/16/22 floz) — genuinely different pack sizes, not aliased.

EMOJI/SYMBOL STRIPPING
    Every Slerp product name carries decorative emoji (🥡🌱🍒🇰🇷⭐...) that
    `data/db/chopstix.json` never does — stripped down to ASCII letters,
    digits, and basic punctuation before matching or emitting.

STORE — none; catalogue-wide pricing, not a branch till
    Like `gails.py`/`paul.py`: Slerp prices once per SKU platform-wide, with
    no per-branch override visible anywhere in this schema.
"""
from __future__ import annotations

import re
import unicodedata

from ..base import session

CHAIN = "chopstix"

GRAPHQL = "https://mobile.graph.api.slerp.com/v1/graphql"
#: The public key the Slerp storefront's own browser bundle sends — not a
#: secret, the same value every visitor's page load uses.
API_KEY = "1a376c369a1d2cf6"
#: Chopstix's merchant UUID on this platform, read from the storefront
#: page's own inline `partnerData.id` config.
_MERCHANT_ID = "4f0e037f-4faf-4dd8-8608-89114c2afd93"

_QUERY = """
query {
  product_variants(where: {merchant_id: {_eq: "%s"}}, limit: 500) {
    name
    price
    vat
    calorie_data
    archived_at
  }
}
""" % _MERCHANT_ID

#: Slerp's own base name (cleaned, lowercased) -> the nutrition table's name
#: for the same dish, where it differs by more than the Extra/Box pattern
#: `_generate_aliases` already handles.
_BASE_RENAMES = {
    "skinny cauliflower rice": "Cauli Rice",
    "vegetable chow mein (noodles)": "Vegetable Chow Mein",
    "egg-fried rice": "Egg Fried Rice",
    # The "Box" SKU carries a marketing adjective the "Extra" SKU (and the
    # nutrition table) doesn't.
    "spicy coconut crave chicken": "Coconut Crave Chicken",
    # "sweet n sour" (Box SKU) vs "sweet & sour" (nutrition table).
    "no chick'n sweet n sour": "No Chick'n Sweet & Sour",
}

_EXTRA_RE = re.compile(r"^extra\s+", re.I)
_BOX_RE = re.compile(r"\s+box$", re.I)
_GO_LARGE_RE = re.compile(r"^go large!\s*", re.I)


def _clean_name(raw: str) -> str:
    """Strip emoji/decorative symbols down to plain ASCII text."""
    # Typographic apostrophe/dash -> ASCII, kept rather than dropped.
    text = raw.replace("’", "'").replace("‘", "'") \
        .replace("–", "-").replace("—", "-")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text
                  if ch.isascii() and (ch.isalnum() or ch in " '&-(),./"))
    return re.sub(r"\s+", " ", text).strip()


def _generate_aliases(clean: str) -> list[str]:
    """"Extra Salt & Pepper Chicken" -> ["Salt & Pepper Chicken - Small",
    "Salt & Pepper Chicken - Small NEW"], etc. See the module docstring's
    NAME DRIFT section for how this pattern was verified.
    """
    out: list[str] = []

    m = _EXTRA_RE.match(clean)
    if m:
        topping = clean[m.end():].strip()
        renamed = _BASE_RENAMES.get(topping.lower(), topping)
        out.append(f"{renamed} - Small")
        out.append(f"{renamed} - Small NEW")

    m = _BOX_RE.search(clean)
    if m:
        topping = clean[:m.start()].strip()
        renamed = _BASE_RENAMES.get(topping.lower(), topping)
        out.append(f"{renamed} - Regular")
        out.append(f"{renamed} - Regular NEW")
        out.append(f"{renamed} - Large")
        out.append(f"{renamed} - Large NEW")

    m = _GO_LARGE_RE.match(clean)
    if m:
        base = clean[m.end():].strip()
        renamed = _BASE_RENAMES.get(base.lower(), base)
        out.append(f"{renamed} - Large")

    return out


def fetch_prices() -> list[dict]:
    """Chopstix UK's priced Slerp catalogue. No store parameter — see the
    module docstring's STORE section."""
    s = session()
    r = s.post(GRAPHQL, json={"query": _QUERY}, timeout=30,
              headers={"x-slerp-api-key": API_KEY,
                       "Content-Type": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"chopstix: HTTP {r.status_code} from Slerp GraphQL")
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"chopstix: GraphQL error: "
                           f"{data['errors'][0].get('message')}")
    variants = (data.get("data") or {}).get("product_variants") or []
    active = [v for v in variants if not v.get("archived_at")
             and v.get("price") is not None and v.get("name")]
    if not active:
        raise RuntimeError("chopstix: no active product_variants for "
                           "Chopstix's merchant id — the handshake broke, "
                           "not that the shop is bare")

    out: list[dict] = []
    seen: set[str] = set()
    for v in active:
        clean = _clean_name(v["name"])
        if not clean:
            continue
        vat = v.get("vat") or 0.0
        price_gbp = round(float(v["price"]) * (1 + vat / 100.0), 2)
        cal = (v.get("calorie_data") or {}).get("calories_per_serving")

        names = [clean] + _generate_aliases(clean)
        for row_name in names:
            key = row_name.lower()
            if not row_name or key in seen:
                continue
            seen.add(key)
            out.append({
                "name": row_name,
                "price_gbp": price_gbp,
                "basis": "collection",
                "store": "Chopstix online shop (nationwide catalogue price "
                        "— no per-branch pricing exists on this platform)",
                "category": None,
                "kcal": float(cal) if cal is not None else None,
            })

    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} priced rows")
    for row in rows[:30]:
        print(f"{row['price_gbp']:>7.2f}  {row['name']}")
