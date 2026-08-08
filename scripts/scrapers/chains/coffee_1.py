"""Coffee #1 — brand nutrition PDFs, positional (not header-driven) parsing.

Discovery
---------
`discover.py` recorded coffee_1 as `js_only` at
https://www.coffee1.co.uk/food/nutrition — that page really is client
rendered (a plain `requests.get` returns markup with zero mentions of
"kcal"/"protein" or any `.pdf` link; verified directly, not inferred). But
that is not the only page the brand publishes to, and it is not where the
real PDFs live. https://www.coffee1.co.uk/allergy-advice/ is a plain
server-rendered WordPress page that links the current guides directly:

    https://www.coffee1.co.uk/wp-content/uploads/2026/07/C1-Core-Food-July-2026-Issue-Date-2307.pdf
    https://www.coffee1.co.uk/wp-content/uploads/2026/04/C1-Core-Beverage-Allergen-Nutritional-Information-April-26-v1.pdf

Both are genuine PDFs (`%PDF` magic bytes, 200 over plain `requests`, no
Cloudflare challenge) with full per-item macros, not just allergens despite
the page's name. Filenames are re-versioned every reissue, so this adapter
resolves the current link at fetch time via WordPress's public REST media
search (`/wp-json/wp/v2/media?search=...`, no auth, no login) rather than
pinning a filename that will 404 in a month. That endpoint also conveniently
sorts by upload date, so the first "core food" / "core beverage" hit is
always the live guide.

Two documents, two unrelated table layouts
-------------------------------------------
Neither PDF yields a `pdfplumber.extract_tables()` table — both are
plain flowing text/positioned-word layouts with no ruling lines, so
`generic_pdf` (which requires a found header row inside an extracted table)
returns nothing for either. Two bespoke, purely positional parsers:

**Food guide** ("Allergens, Ingredients and Nutrition Guide"): each product
is a two-column block — ingredients/allergen prose on the left, a labelled
nutrition stack ("KJ / Kcal / Fat / Sat / Carbs / Sugar / Fibre / Protein /
Salt / Portion weight (g)") on the right, each label's row carrying two
numbers (per 100g, per portion). The product name is bold text that sits
*vertically centered* between its block's first and last nutrition label —
not above it, not beside it on the same line — because the two columns are
laid out independently and the name is simply centred on the block's height.
So: find nutrition blocks by scanning for "KJ" as a block-start marker
(collecting labels until the next "KJ"), find name candidates as bold words
left of ~22% of page width (empirically the widest real product name;
in-paragraph bold allergen words like "WHEAT"/"MILK" sit past 23%), then
assign each name to whichever block's label-row span contains it. Matching
each label to its two numbers uses proximity in `top` (±1.5pt), not a
`round()`-keyed row dict — two words on the visually same line can differ by
0.5pt and round to different integers, which silently dropped ~1 in 6 fields
(portion weight especially) in an earlier version of this parser.

**Beverage guide** ("Core Beverage Allergen Nutritional Information"): a
denser two-per-100ml/per-product table with *rotated* column headers
(pdfplumber reads "KJ" as stacked single-glyph words) repeated once per
drink family, not once per row — so there is no reliable per-row header to
map by text. Instead the 9-field order (KJ, Kcal, Fat, Sat, Carbs, Sugar,
Fibre, Protein, Salt) is fixed and read *positionally*: each data row is
found via its size label ("Single"/"Double"/"Regular"/"Large"/"Small"/
"NNoz"), then the 18 numeric words to its right on the same line (±1.5pt)
are read off in that fixed order, first 9 = per 100ml, next 9 = per product.
The product name is the nearest text line (by |Δtop|) among bold-adjacent
words left of ~28% of page width. This is deliberately the *simple* strategy
(nearest single line, not multi-line block grouping) because normal rows are
one name line per size row at ~12pt spacing throughout — grouping by a
top-gap threshold cannot tell a multi-line name apart from two different
single-line products, since both are spaced ~12pt apart here. It only
mis-attributes name text on the "Homemade Quenchers" page, which inserts an
extra "Vitamin Content" column that intrudes into the name x-range for two
products (still correct kcal/protein, just a name fragment) — not worth a
bespoke block-grouping pass for two items out of 426.

Both parsers apply the same plausibility gate as everywhere else in this
project (`protein_g * 4 <= kcal * 1.15`), which is what caught the original
row-alignment bug during development (it produced zero false passes once the
±1.5pt fix landed).

Verified samples (July/April 2026 issues): Apricot Croissant 343 kcal / 7.8g
protein per 84g portion; Latte (Regular, whole milk) 156 kcal / 8.3g protein
per product — consistent with the brand's own "Per portion" column.

Dietary flag source
--------------------
The food guide (not the beverage guide -- see below) prints a real diet-code
suffix right after each product name, e.g. "Apricot Croissant\\n(V)", and
defines the codes itself on the same page: "Key for Dietary Suitability:
Vegetarian (V): ... Vegan (Vg): ... Gluten Free (GF): ...". Codes are
comma/slash-free single tags or a combo like "(V/GF)"; a trailing "*" on a
couple of "(Vg)*" tags has no separate footnote definition found, so it is
treated as an ordinary "(Vg)" rather than guessed at further. `_TAG_RE`
already isolated this exact token during name-parsing (to keep it out of
the product name) -- it was simply discarded until now; `parsed_blocks`
now carries it through and `_fetch_food` turns it into flags. "V" alone ->
vegetarian True, vegan unset; "Vg" -> both True (vegan implies vegetarian).
No tag at all is left unset (the guide has no equivalent negative code, so
absence isn't a "no").

The BEVERAGE guide has no such tag system -- its only "vegan" mentions are
inside product names ("Vegan Tropical Milkshake") and ingredient prose
("not suitable for vegans"), both of which are exactly the name/description
text this project's non-negotiable rule forbids using to justify `True`. So
`_fetch_bev` sets no dietary flags at all.
"""
from __future__ import annotations

import re

from ..base import fetch_protected, item, session

CHAIN = "coffee_1"
BASE = "https://www.coffee1.co.uk"
MEDIA_API = BASE + "/wp-json/wp/v2/media"
SOURCE = "Coffee #1 Allergens, Ingredients and Nutrition Guide (PDF)"

#: Last-known-good direct links, used only if the media-search discovery
#: (which finds the *current* reissue) fails outright.
_FALLBACK_FOOD = (BASE + "/wp-content/uploads/2026/07/"
                   "C1-Core-Food-July-2026-Issue-Date-2307.pdf")
_FALLBACK_BEV = (BASE + "/wp-content/uploads/2026/04/"
                  "C1-Core-Beverage-Allergen-Nutritional-Information-April-26-v1.pdf")

NUM_RE = re.compile(r"^-?\d+\.?\d*$")
_TAG_RE = re.compile(r"^\([^)]*\)\*?$")
_FOOD_LABELS = {"KJ", "Kcal", "Fat", "Sat", "Carbs", "Sugar", "Fibre", "Protein", "Salt"}
_FOOD_FIELD = {"KJ": "kj", "Kcal": "kcal", "Fat": "fat_g", "Sat": "sat_g",
               "Carbs": "carbs_g", "Sugar": "sugar_g", "Fibre": "fibre_g",
               "Protein": "protein_g", "Salt": "salt_g", "Portion": "portion_g"}
_SKIP_NAME_WORDS = {"PRODUCT", "INGREDIENTS", "NUTRITIONAL", "INFO", "Guide",
                     "Allergens,", "Ingredients", "and", "Nutrition", "Within", "this"}
_BEV_FIELDS = ["kj", "kcal", "fat_g", "sat_g", "carbs_g", "sugar_g", "fibre_g",
               "protein_g", "salt_g"]
_SIZE_RE = re.compile(r"^(Single|Double|Regular|Large|Small|Kids|\d+oz|\d+ml)$", re.I)
_VITAMIN_RE = re.compile(r"^\d+\.?\d*u?g$", re.I)
_SKIP_BEV_WORDS = {"PRODUCT", "ALLERGENS", "SIZE", "Per", "100ml", "100g", "product"}
#: The ALLERGENS column sits close enough to the name column (x0 fraction
#: ~0.23-0.28) that its tag word rides along with the name text it's
#: printed beside ("Latte - Whole Milk" + "MILK" on the same line) rather
#: than being cleanly excluded by the x0 cutoff. Strip it back off by text
#: instead of chasing an ever-thinner x0 threshold.
#: Case-SENSITIVE on purpose: the allergen-column tag is rendered ALL CAPS
#: ("MILK"), while the same word as a genuine part of the product name is
#: Title Case ("Whole Milk", "Macchiato - Oat") — ignoring case here would
#: strip the real descriptor along with the tag ("Macchiato - Soya" ->
#: "Macchiato -"), which is what an earlier version of this filter did.
_ALLERGEN_TAG_RE = re.compile(
    r"^(MILK|OAT|SOYA|EGG|EGGS|GLUTEN|WHEAT|NUTS|FISH|CELERY|MUSTARD|"
    r"SESAME|LUPIN|SULPHITES|CRUSTACEANS|MOLLUSCS),?$")


def _strip_allergen_tags(name: str) -> str:
    tokens = name.split()
    while tokens and _ALLERGEN_TAG_RE.match(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


# ------------------------------------------------------------------ fetch --

def _discover_pdf_url(search: str, fallback: str) -> str:
    """Latest attachment matching `search`, via WordPress's public REST API."""
    s = session()
    try:
        r = s.get(MEDIA_API, params={"search": search, "per_page": 5,
                                      "orderby": "date", "order": "desc"},
                   timeout=30)
        if r.status_code == 200:
            hits = r.json()
            for m in hits:
                url = m.get("source_url") or ""
                if url.lower().endswith(".pdf"):
                    return url
    except Exception:
        pass
    return fallback


def _load_pdf(url: str) -> bytes | None:
    s = session()
    try:
        r = s.get(url, timeout=90)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    pr = fetch_protected(url, timeout=120)
    if pr is not None and pr.content[:4] == b"%PDF":
        return pr.content
    return None


# ------------------------------------------------------------- food guide --

_CATEGORY_RE = re.compile(r"^[A-Z][A-Z &']{1,28}[A-Z]$")
#: Rotated column headers ("Fat"/"Sat"/"Sugar"/"Salt") decompose into lone
#: glyphs that can land on the same text line by coincidence and still pass
#: `_CATEGORY_RE` ("F S S F S F S S F S"); allergen tags ("MILK", "OAT") do
#: too. A real category is at least one real word (>=3 letters), not just
#: single letters or a bare allergen name.
_CATEGORY_STOPWORDS = {"MILK", "SOYA", "OAT", "EGG", "EGGS", "GLUTEN", "NUTS",
                        "WHEAT", "FISH", "CELERY", "MUSTARD", "SESAME", "LUPIN",
                        "SULPHITES", "CRUSTACEANS", "MOLLUSCS", "VEGAN", "VEGGIE"}


def _looks_like_category(s: str) -> bool:
    if not _CATEGORY_RE.match(s) or s in _CATEGORY_STOPWORDS:
        return False
    tokens = s.split()
    return bool(tokens) and all(t == "&" or len(t) >= 3 for t in tokens)


def _food_category(page) -> str:
    text = page.extract_text() or ""
    for ln in text.split("\n")[:8]:
        s = ln.strip()
        if _looks_like_category(s) and "PRODUCT" not in s and "INFO" not in s \
                and "GUIDE" not in s:
            return s.title()
    return ""


def _parse_food_page(page):
    """[(name, diet_tag, {field: value}), ...] for one product-page."""
    words = page.extract_words(extra_attrs=["fontname", "size"])
    pw = page.width

    def nums_near(top, x0):
        return sorted(
            [w for w in words if abs(w["top"] - top) <= 1.5 and w["x0"] > x0
             and NUM_RE.match(w["text"])],
            key=lambda w: w["x0"])

    label_hits = [(w["top"], w["text"], w["x0"]) for w in words
                  if w["text"] in _FOOD_LABELS or w["text"] == "Portion"]

    # A word like "Fat" or "Sugar" also shows up as ordinary ingredient-list
    # prose ("Vegetable Fat", "Fruit ... Sugar") at whatever x-position that
    # sentence happens to wrap to. The real label column is a single fixed
    # x0 repeated identically block after block (the template's numeric
    # column), so keep only the modal x0 per label text and drop the rest.
    from collections import Counter
    modal_x0: dict[str, float] = {}
    for lab in _FOOD_FIELD:
        xs = [round(x0, 1) for _, l, x0 in label_hits if l == lab]
        if xs:
            modal_x0[lab] = Counter(xs).most_common(1)[0][0]
    label_hits = [(top, lab, x0) for top, lab, x0 in label_hits
                  if lab not in modal_x0 or abs(round(x0, 1) - modal_x0[lab]) <= 1.0]
    label_hits.sort(key=lambda h: h[0])

    blocks: list[list[tuple[float, str, float]]] = []
    cur: list[tuple[float, str, float]] | None = None
    for top, lab, x0 in label_hits:
        if lab == "KJ":
            cur = []
            blocks.append(cur)
        if cur is not None:
            cur.append((top, lab, x0))
    blocks = [b for b in blocks if b]

    parsed_blocks = []
    for block in blocks:
        vals: dict[str, float] = {}
        for top, lab, x0 in block:
            nums = nums_near(top, x0)
            if not nums:
                continue
            if lab == "Portion":
                vals["portion_g"] = float(nums[-1]["text"])
            elif len(nums) >= 2:
                vals[_FOOD_FIELD[lab]] = float(nums[1]["text"])  # per-portion
            elif len(nums) == 1:
                vals[_FOOD_FIELD[lab]] = float(nums[0]["text"])
        tops = [t for t, _, _ in block]
        parsed_blocks.append((min(tops), max(tops), vals))

    name_words = [w for w in words
                  if "Bold" in w.get("fontname", "") and w["x0"] / pw < 0.22
                  and w["top"] >= 170
                  and w["text"] not in _SKIP_NAME_WORDS
                  and w["text"].rstrip(",") not in _SKIP_NAME_WORDS]
    lines: dict[int, list] = {}
    for w in name_words:
        lines.setdefault(round(w["top"]), []).append(w)
    line_list = [(t, " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])))
                 for t, ws in sorted(lines.items())]

    groups: list[list[tuple[int, str]]] = []
    prev_top = None
    for t, text in line_list:
        if prev_top is None or t - prev_top > 20:
            groups.append([])
        groups[-1].append((t, text))
        prev_top = t
    names = []
    for g in groups:
        texts = [x[1] for x in g]
        tag = texts.pop() if texts and _TAG_RE.match(texts[-1]) else None
        # dedupe accidental repeated tokens (stray bold word bleed-through)
        dedup: list[str] = []
        for tok in " ".join(texts).split():
            if dedup and tok == dedup[-1]:
                continue
            dedup.append(tok)
        name = " ".join(dedup).strip()
        if name:
            avg_top = sum(x[0] for x in g) / len(g)
            names.append((avg_top, name, tag))

    out = []
    for block_top, block_bot, vals in parsed_blocks:
        best, bestd = None, None
        for avg_top, name, tag in names:
            if block_top - 10 <= avg_top <= block_bot + 10:
                d = abs(avg_top - (block_top + block_bot) / 2)
                if bestd is None or d < bestd:
                    bestd, best = d, (name, tag)
        if best:
            out.append((best[0], vals, best[1]))
    return out


def _diet_flags(tag: str | None) -> tuple[bool | None, bool | None]:
    """(vegetarian, vegan) from a "(V)"/"(Vg)"/"(V/GF)"/"(Vg)*" diet-code
    suffix -- see "Dietary flag source" above."""
    if not tag:
        return None, None
    codes = {c.strip("*") for c in tag.strip("()").split("/")}
    vegan = "Vg" in codes
    vegetarian = vegan or "V" in codes
    return (vegetarian or None), (vegan or None)


def _fetch_food(url: str) -> list[dict]:
    import io
    import pdfplumber

    raw = _load_pdf(url)
    if raw is None:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    last_category = ""
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "PRODUCT" not in text or "Kcal" not in text:
                continue
            category = _food_category(page) or last_category
            last_category = category
            for name, vals, tag in _parse_food_page(page):
                kcal, protein = vals.get("kcal"), vals.get("protein_g")
                if kcal is None or protein is None or kcal <= 0:
                    continue
                if protein * 4 > kcal * 1.15:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                portion = vals.get("portion_g")
                serving = f"{portion:g}g" if portion else "per portion"
                vegetarian, vegan = _diet_flags(tag)
                out.append(item(
                    CHAIN, name, SOURCE, url,
                    item_id=name, category=category, serving_desc=serving,
                    kcal=kcal, protein_g=protein,
                    carbs_g=vals.get("carbs_g"), fat_g=vals.get("fat_g"),
                    salt_g=vals.get("salt_g"),
                    vegetarian=vegetarian, vegan=vegan,
                ))
    return out


# --------------------------------------------------------- beverage guide --

def _bev_categories(words) -> list[tuple[float, str]]:
    """[(top, category), ...] — a page can carry more than one drink family
    (e.g. Caramel Macchiato *and* Americano share a page), so every heading
    is kept and rows are matched to whichever one sits above them."""
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w["top"]), []).append(w)
    out = []
    for t, ws in sorted(lines.items()):
        s = " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])).strip()
        if _looks_like_category(s) and "PRODUCT" not in s and "INFO" not in s \
                and "ALLERGEN" not in s:
            out.append((t, s.title()))
    return out


def _parse_bev_page(page):
    words = page.extract_words(extra_attrs=["fontname", "size"])
    pw = page.width

    size_hits = [w for w in words
                 if _SIZE_RE.match(w["text"]) and 0.28 < w["x0"] / pw < 0.36]

    rows = []
    for sw in size_hits:
        top = sw["top"]
        nums = sorted(
            [w for w in words if abs(w["top"] - top) <= 1.5 and w["x0"] > sw["x0"]
             and NUM_RE.match(w["text"])],
            key=lambda w: w["x0"])
        if len(nums) < 18:
            continue
        perprod = {f: float(nums[9 + i]["text"]) for i, f in enumerate(_BEV_FIELDS)}
        rows.append((top, sw["text"], perprod))

    name_words = [w for w in words
                  if w["x0"] / pw < 0.28 and w["text"] not in _SKIP_BEV_WORDS
                  and not _VITAMIN_RE.match(w["text"])]
    lines: dict[int, list] = {}
    for w in name_words:
        lines.setdefault(round(w["top"]), []).append(w)
    line_list = [(t, _strip_allergen_tags(
                     " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]))))
                 for t, ws in sorted(lines.items())]

    categories = _bev_categories(words)

    out = []
    for top, size, vals in rows:
        best, bestd = None, None
        for t, text in line_list:
            d = abs(t - top)
            if bestd is None or d < bestd:
                bestd, best = d, text
        category = ""
        for t, cat in categories:
            if t <= top:
                category = cat
            else:
                break
        if best:
            out.append((best, size, vals, category))
    return out


def _fetch_bev(url: str) -> list[dict]:
    import io
    import pdfplumber

    raw = _load_pdf(url)
    if raw is None:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "PRODUCT" not in text:
                continue
            for name, size, vals, category in _parse_bev_page(page):
                kcal, protein = vals.get("kcal"), vals.get("protein_g")
                if kcal is None or protein is None or kcal <= 0:
                    continue
                if protein * 4 > kcal * 1.15:
                    continue
                full_name = f"{name} — {size}"
                key = full_name.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(item(
                    CHAIN, full_name, SOURCE, url,
                    item_id=full_name, category=category, serving_desc=size,
                    kcal=kcal, protein_g=protein,
                    carbs_g=vals.get("carbs_g"), fat_g=vals.get("fat_g"),
                    salt_g=vals.get("salt_g"),
                ))
    return out


# --------------------------------------------------------------------- api

def fetch() -> list[dict]:
    food_url = _discover_pdf_url("core food", _FALLBACK_FOOD)
    bev_url = _discover_pdf_url("core beverage", _FALLBACK_BEV)
    return _fetch_food(food_url) + _fetch_bev(bev_url)
