"""German Doner Kebab (GDK UK) — per-item nutrition tables on product pages.

Discovery
---------
`catalog.py`'s note for this chain ("allergens published, macros not found on
site") is wrong and predates this adapter — the allergen page
(gdk.com/gb/allergen-information) is indeed allergens-only, but that is not
the only page GDK publishes. Every product has its own page at
`gdk.com/gb/menu/<slug>` and *that* page carries a full "NUTRITIONAL" table,
separate from the "ALLERGENS" table above it:

    https://gdk.com/gb/menu/gdk-doner-burrito

    <div class="table-heading-label">NUTRITIONAL</div>
    <div class="table-10-col-row header">
      <div class="table-header-details-text">Energy KCal</div>
      <div class="table-header-details-text">Energy KJ</div>
      <div class="table-header-details-text">Fat (g)</div>
      ... Sat, Carb, Sugars, Fibre, Protein, Salt, Sodium, Portion Size (g)
    </div>
    <div class="table-10-col-row data-row">
      <div class="table-1---header---text data center">Doner Burrito Beef</div>
      <div class="table-col">1218</div> ... 11 value columns

The site is plain server-rendered HTML (Webflow), no JS execution or API
needed — `curl`/`requests` sees the same markup a browser would.

Two-stage fetch, same shape as itsu: the menu listing
(gdk.com/gb/menu) groups products under section headings
("Mains (12)", "Toppings (5)", "Signature Sauces (5)", ...); each section's
heading text becomes `category` so the search-layer's non-product-category
filter can drop "Toppings"/"Signature Sauces" rows the way it already does
for other chains. Then every product URL is fetched individually (~75
requests) for its nutrition table.

Traps
-----
* One product page can carry *multiple* nutrition rows — protein variants
  ("Doner Burrito Beef" / "Chicken" / "Mix" / "Plant-based") share one page
  and one title, but are nutritionally distinct meals. The row's own name
  (not the page title) is used as the item name.
* Not every product page has a nutrition table: canned drinks (Coke, Diet
  Coke), Ayran, Dill Pickles, and multi-component boxes like "Boss Box Jr"
  render only the page chrome and CSS for `.kcal-wrapper` with no actual
  `data-row` content underneath — skipped rather than guessed at.
* "Portion Size (g)" is a real serving weight (e.g. 530g burrito, not
  per-100g), so servings are recorded as genuine per-item portions.
* Header order is read dynamically rather than hardcoded by column index —
  the table is otherwise identical to Chopstix's trap in reverse (rotated
  labels there; here the risk is a future reorder silently misreading a
  column), so field lookup goes by header text.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from ..base import fetch_protected, item, session, to_float

CHAIN = "gdk"
SOURCE = "brand site (GDK per-item nutrition tables)"
MENU_URL = "https://gdk.com/gb/menu"
BASE = "https://gdk.com"

WORKERS = 8

_SECTION_RE = re.compile(
    r'menu-category-heading">([^<(]+?)\s*(?:\(\d+\))?<', re.I)
#: Product slugs are usually [a-z0-9-] but the "FIV£R" range literally bakes
#: the pound sign into the URL (gdk-fiv£r-london-jerk-loaded-fries) — an
#: ASCII-only class silently drops that whole section, so match up to the
#: closing quote instead of guessing the slug alphabet.
_LINK_RE = re.compile(r'href="(https://gdk\.com/gb/menu/[^"?#]+)"', re.I)

_HEADER_TEXT_RE = re.compile(r'table-header-details-text">\s*([^<]+?)\s*</div>')
_ROW_NAME_RE = re.compile(r'table-1---header---text data center">([^<]+)<')
_ROW_VAL_RE = re.compile(r'<div class="table-col">([^<]*)</div>')

#: Header text -> normalized field. Matched by exact (lowercased) label so a
#: future "Fat (g)" vs "Fibre (g)" style near-miss can't cross-map.
_FIELD_MAP = {
    "energy kcal": "kcal",
    "fat (g)": "fat_g",
    "carb (g)": "carbs_g",
    "protein (g)": "protein_g",
    "salt (g)": "salt_g",
    "portion size (g)": "portion_g",
}


def _get(url: str, timeout: int = 60) -> str | None:
    s = session()
    try:
        r = s.get(url, timeout=timeout)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    pr = fetch_protected(url, timeout=timeout + 30)
    if pr is not None and pr.text:
        return pr.text
    return None


def _sections(listing: str) -> list[tuple[str, str]]:
    """[(product_url, category), ...] in menu order, deduped by URL."""
    heads = list(_SECTION_RE.finditer(listing))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, h in enumerate(heads):
        start = h.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(listing)
        category = h.group(1).strip()
        for m in _LINK_RE.finditer(listing[start:end]):
            url = m.group(1)
            if url not in seen:
                seen.add(url)
                out.append((url, category))
    return out


def _parse_product(entry: tuple[str, str]) -> list[dict]:
    url, category = entry
    body = _get(url)
    if not body:
        return []

    i = body.find('table-heading-label">NUTRITIONAL')
    if i < 0:
        return []
    j = body.find("table-heading-label", i + 10)
    block = body[i:j] if j > 0 else body[i:i + 20000]

    header_start = block.find("table-10-col-row header")
    rows_blob = block[header_start:] if header_start >= 0 else block
    parts = re.split(r"table-10-col-row data-row", rows_blob)
    header_part, row_parts = parts[0], parts[1:]

    headers = [h.lower() for h in _HEADER_TEXT_RE.findall(header_part)]
    cols = {_FIELD_MAP[h]: idx for idx, h in enumerate(headers) if h in _FIELD_MAP}
    if "kcal" not in cols or "protein_g" not in cols:
        return []

    recs: list[dict] = []
    for row in row_parts:
        name_m = _ROW_NAME_RE.search(row)
        if not name_m:
            continue
        name = " ".join(name_m.group(1).split())
        vals = _ROW_VAL_RE.findall(row)
        if len(vals) != len(headers):
            continue  # positional mismatch — table shape changed, skip safely

        def get(field):
            idx = cols.get(field)
            return to_float(vals[idx]) if idx is not None else None

        kcal, protein = get("kcal"), get("protein_g")
        if kcal is None or protein is None or kcal <= 0:
            continue
        if protein * 4 > kcal * 1.15:
            continue

        portion = get("portion_g")
        serving_desc = f"{portion:g}g" if portion else "per portion"
        recs.append(item(
            CHAIN, name, SOURCE, url,
            item_id=name, category=category, serving_desc=serving_desc,
            kcal=kcal, protein_g=protein,
            carbs_g=get("carbs_g"), fat_g=get("fat_g"), salt_g=get("salt_g"),
        ))
    return recs


def fetch() -> list[dict]:
    listing = _get(MENU_URL, timeout=90)
    if not listing:
        return []
    entries = _sections(listing)
    if not entries:
        return []

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(_parse_product, entries))

    out: list[dict] = []
    seen: set[str] = set()
    for recs in results:
        for rec in recs:
            key = rec["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
    return out
