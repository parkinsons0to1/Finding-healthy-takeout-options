"""Pizza Hut Delivery UK — the "Allergens & Nutrition" booklet in Contentful.

Discovery
---------
pizzahut.co.uk is an Angular SPA; nothing useful is in its HTML. Two paths
were opened up here, and only the second one carries protein:

1. **The storefront GraphQL API (works, but calories-only).**
   `https://www.pizzahut.co.uk/ph_uk/storefront/graphql` is a Yum! Connect
   endpoint that 401s ("Access denied to one or more GraphQL types") until you
   present a bearer token. The site mints one anonymously — no account needed:

       POST https://www.pizzahut.co.uk/v1/oidc/oauth2/token
       Content-Type: application/x-www-form-urlencoded
       originatingAppId: ph_uk_web
       grant_type=guest&client_id=ph_uk_web

   With `Authorization: Bearer <access_token>` the whole menu opens up
   (`storeByNumber(storeNumber:"1004"){menuByChannel(channel:WEB){...}}`,
   ~790 variants per store, one menu instance per store).
   **The trap:** the schema *does* define protein — `ProductVariant.nutrition`
   -> `Nutrition.nutritionalValues` -> `NutritionalValuePerBasis{protein …}` —
   which makes it look like the answer. In the live UK data `nutrition` is
   `null` on every single variant, and the only populated field is the string
   list `nutritionInformation: ["calories:2231", "serves:3"]`. Energy only.
   Do not re-mine the API for protein; it is not there.

2. **Contentful (this module's source).** The SPA's config points at
   `spaces/gsh8f6v1sw3c` and ships a Contentful delivery token in the bundle.
   Listing that space's assets turns up 31 PDFs, of which exactly one is the
   current nutrition booklet: title "Allergens & Nutrition",
   `DELEX_AIN_Booklet_C3_2026_V1_1.pdf` (valid from July 2026). Pages 0-3 are
   the allergen/ingredient matrix; **pages 4-9 are the nutrition tables** with
   Energy/Fat/Saturates/Carbohydrate/Sugar/**Protein**/Salt.

   Two near-misses to not repeat: the `DINE-IN_AIN_Booklet` (Pizza Hut
   Restaurants, the separate dine-in company) is allergens only — its 29
   "protein" hits are ingredient words like "MILK Protein"; and
   `/order/pdfs/Nutritional-Information.pdf` serves the SPA shell, not a PDF.

Traps in the PDF
----------------
* **The Category and Product-name cells are rotated 90°**, and
  `extract_tables()` returns them character-reversed *and* line-reversed: the
  cell for "Halal Pepperoni Feast" comes back as `'tsaeF\\ninoreppeP\\nlalaH'`.
  Naively reversing the string is *almost* right but silently scrambles any
  cell that wrapped onto more than one visual line ("Halal Loaded Pepperoni
  Feast" became "Halal Loaded Feast Pepperoni"), so `_cell_text()` rebuilds
  those cells from character geometry instead: rotated glyphs read
  bottom-to-top (sort by `top` descending) and wrapped lines advance
  left-to-right (group by `x0` ascending).
  Not every cell is rotated, either — "Flatzz UK" and "Melts" are horizontal,
  and blanket-reversing them produced items literally named "KU zztalF"; the
  `upright` flag on the chars tells the two apart.
* The column headers are rotated too, so no header text ever contains the
  literal "kcal"/"protein" — a header-matching parser finds nothing here.
  Column order is fixed and positional: Category, Product name, Size, Serves,
  then Energy(kcal), Fat, Saturated Fat, Carbohydrate, Sugar, Protein, Salt.
* Each page yields **two** tables: "Nutrition Per Whole Product" (11 cols) and
  "Nutrition Per Serving" (7 cols). We take the whole-product table, because
  that is the unit you actually order — a "Large Handcrafted" row's per-serving
  figures are a third of a pizza. `serving_desc` records the serves count.
* Names are assembled as "<Product> — <Size>" only for pizzas, where Size is a
  crust/size descriptor. For sides/chicken/dips/desserts the Size column holds
  the real product name ("Potato Wedges") and the Product column is a section
  heading ("Classic Sides"), so the heading is demoted to `category` — this is
  the section-heading-as-product-name failure mode, avoided deliberately.

Politeness: two HTTP requests (token-free) — one Contentful lookup, one PDF.
"""
from __future__ import annotations

import io
import re

from ..base import item, session, to_float

CHAIN = "pizza_hut"
SOURCE = "brand PDF (Pizza Hut Delivery UK Allergens & Nutrition booklet, valid from July 2026)"
SOURCE_URL = ("https://assets.ctfassets.net/gsh8f6v1sw3c/6XUgXQCKklvPyrUmgIVshd/"
              "6948068493acdb56f38be1f2360388d0/DELEX_AIN_Booklet_C3_2026_V1_1.pdf")

#: Read-only Contentful delivery token, shipped in the site's public JS bundle
#: (main.*.js -> contentfulCms.deliveryApiKey). Used only to find a newer
#: booklet than SOURCE_URL; failure here is non-fatal.
_CDA = "https://cdn.contentful.com/spaces/gsh8f6v1sw3c/environments/master/assets"
_CDA_TOKEN = "RPf5VzSzPkQcidaDhZVqur2FGDY7Mlc3hhxK-YTgGIg"
_BOOKLET_RE = re.compile(r"DELEX_AIN_Booklet.*\.pdf$", re.I)

#: Size-column values that describe a pizza format rather than a product.
_PIZZA_SIZE = re.compile(
    r"handcrafted|\bpan\b|stuffed crust|cheesy bites|gluten\s*free|express only|"
    r'^\d+"|big\s+new\s+yorker', re.I)

#: Columns of the "Nutrition Per Whole Product" table, after Serves.
_COLS = {"kcal": 4, "fat_g": 5, "sat_g": 6, "carbs_g": 7, "sugar_g": 8,
         "protein_g": 9, "salt_g": 10}


def _cell_text(page, bbox, fallback: str) -> str:
    """Read a table cell, un-rotating it if its glyphs are sideways.

    `bbox` is (x0, top, x1, bottom) from `Table.rows[i].cells[j]`.
    """
    if not bbox:
        return " ".join((fallback or "").split())
    x0, top, x1, bottom = bbox
    chars = [c for c in page.chars
             if c["x0"] >= x0 - 1 and c["x1"] <= x1 + 1
             and c["top"] >= top - 1 and c["bottom"] <= bottom + 1]
    if not chars:
        return " ".join((fallback or "").split())
    if all(c.get("upright", True) for c in chars):
        return " ".join((fallback or "").split())

    lines: dict[int, list] = {}
    for c in chars:
        lines.setdefault(round(c["x0"]), []).append(c)
    parts = []
    for key in sorted(lines):
        glyphs = sorted(lines[key], key=lambda c: -c["top"])
        parts.append("".join(g["text"] for g in glyphs).strip())
    return " ".join(" ".join(parts).split())


def _num(row: list, idx: int):
    if idx >= len(row):
        return None
    return to_float(re.sub(r"[^\d.]", "", str(row[idx] or "")) or None)


def _booklet_url(s) -> str:
    """Prefer whatever booklet Contentful currently holds; fall back to ours."""
    try:
        r = s.get(_CDA, params={"access_token": _CDA_TOKEN, "limit": 1000},
                  timeout=60)
        best = None
        for a in r.json().get("items", []):
            f = (a.get("fields") or {}).get("file") or {}
            url = f.get("url") or ""
            if _BOOKLET_RE.search(url):
                stamp = (a.get("sys") or {}).get("updatedAt", "")
                if best is None or stamp > best[0]:
                    best = (stamp, url)
        if best:
            return "https:" + best[1] if best[1].startswith("//") else best[1]
    except Exception:
        pass
    return SOURCE_URL


def fetch() -> list[dict]:
    import pdfplumber

    s = session()
    url = _booklet_url(s)
    r = s.get(url, timeout=120)
    if r.status_code != 200 or r.content[:4] != b"%PDF":
        return []

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for page in pdf.pages:
            for finder in page.find_tables():
                table = finder.extract()
                if not table or len(table[0]) < 11:
                    continue
                header = " ".join(str(c or "") for c in table[0])
                # "Nutrition Per Whole Product" — the allergen pages have no
                # such banner, and the per-serving table has only 7 columns.
                if "Whole Product" not in header:
                    continue

                category = product = ""
                for ri, row in enumerate(table):
                    if ri < 2:
                        continue
                    cells = [(str(c).replace("\n", " ").strip() if c else "")
                             for c in row]
                    boxes = finder.rows[ri].cells
                    if row[0]:
                        category = _cell_text(page, boxes[0], row[0])
                    if row[1]:
                        product = _cell_text(page, boxes[1], row[1])
                    size = cells[2]
                    if not size:
                        continue

                    kcal = _num(cells, _COLS["kcal"])
                    protein = _num(cells, _COLS["protein_g"])
                    if kcal is None or protein is None or kcal <= 0:
                        continue
                    if protein * 4 > kcal * 1.15:
                        continue

                    # Only pizza rows split product/size; on the sides pages
                    # "Handcrafted"/"Express Only" appear in real product names
                    # ("Handcrafted Cheesy Garlic Strips"), so gate on category.
                    if "pizza" in category.lower() and _PIZZA_SIZE.search(size):
                        name = f"{product} — {size}" if product else size
                        cat = category
                    else:
                        # Size column holds the real product; Product column is
                        # a section heading, so it must not become the name.
                        name = size
                        cat = f"{category} / {product}".strip(" /")
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)

                    serves = _num(cells, 3)
                    out.append(item(
                        CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
                        category=cat or None,
                        serving_desc=("whole product"
                                      + (f" (serves {serves:g})" if serves else "")),
                        kcal=kcal, protein_g=protein,
                        carbs_g=_num(cells, _COLS["carbs_g"]),
                        fat_g=_num(cells, _COLS["fat_g"]),
                        salt_g=_num(cells, _COLS["salt_g"]),
                    ))
    return out
