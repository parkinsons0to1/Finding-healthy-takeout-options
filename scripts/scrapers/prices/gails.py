"""GAIL's Bakery UK — REAL prices from GAIL's own Shopify storefront.

WHICH PLATFORM
    `gails.com` is a full Shopify store (theme assets under `/cdn/shop/t/...`,
    a standard `/cart` + `/checkout`), not a marketing site with an
    off-platform "Order Now" link — GAIL's sells its café menu (sandwiches,
    pastries, salads, breakfast items, catering trays) for click & collect
    and local London delivery directly off this domain, alongside its
    separate nationwide bread-shipping business. Every product's page shows
    a "Collection" accordion (available everywhere) and a postcode-gated
    "Local delivery" accordion (London zones only, verified by inspecting
    `window.validPostcodes` on a product page) — but Shopify prices a
    product once per variant, with no separate collection/delivery figure to
    compare, so this module has nothing to measure a channel split against
    (see PRICE BASIS below).

    Every Shopify storefront exposes its full catalogue at `/products.json`
    with no auth of any kind — plain `requests` gets a 200 directly, no
    `curl_cffi`/TLS-impersonation needed (checked: gails.com is not behind
    the Cloudflare-fingerprint gate Papa John's/GDK sit behind).

Handshake
---------
    ``GET https://gails.com/products.json?limit=250&page={n}`` — paginate
    until a page returns an empty ``products`` array (250/page maxes out at
    2 pages, ~262 products at verify time). Each product carries
    ``product_type`` (category), and each of its ``variants[]`` a ``price``
    (string, GBP, already decimal) and a ``sku``.

THE SKU IS THE JOIN KEY — not a guess, verified exhaustively
    GAIL's runs one internal product database: the same numeric SKU used to
    key `data/db/gails.json` (this project's nutrition table, scraped from
    `window.allergenProducts` on the same site) is the Shopify variant
    `sku` too. Comparing every nutrition `item_id` against every Shopify
    variant `sku` at verify time found 144 exact SKU matches out of 211
    nutrition rows (68%) — of those 144, 46 already carry byte-identical
    names on both sides and 98 differ only cosmetically (GAIL's own
    ampersand/comma/size-suffix drift between its two internal feeds, e.g.
    Shopify "Ham, Cheddar Cheese & Leek Quiche" vs. nutrition-table "Ham,
    Cheese + Leek Quiche" — same SKU, same product, different copywriter).
    `_SKU_VERIFIED_ALIASES` below is that exact 98-pair table, so every
    aliased row is a same-SKU fact, not a fuzzy string guess.

WHY 67 NUTRITION ROWS HAVE NO PRICE HERE, HONESTLY
    The 67 unmatched nutrition rows are overwhelmingly *made-to-order café
    items with no independent SKU on the shippable-goods shelf* — "Baked
    Eggs", "Oat Milk Porridge", "Extra Bacon", "Gails Toast with Butter",
    single condiments ("Clotted Cream", "Tomato Relish"). GAIL's Shopify
    catalogue sells *packaged/boxed* products (sandwiches, pastries, bread,
    catering trays) that a courier or a collection order can physically
    hand over; a bare "Extra Bacon" add-on to a cooked breakfast isn't one
    of those. This is a real scope boundary of the online shop, not a
    scraping failure — confirmed by literally searching gails.com for each
    missing name and finding no product page.

PRICE BASIS — "collection"
    Every GAIL's product page shows a "Collection" accordion before the
    postcode-gated "Local delivery" one, and Shopify has exactly one price
    per variant with no delivery/collection split visible anywhere in the
    product JSON — so there is nothing here to measure a delivery uplift
    against (unlike Nando's/GDK, where both figures are visible side by
    side). Labelled "collection" to match this project's convention for a
    single-price catalogue (`gdk.py`, `wimpy.py`).

STORE — none; this is genuinely a national online-shop price, not a branch
    Unlike every Just Eat-backed adapter in this directory, GAIL's own
    storefront does not ask which café you're near before pricing — the
    catalogue price is the same regardless of which valid London postcode
    (or nationwide shipping address) is entered. Labelling this "GAIL's —
    Wimbledon" or similar would fabricate a store-level precision the site
    itself doesn't have; the store field says so plainly instead.
"""
from __future__ import annotations

import re

from ..base import session

CHAIN = "gails"

PRODUCTS_JSON = "https://gails.com/products.json"

#: product_type values that are not food/drink (skipped outright).
_NON_FOOD_TYPES = {"gift cards", "digital gift cards", "cookbook", "non food",
                   "location"}

#: Shopify product title (verbatim) -> `data/db/gails.json` nutrition-row
#: name for the SAME numeric SKU. Every pairing here shares one SKU between
#: GAIL's own Shopify catalogue and its nutrition feed — see the module
#: docstring's "THE SKU IS THE JOIN KEY" section for how this was verified.
_SKU_VERIFIED_ALIASES = {
    '10 Chocolate & Tahini Bites': '10 Chocolate And Tahini Bites',
    '10 Smoked Chicken Caesar Club Sandwich Halves': '10 Chicken Caesar Club Halves',
    '12 Aubergine, Crunchy Slaw & Herbs Sandwich Halves': '12 Charred Aubergine Halves',
    '12 Harissa Chicken Sandwich Halves': '12 Harissa Chicken Halves',
    '12 Mini Avocado Sandwiches': '12 Mini Avocado Challah',
    '12 Mini Croissants': 'Mini Croissant Box',
    '12 Mini Pain Aux Raisins': 'Mini Pain Aux Raisins Box',
    '12 Mini Salami & Cornichons': '12 Mini Salami',
    '12 Mini Sausage Rolls': '12 Mini Sausage Roll',
    '12 Mini Smoked Salmon Sandwiches': '12 Mini Salmon',
    '12 Mini Spinach Rolls': '12 Mini Spinach Roll',
    '12 Mozzarella & Pesto Halves': '12 Mozzarella + Pesto halves',
    '4 Pistachio Lemon & Rose Cakes': '4 Pistachio Rose Cakes',
    '5 Strawberry & Ricotta Cakes': '5 Strawb Ricotta Cakes',
    '6 Almond Croissants': '6 Almond Croissant',
    '6 Berry Brioches': 'x6 Mixed Berry Brioche',
    '6 Blueberry & Vanilla Custard Brioches': '6 Blueberry Brioche',
    '6 Cheese, Tomato & Basil Savoury Buns': 'X6 Tomato Brioche Box',
    '6 Chocolate & Almond Croissants': '6 Choc Almond Croissant',
    '6 Filled Buns': '6x Passionfruit Filled Buns',
    '6 Flourless Chocolate & Extra Virgin Olive Oil Mousse Cakes': 'X6 Chocolate EVVO Mousse Cake',
    '6 Ham & Cheese Croissants': '6 Ham Croissant',
    '6 Ham, Cheese & Pickles': 'x6 Ham, Cheese + Pickle box',
    '6 Pain au Chocolat': '6 Pain Au Choc',
    '6 Pain aux Raisins': 'Pain Aux Raisins X6',
    '6 Parmesan Chicken Sandwiches': '6 Parmesan Chicken',
    '6 Pistachio & Chocolate Croissants': '6x Pistachio Croissant',
    'Afternoon Tea (serves 4)': 'Afternoon Tea Hamper(Serves 4)',
    'Apple & Blackcurrant Overnight Oats': 'Blackcurrant Overnight Oats',
    'Aubergine, Crunchy Slaw & Herbs': 'Aubergine+Slaw Sandwich',
    'Babka Bun': 'Chocolate Babka Bun',
    'Baguette 245g': 'Baguette',
    'Barley, Chocolate & Hazelnut Cookie': 'Barley, Choc + Hazelnut Cookie',
    "Beetroot, Lentil & Goat's Cheese with Toasted Hazelnuts": 'Beetroot And Goats Cheese Salad',
    'Berry Brioche': 'Mixed Berry Brioche',
    'Blueberry & Vanilla Custard Brioche': 'Blueberry Brioche',
    'Breakfast Bacon & Egg Slider': 'Bacon Egg Slider',
    'Bruern Farms Sourdough 750g': 'Bruern Farms Sourdough',
    'Carrot Cake': 'Carrot Cake + Pecan Crunch',
    'Cheddar & Chive Drop Scone': 'Cheddar And Chive Drop Scone',
    'Cheese, Tomato & Basil Savoury Bun': 'Tomato Brioche',
    'Chicken & Charred Corn Salad': 'Chicken+ Charred Corn Salad',
    'Chicken, Tarragon & Ham Hand Pie': 'Chicken + Ham Hand Pie',
    'Chocolate & Almond Croissant': 'Chocolate And Almond Croissant',
    'Chocolate & Tahini Bite': 'Chocolate And Tahini Bite',
    'Chocolate and Hazelnut Biscotti': 'Chocolate + Hazelnut Biscotti',
    'Classic Fruit & Nut Granola 400g': 'GAILs Fruit + Nut Granola',
    'Crustless Cheddar, Potato & Caramelised Onion Pie': 'Crustless Potato Pie',
    'Filled Bun': 'Passionfruit Filled Bun',
    'Filter Coffee Box': 'Filter Delivery Box',
    'Flourless Chocolate & Extra Virgin Olive Oil Mousse Cake': 'Chocolate EVOO Mousse Cake',
    "GAIL's Sourdough 2kg": 'GAILs Sourdough 2kg',
    "GAIL's Sourdough 650g": 'GAILs Sourdough',
    'Ginger & Treacle Loaf Cake': 'Ginger Loaf Cake Packed',
    'Gluten-Free Sourdough 350g': 'Gluten-Free Sourdough',
    'Good Earth Sourdough 1kg': 'Good Earth Loaf',
    'Greek Yoghurt with Blueberry and Blackcurrant Compote': 'Blueberry Yoghurt',
    'Half Smoked Chicken Caesar Club': 'Chicken Caesar Club - Half',
    'Ham & Cheese Croissant': 'Ham And Cheese Croissant',
    'Ham, Cheddar Cheese & Leek Quiche': 'Ham, Cheese + Leek Quiche',
    'Ham, Cheese & Pickle': 'Ham, Cheese + Pickle',
    'Hazelnut & Chocolate Spread': 'Hazelnut And Chocolate Spread',
    'Hazelnut and Walnut Sourdough 500g': 'Hazelnut and Walnut Sourdough',
    'Heritage Grain Crispbreads': 'Heritage Wheat Crispbread',
    'Mango & Passionfruit Chia Pot': 'Mango And Passionfruit Chia Pot',
    'Maple & Pecan Scone': 'Maple + Pecan Drop Scone',
    'Mini Avocado and Chickpea': 'Avocado + Chickpea Challah',
    'Mini Salami & Cornichon': 'Mini Salami On A Cream Bun',
    'Mini Smoked Salmon & Avocado Yoghurt': 'Salmon And Avocado Yoghurt Roll',
    'Mixed Olive Sourdough 300g': 'Mixed Olive Sourdough',
    'Mozzarella & Pesto Sandwich': 'Mozzarella and Pesto Sandwich',
    'Oat, Pecan & Cranberry Cookie': 'Oat, Pecan + Cranberry Cookie',
    'Organic Raspberry & Rose Jam': 'Raspberry And Rose Jam',
    'Parmesan Chicken on a Cream Bun': 'Parmesan Chicken Sandwich',
    'Pecan & Cinnamon Crumb Cake': 'Pecan Crumb Cake',
    'Pistachio & Chocolate Croissant': 'Pistachio Chocolate Croissant',
    'Pistachio & Sour Cherry Biscotti': 'Pistachio + Cherry Biscotti',
    'Pistachio Financiers': 'Pistachio Financier',
    'Pistachio, Lemon & Rose Cake': 'Pistachio, Lemon And Rose Cake',
    'Potato & Rosemary Sourdough 650g': 'Potato Rosemary Sourdough 650G',
    'Rapscallion Ginja Ninja Can': 'Rapscallion Ginja Ninja',
    'Raspberry & Almond Overnight Oats': 'Rasp + Almond Overnight Oats',
    'Roasted Strawberry, Pistachio & Quinoa Pot': 'Roasted Straw,Pistachio+Quinoa',
    'Roasted Sweet Potato & Freekeh Salad': 'Freekeh And Sweet Potato Salad',
    'Rye & Barley Sourdough 860g': 'Rye + Barley Sourdough',
    'San Francisco Sourdough 650g': 'San Francisco Sourdough',
    'Sea Salt Caramel, Banana & Pecan Cake': 'Caramel, Banana And Pecan Cake',
    'Seeded Sourdough 650g': 'Seeded Sourdough',
    'Sesame & Cardamom Morning Bun': 'Sesame + Cardamom Bun',
    "Smoked Salmon Bagel, GAIL's Schmear, Pickled Pink Onions": 'Smoked Salmon Bagel',
    'Sour Cherry and Chocolate Scone': 'Cherry + Chocolate scone',
    'Spelt, Cauliflower & Ferments Salad': 'Spelt And Ferments Salad',
    'Spinach & Feta Roll': 'Spinach And Feta Roll',
    'Strawberry & Ricotta Cake': 'Strawberry + Ricotta Cake',
    'Summer Vegetable & Charred Aubergine Salad': 'Summer Veg+Aubergine Salad',
    'Toasted Coconut, Rye & Maple Granola 350g': 'Coconut + Maple Granola',
    'Vanilla Shortbread With Heritage Grain': 'Vanilla Shortbread w Heritage',
    'Waste-Less Sourdough 750g': 'Waste-Less Sourdough',
}
#: lowercased for O(1) lookup at emit time.
_ALIASES_LC = {k.lower(): v for k, v in _SKU_VERIFIED_ALIASES.items()}


def _get_products() -> list[dict]:
    s = session()
    out: list[dict] = []
    for page in range(1, 6):  # 250/page; catalogue is ~260 products (2 pages)
        r = s.get(PRODUCTS_JSON, params={"limit": 250, "page": page}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"gails: HTTP {r.status_code} on products.json "
                               f"page {page}")
        products = (r.json() or {}).get("products") or []
        if not products:
            break
        out.extend(products)
    if not out:
        raise RuntimeError("gails: products.json returned no products at all — "
                           "an empty catalogue means the handshake broke, not "
                           "that the shop is bare")
    return out


def fetch_prices() -> list[dict]:
    """Priced GAIL's UK catalogue, straight off gails.com's own Shopify feed.

    No store parameter: see the module docstring's STORE section for why —
    GAIL's own storefront prices identically regardless of postcode/branch.
    """
    products = _get_products()

    out: list[dict] = []
    seen: set[str] = set()
    for product in products:
        ptype = (product.get("product_type") or "").strip()
        if ptype.lower() in _NON_FOOD_TYPES:
            continue
        title = re.sub(r"\s+", " ", (product.get("title") or "").strip())
        if not title:
            continue
        for variant in product.get("variants") or []:
            sku = variant.get("sku") or ""
            if "__" in sku:
                continue  # a multi-option combo SKU (e.g. milk add-ons), not a plain product price
            price = variant.get("price")
            if price is None:
                continue
            try:
                price_gbp = round(float(price), 2)
            except (TypeError, ValueError):
                continue

            # A priced variant with its own option name (e.g. Gift Card
            # "£20") gets that folded into the row name; a Default Title
            # variant just uses the product title. "None / None" (and other
            # all-"None" combinations) is Shopify's placeholder for
            # "no option chosen" on a product with unused option slots
            # (e.g. Filter Coffee Box's milk add-on options) — not real
            # distinguishing text, so it is treated the same as no title.
            vtitle = (variant.get("title") or "").strip()
            is_placeholder = vtitle == "" or vtitle == "Default Title" or \
                re.fullmatch(r"(?:none\s*/\s*)*none", vtitle, flags=re.I)
            name = title if is_placeholder else f"{title} {vtitle}"

            names = [name]
            alias = _ALIASES_LC.get(name.lower())
            if alias:
                names.append(alias)

            for row_name in names:
                key = row_name.strip().lower()
                if not row_name.strip() or key in seen:
                    continue
                seen.add(key)
                out.append({
                    "name": row_name.strip(),
                    "price_gbp": price_gbp,
                    "basis": "collection",
                    "store": "GAIL's online shop (nationwide catalogue price — "
                            "no per-branch pricing exists on this platform)",
                    "category": ptype or None,
                })

    if not out:
        raise RuntimeError("gails: no priced food/drink items survived — the "
                           "catalogue shape or product_type taxonomy has moved")
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} priced rows")
    for row in rows[:25]:
        print(f"{row['price_gbp']:>7.2f}  [{row['category']}] {row['name']}")
