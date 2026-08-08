"""Caffè Nero GB — brand allergen/nutrition PDF (food range).

Discovery: caffenero.com serves its guide from Azure blob storage, not the
brand domain — https://caffenerowebsite.blob.core.windows.net/production/
data/menus/caffenero_nutrition_allergens-en_GB.pdf (there is a parallel
``-en_IE.pdf`` for ROI/NI which we do not use).

Format, and why the generic PDF adapter returns nothing here: the food pages
are not a product-per-row table. Each product is a *block* laid out as three
columns — product name, an ingredient declaration, and a transposed nutrition
panel where the NUTRIENTS are the rows ("Kcal 317 238") and the two columns are
per 100 g and per portion. `pdfplumber.extract_tables` sees only stray
one-cell fragments, so this adapter works from word positions instead:

* a block starts at each "per 100g per portion (g)" line (the word "per" at
  x ~ 920);
* inside the block, the row labelled "Kcal"/"Protein" gives per-100g (x < 975)
  and per-portion (x >= 975) values — per portion is what we keep, since the
  per-100g figures would understate a 190 g panini by ~2x;
* the product name is the only text in the left column set in 9.1 pt bold —
  filtering on x alone drags in wrapped ingredient text ("WHEAT Brie & Bacon
  Panini Sugar,"), so the font size filter is load-bearing.

Beverage pages (22+) use a different, wide per-100ml/per-product table whose
product names sit on separate lines from their size rows; they are deliberately
not parsed here — the food range is where the protein is.

Dietary flag source
--------------------
Every product name in this PDF carries a brand-published parenthetical diet
code — "(V)" for vegetarian, "(Vg)" for vegan, e.g. "Pastel De Nata (V)",
"Raspberry Jam (Vg)", "Mushroom & Tomato Ragu Panini (Vg)" (`(GF)` also
appears, for gluten-free, unrelated to vegetarian/vegan and not used here).
`_DIET_SUFFIX` already matched this to strip it from the display name; it
previously discarded the match instead of reading it. `(Vg)` implies both
vegetarian and vegan; `(V)` implies vegetarian only — Caffè Nero's own
codes, not inferred from surrounding name text. Items with neither code are
left unset (most of the range — sandwiches, meat/fish products — carries no
code at all, so absence is not itself evidence of anything).
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session

CHAIN = "caffe_nero"
SOURCE = "brand PDF (Caffè Nero GB allergen, nutritional & ingredient guide)"
SOURCE_URL = ("https://caffenerowebsite.blob.core.windows.net/production/"
              "data/menus/caffenero_nutrition_allergens-en_GB.pdf")

#: x-band, font and size that isolate the product-name column. Product names
#: are always CenturyGothic-Bold 9.1 pt; ingredient text is 8 pt CenturyGothic
#: on most pages but 10 pt Calibri on a few, so size alone is not enough.
_NAME_X = (100, 230)
_NAME_MIN_SIZE = 8.5
_NAME_FONT = "centurygothic-bold"
#: x of the "per 100g / per portion" header words that start each block.
_BLOCK_X = (900, 940)
#: per-100g values sit left of this x, per-portion values right of it.
_PORTION_X = 975
#: nutrient labels sit in the right-hand panel, never in the name column.
_LABEL_MIN_X = 850

_NUM = re.compile(r"^<?\d+(?:[.,]\d+)?$")
_DIET_SUFFIX = re.compile(r"\s*\((V|Vg|VE|GF)\)\s*", re.I)


def _num(text: str) -> float | None:
    text = str(text).strip()
    if not _NUM.match(text):
        return None
    try:
        return float(text.lstrip("<").replace(",", "."))
    except ValueError:
        return None


def _label_values(words, label: str, y0: float, y1: float):
    """(per_100g, per_portion) for a nutrient row inside one product block."""
    for w in words:
        if (w["text"].lower().rstrip(":") != label
                or w["x0"] <= _LABEL_MIN_X or not y0 <= w["top"] < y1):
            continue
        row = sorted((x for x in words
                      if abs(x["top"] - w["top"]) < 6 and x["x0"] > w["x1"]),
                     key=lambda x: x["x0"])
        vals = [(x["x0"], _num(x["text"])) for x in row]
        vals = [(x, v) for x, v in vals if v is not None]
        per100 = next((v for x, v in vals if x < _PORTION_X), None)
        portion = next((v for x, v in vals if x >= _PORTION_X), None)
        return per100, portion
    return None, None


def _download() -> bytes | None:
    try:
        r = session().get(SOURCE_URL, timeout=150)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    pr = fetch_protected(SOURCE_URL, timeout=180)
    if pr is not None and pr.content[:4] == b"%PDF":
        return pr.content
    return None


def parse(raw: bytes) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["size"])
            starts = sorted({round(w["top"]) for w in words
                             if w["text"] == "per"
                             and _BLOCK_X[0] < w["x0"] < _BLOCK_X[1]})
            if not starts:
                continue
            bounds = starts + [page.height]
            for i, y0 in enumerate(starts):
                y1 = bounds[i + 1]
                _, kcal = _label_values(words, "kcal", y0, y1)
                _, protein = _label_values(words, "protein", y0, y1)
                _, weight = _label_values(words, "weight", y0, y1)
                if kcal is None or protein is None:
                    continue
                if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
                    continue          # missing or misread macros
                name_words = sorted(
                    (w for w in words
                     if _NAME_X[0] < w["x0"] < _NAME_X[1]
                     and y0 <= w["top"] < y1
                     and w.get("size", 0) > _NAME_MIN_SIZE),
                    key=lambda w: (round(w["top"] / 4), w["x0"]))
                name = " ".join(w["text"] for w in name_words)
                diet_m = _DIET_SUFFIX.search(name)
                diet_code = diet_m.group(1).lower() if diet_m else None
                name = re.sub(r"\s+", " ", _DIET_SUFFIX.sub(" ", name)).strip()
                # trailing column headings occasionally bleed into a block
                name = re.sub(r"\s*(PRODUCT|INGREDIENTS)\s*$", "", name).strip()
                if len(name) < 3 or name.lower() in seen:
                    continue
                seen.add(name.lower())
                _, fat = _label_values(words, "fat", y0, y1)
                _, carbs = _label_values(words, "carbs", y0, y1)
                _, salt = _label_values(words, "salt", y0, y1)
                vegan = True if diet_code in ("vg", "ve") else None
                vegetarian = True if (vegan or diet_code == "v") else None
                out.append(item(
                    CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
                    category="Food",
                    serving_desc=(f"per portion ({weight:g}g)" if weight
                                  else "per portion"),
                    kcal=kcal, protein_g=protein,
                    fat_g=fat, carbs_g=carbs, salt_g=salt,
                    vegetarian=vegetarian, vegan=vegan))
    return out


def fetch() -> list[dict]:
    raw = _download()
    return parse(raw) if raw else []
