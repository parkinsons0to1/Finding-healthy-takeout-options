"""JD Wetherspoon — per-item macros from the allergens/nutrition JSON API.

Discovery
---------
jdwetherspoon.com/food/menu 301s to https://allergens.jdwetherspoon.com/,
which is a Vite single-page app: the served HTML is an empty
``<div id="root">`` with no nutrition in it at all. The data comes from an
API whose config is hard-coded in the JS bundle referenced by that page
(``/assets/index-<hash>.js``)::

    const pn = {
      apiPath: "https://ca.jdw-apps.net",
      pubsPath: "api/allergens/v0.1/jdw/venues/{pubId}",
      foodPath: "api/allergens/v0.1/jdw/venues/{pubId}/food",
      foodCategoriesPath: "api/allergens/v0.1/jdw/food-categories",
      drinksPath: "api/allergens/v0.1/jdw/drinks",
      drinkCategoriesPath: "api/allergens/v0.1/jdw/drink-categories",
      allergensPath: "api/allergens/v0.1/jdw",
      apiKey: () => "1|SFS9MMnn5deflq0BMcUTSijwSMBB4mc7NSG2rOhqb2765466"
    }

The same bundle shows the key is sent as ``Authorization: Bearer <key>``
(``defaultHeaders = {"Content-Type": "application/json",
Authorization: "Bearer " + n}``).

Each food record carries name, summary, ingredients, allergens, calories,
protein, fat, saturated_fat, carbohydrates, sugar, fibre, salt and
vegetarians/vegans booleans — a complete macro set, no PDF needed.

Traps
-----
* The menu is fetched *per venue*, and many venue ids return an empty
  ``data`` array (they carry no menu of their own). Probing a fixed id and
  reporting "0 items" would look like a broken API rather than a bad id, so
  ``fetch()`` walks a list of known-good ids until one returns a menu.
* ``category``/``sub_category`` are numeric ids; the human-readable names come
  from the separate ``/food-categories`` endpoint, which nests sub-categories
  inside each top-level category.
"""
from __future__ import annotations

from ..base import item, session

CHAIN = "wetherspoons"
SOURCE = "brand API (JD Wetherspoon allergens & nutrition)"
API_ROOT = "https://ca.jdw-apps.net/api/allergens/v0.1/jdw"

#: Static public key embedded in the allergens.jdwetherspoon.com web bundle
#: (/assets/index-<hash>.js). It is shipped to every browser that loads the
#: page, so it is not a secret — but it is also not guaranteed stable: JDW can
#: rotate it whenever they redeploy, and the bundle hash changes with it. If
#: this adapter starts returning 401/403, re-read the current bundle from
#: https://allergens.jdwetherspoon.com/ and lift the new `apiKey` value.
API_KEY = "1|SFS9MMnn5deflq0BMcUTSijwSMBB4mc7NSG2rOhqb2765466"

#: Venue ids observed to serve the full national food menu. Many ids return an
#: empty list, so try in order and take the first that answers with items.
VENUE_IDS = (90, 20, 50, 100, 5, 6283, 200)


def _client():
    s = session()
    s.headers.update({"Authorization": f"Bearer {API_KEY}",
                      "Content-Type": "application/json"})
    return s


def _categories(s) -> dict[int, str]:
    """id -> label, flattening sub-categories into "PARENT / Child"."""
    labels: dict[int, str] = {}
    try:
        data = s.get(f"{API_ROOT}/food-categories", timeout=60).json().get("data") or []
    except Exception:
        return labels
    for cat in data:
        name = (cat.get("display_name") or cat.get("name") or "").strip()
        if cat.get("id") is not None and name:
            labels[cat["id"]] = name
        for sub in cat.get("sub_categories") or []:
            sub_name = (sub.get("display_name") or sub.get("name") or "").strip()
            if sub.get("id") is not None and sub_name:
                labels[sub["id"]] = f"{name} / {sub_name}" if name else sub_name
    return labels


def _venue_food(s) -> tuple[list[dict], str | None]:
    for pub_id in VENUE_IDS:
        url = f"{API_ROOT}/venues/{pub_id}/food"
        try:
            payload = s.get(url, timeout=90).json()
        except Exception:
            continue
        data = payload.get("data") or []
        if data:
            return data, url
    return [], None


def fetch() -> list[dict]:
    s = _client()
    data, source_url = _venue_food(s)
    if not data:
        return []
    labels = _categories(s)

    out: list[dict] = []
    for rec in data:
        name = (rec.get("name") or "").strip()
        kcal = rec.get("calories")
        protein = rec.get("protein")
        # Plausibility gate: reject rows missing a name, kcal or protein, and
        # rows where protein alone would exceed the stated calories.
        if not name or kcal is None or protein is None:
            continue
        try:
            kcal, protein = float(kcal), float(protein)
        except (TypeError, ValueError):
            continue
        if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
            continue

        category = labels.get(rec.get("sub_category")) or labels.get(rec.get("category"))
        out.append(item(
            CHAIN, name, SOURCE, source_url,
            item_id=str(rec.get("dish_ref") or rec.get("id") or name),
            category=category,
            serving_desc=(rec.get("summary") or "").strip() or None,
            kcal=kcal,
            protein_g=protein,
            carbs_g=rec.get("carbohydrates"),
            fat_g=rec.get("fat"),
            salt_g=rec.get("salt"),
            vegetarian=rec.get("vegetarians"),
            vegan=rec.get("vegans"),
        ))
    return out
