"""ASK Italian — "Allergen and Nutritional Information Spring/Summer 2026" (PDF).

Discovery
---------
https://www.askitalian.co.uk/allergens (needs ``fetch_protected``) links two
Sanity PDFs under ``cdn.sanity.io/files/ysupxjc9/production/``. Note the space
id ``ysupxjc9`` is the SAME one Zizzi uses — both are Azzurri Group brands, so
a search that keys on the CDN path alone will mix the two estates up.

    b6039d51…  main estate, 50 pages   <- this one
    c476e315…  "Concept Stores" menu, 49 pages, same layout

The document is titled "ALLERGEN GUIDE". It is not allergen-only: pages 34+
carry a full per-portion nutrition table. Do not conclude from the title that
ASK publishes allergens only.

TRAP 1 — ``generic_pdf`` silently produces GARBAGE here, it does not fail
    ``parse_pdf`` returns 29 rows whose "names" are menu-section headings
    ("Summer Specials", "Bread & Nibbles", "Starters") with numbers attached.
    That looks like a small-but-working result and is the most dangerous
    failure mode in this file. Cause: the nutrition tables are drawn without
    ruling lines, so ``page.extract_tables()`` cannot see them and latches onto
    unrelated decorative boxes. Everything here is parsed from word geometry
    instead.

TRAP 2 — the layout has THREE column zones, found from the header row
    The header line reads "Menu Section | Dish Description | Energy …".
    Taking the x0 of the word "Dish" and of the first "Energy" gives two
    boundaries:
        x0 < dish_x        -> Menu Section  (e.g. "Al Forno", "Pizza")
        dish_x <= x0 < num_x -> Dish Description
        x0 >= num_x        -> the numbers
    Splitting on those boundaries is what separates the section from the dish
    name; string-prefix stripping does not work because sections like "Pizza"
    are also the first word of dish names.

TRAP 3 — sixteen numbers per row, per-100g FIRST
    Each data row carries 16 values: indices 0-7 are Per 100g
    (kJ, kcal, fat, saturates, carbohydrate, sugar, protein, salt) and indices
    8-15 repeat them Per Portion. Per-portion kcal is index 9 and per-portion
    protein is index 14. A row with any other count is not a dish row and is
    skipped rather than padded.

TRAP 4 — long dish names wrap onto the following line
    "Non Gluten Prosciutto, Truffle &" / "Stracciatella Pizza" is one dish. A
    wrapped line is recognisable as: words only in the dish zone, nothing in
    the section zone, and no numbers. Such a line is appended to the previous
    row's name. Page footers ("These figures are approximate…") start in the
    section zone, so requiring an EMPTY section zone is what keeps boilerplate
    out of dish names.

Values are per portion. Some are large because ASK portions are whole dishes
(e.g. Fiery Trio di Carne pizza = 1193 kcal / 50 g protein).
"""
from __future__ import annotations

import io
import re

from ..base import fetch_protected, item, session, to_float

CHAIN = "ask_italian"
SOURCE = "ASK Italian Allergen and Nutritional Information Spring/Summer 2026 V2"
SOURCE_URL = ("https://cdn.sanity.io/files/ysupxjc9/production/"
              "b6039d513237130ab53a1ddc01afb713d1aa7dde.pdf")

#: Per-portion positions inside the 16-number run.
_KCAL_IDX, _PROTEIN_IDX = 9, 14
_FAT_IDX, _CARB_IDX, _SALT_IDX = 10, 12, 15

_NUM = re.compile(r"^<?\d+(?:\.\d+)?$")


def _fetch_pdf(url: str) -> bytes | None:
    try:
        r = session().get(url, timeout=90)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    pr = fetch_protected(url, timeout=120)
    if pr is not None and pr.content[:4] == b"%PDF":
        return pr.content
    return None


def _lines(page):
    """Words grouped into visual lines, each sorted left to right."""
    buckets: dict[int, list] = {}
    for w in page.extract_words():
        buckets.setdefault(round(w["top"] / 3.0), []).append(w)
    for key in sorted(buckets):
        yield sorted(buckets[key], key=lambda w: w["x0"])


def _boundaries(page):
    """(dish_x, num_x) from the header row, or None if this page has no table."""
    for line in _lines(page):
        texts = [w["text"] for w in line]
        if "Dish" in texts and "Energy" in texts:
            dish_x = next(w["x0"] for w in line if w["text"] == "Dish")
            num_x = next(w["x0"] for w in line if w["text"] == "Energy")
            if num_x > dish_x:
                return dish_x, num_x
    return None


def _parse(raw: bytes) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            bounds = _boundaries(page)
            if not bounds:
                continue
            dish_x, num_x = bounds
            last: dict | None = None
            for line in _lines(page):
                sect_w = [w for w in line if w["x0"] < dish_x - 5]
                dish_w = [w for w in line if dish_x - 5 <= w["x0"] < num_x - 5]
                num_w = [w for w in line if w["x0"] >= num_x - 5]
                nums = [w["text"] for w in num_w]
                if not dish_w:
                    continue
                if not nums:
                    # Possible wrapped continuation of the previous dish name.
                    if last is not None and not sect_w:
                        cont = " ".join(w["text"] for w in dish_w).strip()
                        if cont and not cont.lower().startswith("dish"):
                            last["name"] = f"{last['name']} {cont}".strip()
                            last["item_id"] = last["name"]
                    continue
                if len(nums) != 16 or not all(_NUM.match(n) for n in nums):
                    continue
                vals = [to_float(n.lstrip("<")) for n in nums]
                name = " ".join(w["text"] for w in dish_w).strip()
                category = " ".join(w["text"] for w in sect_w).strip() or None
                kcal, protein = vals[_KCAL_IDX], vals[_PROTEIN_IDX]
                if not name or kcal is None or protein is None:
                    continue
                if kcal <= 0 or protein < 0:
                    continue
                if protein * 4 > kcal * 1.15:
                    continue
                key = f"{category}|{name}".lower()
                if key in seen:
                    continue
                seen.add(key)
                row = item(CHAIN, name, SOURCE, SOURCE_URL,
                           item_id=name, category=category,
                           serving_desc="per serving",
                           kcal=kcal, protein_g=protein,
                           fat_g=vals[_FAT_IDX], carbs_g=vals[_CARB_IDX],
                           salt_g=vals[_SALT_IDX])
                out.append(row)
                last = row
    return out


def fetch() -> list[dict]:
    raw = _fetch_pdf(SOURCE_URL)
    if raw is None:
        return []
    return _parse(raw)
