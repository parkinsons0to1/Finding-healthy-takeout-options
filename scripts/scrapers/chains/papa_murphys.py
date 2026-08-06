"""Papa Murphy's — Nutritionix Interactive Nutrition Menu (server-rendered HTML).

NOTE ON SCOPE: Papa Murphy's is a US chain and this is US data (no UK menu was
found). It is included because the chain was on the target list; a UK-only
consumer of this pipeline should filter it out.

Discovery
---------
https://www.papamurphys.com/nutrition/ contains no nutrition itself — 0
occurrences of "protein". It embeds Nutritionix's Interactive Nutrition Menu:

    <div id="inm-container"></div>
    <script src="https://nix-vue-inm.s3.amazonaws.com/loader.js"></script>
    <script>Nutritionix.inm.iframe(el,
        'https://restaurant.nutritionix.com/papa-murphys/landing', …)</script>

That iframe is a Vue app whose data never appears in HTML, and its S3 bundles
(``app.js``/``vendors.js``) return 403, so the API cannot be read out of them.
Playwright was also a dead end here — Chromium could not reach the network
through this sandbox's proxy (ERR_CONNECTION_RESET).

The way through: Nutritionix publishes the SAME brand data server-rendered as
an ordinary HTML table on its own site, no API key required:

    https://www.nutritionix.com/papa-murphys/menu/premium

TRAP 1 — needs browser TLS and a referer
    A plain ``requests`` GET is rejected; ``fetch_protected`` with a
    papamurphys.com ``Referer`` works.

TRAP 2 — the column order is NOT the usual one
    Columns are: 0 name, 1 Calories, 2 Total Fat, 3 Saturated Fat,
    4 Trans Fat, 5 Cholesterol, 6 Sodium, 7 Total Carbohydrates,
    8 Dietary Fiber, 9 Sugars, 10 Protein. Protein is LAST, after two columns
    (cholesterol, sodium) that do not appear in UK-style tables. Reading
    "protein is the 8th number" — true for every other chain in this package —
    picks up Dietary Fiber here. The header cells carry stable ``id`` values
    (``inmGrid_c1`` … ``inmGrid_c10``) and sort links (``?sort=protein``), so
    the columns are located by parsing that header rather than by position.

TRAP 3 — the basis is PER SLICE, not per pizza
    Section rows ("subCategory") carry both the section name in an ``<h3>``
    and the serving rule in a ``<p>``, e.g. "Family Pizza Slices" /
    "1 Serving = 1 Slice = 1/12th of the Pizza". That note is the ONLY place
    the basis is stated — the data rows look like ordinary per-item values.
    Both are carried onto every following row, and the slice basis is folded
    into the item name so a slice can never be mistaken for a whole pizza.

    Reading it also requires matching the ``<tr …>`` tag WITH its attributes:
    the marker is ``class="subCategory"`` on the tag itself, so a regex that
    captures only the text between ``<tr>`` and ``</tr>`` silently never sees a
    section and every row ends up uncategorised.

TRAP 4 — item names carry a trailing "[more info]"
    Each name cell is followed by a sibling "More Information" anchor that
    flattens into the name. It is stripped.
"""
from __future__ import annotations

import html
import re

from ..base import fetch_protected, item, to_float

CHAIN = "papa_murphys"
SOURCE = "Papa Murphy's Interactive Nutrition Menu (Nutritionix)"
SOURCE_URL = "https://www.nutritionix.com/papa-murphys/menu/premium"
REFERER = "https://www.papamurphys.com/"

#: sort-link keyword -> canonical field, used to map header columns.
_FIELDS = {
    "calories": "kcal",
    "protein": "protein_g",
    "total_fat": "fat_g",
    "total_carb": "carbs_g",
}


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def _map_columns(thead: str) -> dict[str, int]:
    """Canonical field -> column index, read from the header's sort links."""
    cols: dict[str, int] = {}
    for idx, th in enumerate(re.findall(r"<th\b.*?</th>", thead, re.S)):
        # NB: the query separator arrives HTML-escaped as "&amp;sort=", so the
        # character before "sort" is ';', not '&' — anchoring on [?&] finds
        # nothing and the whole table silently yields zero rows.
        m = re.search(r"\bsort=([a-z_]+)", th)
        if not m:
            continue
        field = _FIELDS.get(m.group(1))
        if field and field not in cols:
            cols[field] = idx
    return cols


def _number(cell: str):
    txt = _text(cell).replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", txt)
    return to_float(m.group()) if m else None


def _parse(page: str) -> list[dict]:
    m = re.search(r"<thead\b.*?</thead>", page, re.S)
    if not m:
        return []
    cols = _map_columns(m.group())
    if "kcal" not in cols or "protein_g" not in cols:
        return []
    body = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", page, re.S)
    if not body:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    section: str | None = None
    serving = "per serving"
    # Match the whole <tr …>…</tr> so the class attribute stays visible.
    for tr in re.findall(r"<tr\b[^>]*>.*?</tr>", body.group(1), re.S):
        if "subCategory" in tr.split(">", 1)[0]:
            h3 = re.search(r"<h3\b[^>]*>(.*?)</h3>", tr, re.S)
            note = re.search(r"<p\b[^>]*>(.*?)</p>", tr, re.S)
            section = _text(h3.group(1)) if h3 else None
            serving = (_text(note.group(1)) if note else "") or "per serving"
            continue
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) <= max(cols["kcal"], cols["protein_g"]):
            continue
        name = _text(cells[0])
        name = re.sub(r"\s*\[?more info\]?\s*$", "", name, flags=re.I).strip()
        kcal = _number(cells[cols["kcal"]])
        protein = _number(cells[cols["protein_g"]])
        if not name or kcal is None or protein is None:
            continue
        if kcal <= 0 or protein < 0:
            continue
        if protein * 4 > kcal * 1.15:
            continue
        # Fold the basis into the name when it is a slice, not a whole item.
        label = name
        if "slice" in serving.lower() and "slice" not in name.lower():
            label = f"{name} — per slice"
        if label.lower() in seen:
            continue
        seen.add(label.lower())
        extra = {}
        for field in ("fat_g", "carbs_g"):
            idx = cols.get(field)
            if idx is not None and idx < len(cells):
                extra[field] = _number(cells[idx])
        out.append(item(CHAIN, label, SOURCE, SOURCE_URL,
                        item_id=label, category=section,
                        serving_desc=serving,
                        kcal=kcal, protein_g=protein, **extra))
    return out


def fetch() -> list[dict]:
    r = fetch_protected(SOURCE_URL, timeout=90, referer=REFERER)
    if r is None:
        return []
    return _parse(r.text)
