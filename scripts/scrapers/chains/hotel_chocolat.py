"""Hotel Chocolat — Salesforce Commerce (SCAPI) product catalogue, per 100 g.

Discovery
---------
`hotelchocolat.com/uk` is a Salesforce PWA Kit (Managed Runtime) storefront.
The `/uk/i/allergens-nutritional-information.html` page renders to literally
one line of text ("Home / Nutritional Page") — everything is client-side — and
there is no nutrition PDF anywhere on the site. The numbers live as SFCC
custom attributes on each *variant* product:

    c_nutritionEnergyKcal, c_nutritionEnergyKJ, c_nutritionProtein,
    c_nutritionFat, c_nutritionSaturatedFat, c_nutritionCarbohydrates,
    c_nutritionSugars, c_nutritionFibre, c_nutritionSalt, c_ingredients

Found by pulling `/mobify/bundle/<n>/7334.js` (the product-detail chunk) and
reading the `qt = [{key:"energy", getValue: e => e.c_nutritionEnergyKcal} …]`
table — the i18n strings on the HTML page name the fields but not the source.

Getting a token — the trap
--------------------------
The SSR'd `mobify-data` blob on a product page carries the **master** product
(`111465m`), which has *no* `c_nutrition*` attributes at all; only the variant
(`111465`) does. So the HTML alone looks like Hotel Chocolat publishes no
macros. It does — you just have to call the API.

SCAPI needs a bearer token, and the SLAS client here is a *private* client:
the normal public-client PKCE guest flow (`/oauth2/authorize?hint=guest`)
answers `401 "incorrect client type"`. PWA Kit solves this by proxying token
requests through the Managed Runtime app, which injects the client secret, at

    POST /mobify/slas/private/shopper/auth/v1/organizations/<org>/oauth2/token
         grant_type=client_credentials&channel_id=HotelChocolat

That endpoint is open and returns a guest token. Everything else then goes
through `/mobify/proxy/api/...`. Note the *other* proxy path,
`/mobify/proxy/ocapi/...`, is Cloudflare-403'd even with browser TLS
impersonation — use the SCAPI one.

Enumeration: `product-search?refine=cgid=root` pages the whole catalogue
(~743 hits, 463 distinct `representedProducts` ids); `products?ids=` takes 24
ids per call. ~25 requests total.

Basis: every figure is **per 100 g**, matching the on-site "Per 100g" header.
Boxed chocolates, drinking chocolate powders, biscuits and alcohol are all in
one catalogue, so treat these as per-100g reference values, not portions.
"""
from __future__ import annotations

from ..base import item, session, to_float

CHAIN = "hotel_chocolat"
SOURCE = "Hotel Chocolat UK product catalogue (Salesforce Commerce API)"
SOURCE_URL = "https://www.hotelchocolat.com/uk/i/allergens-nutritional-information.html"

ORIGIN = "https://www.hotelchocolat.com"
ORG = "f_ecom_aazp_prd"
SITE = "HotelChocolat"

TOKEN_URL = (f"{ORIGIN}/mobify/slas/private/shopper/auth/v1/organizations/"
             f"{ORG}/oauth2/token")
SEARCH_URL = (f"{ORIGIN}/mobify/proxy/api/search/shopper-search/v1/organizations/"
              f"{ORG}/product-search")
PRODUCTS_URL = (f"{ORIGIN}/mobify/proxy/api/product/shopper-products/v1/organizations/"
                f"{ORG}/products")

#: SCAPI caps `ids=` at 24 per request.
_BATCH = 24
_PAGE = 200


def _token(s) -> str | None:
    r = s.post(TOKEN_URL, timeout=60, data={
        "grant_type": "client_credentials", "channel_id": SITE})
    if r.status_code != 200:
        return None
    return r.json().get("access_token")


def _all_product_ids(s, headers) -> list[str]:
    ids: list[str] = []
    offset = 0
    while True:
        r = s.get(SEARCH_URL, timeout=90, headers=headers, params={
            "siteId": SITE, "refine": "cgid=root",
            "limit": _PAGE, "offset": offset})
        if r.status_code != 200:
            break
        data = r.json()
        hits = data.get("hits") or []
        for hit in hits:
            for rep in hit.get("representedProducts") or []:
                if rep.get("id"):
                    ids.append(rep["id"])
        offset += _PAGE
        if not hits or offset >= data.get("total", 0):
            break
    return list(dict.fromkeys(ids))


def _row(p: dict) -> dict | None:
    name = (p.get("name") or "").strip()
    kcal = to_float(p.get("c_nutritionEnergyKcal"))
    protein = to_float(p.get("c_nutritionProtein"))
    if not name or kcal is None or protein is None:
        return None
    if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
        return None
    return item(
        CHAIN, name, SOURCE, SOURCE_URL,
        item_id=str(p.get("id") or name),
        category=p.get("primaryCategoryId"),
        serving_desc="per 100g",
        kcal=kcal, protein_g=protein,
        fat_g=to_float(p.get("c_nutritionFat")),
        carbs_g=to_float(p.get("c_nutritionCarbohydrates")),
        salt_g=to_float(p.get("c_nutritionSalt")),
        vegetarian=p.get("c_isSuitableVegetarian"),
        vegan=p.get("c_isSuitableVegan"),
    )


def fetch() -> list[dict]:
    s = session()
    token = _token(s)
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}

    ids = _all_product_ids(s, headers)
    rows: list[dict] = []
    seen: set[str] = set()
    for i in range(0, len(ids), _BATCH):
        r = s.get(PRODUCTS_URL, timeout=90, headers=headers, params={
            "siteId": SITE, "allImages": "false",
            "ids": ",".join(ids[i:i + _BATCH])})
        if r.status_code != 200:
            continue
        for p in r.json().get("data") or []:
            row = _row(p)
            if row is None:
                continue
            key = str(row["name"]).lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows
