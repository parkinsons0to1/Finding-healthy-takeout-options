"""Costa Coffee UK — the site's own nutrition GraphQL API.

Discovery: costa.co.uk publishes four PDFs from /nutrition, and none of them is
the in-store nutrition table — the store guide is an allergen matrix, the
"branded" and "at home" guides cover packaged third-party lines, and the
Express guide covers self-serve machines. The macros the website itself shows
on every product tile come from an API instead: the Gatsby bundle
(/app-*.js) maps the "nutrition" service to ``/api/mdm/`` in production and
carries the two GraphQL documents it posts there —
``WebProductsAndMasterProducts`` (the menu tree, giving each product's
groupCode) and ``MasterProduct`` (nutrition for a batch of groupCodes).

Format: JSON over POST, no auth, but the host fingerprints TLS, so plain
`requests` times out and the call goes through `fetch_protected`'s browser
impersonation.

Shape notes:
* every product has one `nutritionProducts` entry per variation combination
  (size x milk x coffee type x Eat In/Takeaway) — a latte alone is ~40 rows.
  Eat In duplicates Takeaway, so only Takeaway/unset rows are kept.
* `nutritionPerPortion` is what we want; `nutritionPer100g` also exists and
  mixing them would silently halve the food numbers.
* absent variation values arrive as the strings "NA"/"None", which land in the
  display name as "Latte - NA - None" unless filtered.
"""
from __future__ import annotations

import json

from ..base import fetch_protected, item

CHAIN = "costa"
SOURCE = "brand API (costa.co.uk /api/mdm GraphQL)"
SOURCE_URL = "https://www.costa.co.uk/api/mdm/"

_TREE_QUERY = """query WebProductsAndMasterProducts {
  webProductTypes { items { name webProductCategories { name
    masterProducts { isActive groupCode } } } } }"""

_PRODUCT_QUERY = """query MasterProduct {
  masterProducts(groupCodes: [%s], effectiveFromDate: null) {
    items {
      productDisplayName
      groupCode
      nutritionProducts {
        variations { coffeeType milkType serviceDelivery size }
        dietaryChoices { suitableForVegetarians suitableForVegans }
        nutritionPerPortion {
          portionWeight carbohydrates energykCal fat fibre protein salt
        }
      }
    }
  }
}"""

_BATCH = 40
#: Variation values that mean "not applicable" rather than a real option.
_EMPTY = {"", "na", "n/a", "none", "null"}


def _post(query: str) -> dict | None:
    """POST a GraphQL document through browser-impersonated TLS."""
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        return None

    import os
    kwargs = {"timeout": 120}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(ca):
        kwargs["verify"] = ca
    headers = {"Content-Type": "application/json",
               "Origin": "https://www.costa.co.uk",
               "Referer": "https://www.costa.co.uk/menu"}

    for profile in ("safari", "chrome", "edge"):
        try:
            r = cffi.post(SOURCE_URL, json={"query": query},
                          impersonate=profile, headers=headers, **kwargs)
            if r.status_code == 200:
                return (r.json() or {}).get("data")
        except Exception:
            continue
    return None


def _menu_tree() -> dict[str, str]:
    """groupCode -> "Type / Category" for every active product."""
    data = _post(_TREE_QUERY)
    if not data:
        return {}
    cats: dict[str, str] = {}
    for ptype in data.get("webProductTypes", {}).get("items") or []:
        for cat in ptype.get("webProductCategories") or []:
            for mp in cat.get("masterProducts") or []:
                if mp.get("isActive") and mp.get("groupCode"):
                    cats[mp["groupCode"]] = f'{ptype["name"]} / {cat["name"]}'
    return cats


def _variant_name(base: str, variations: dict) -> str:
    parts = [base]
    for key in ("size", "milkType", "coffeeType"):
        value = variations.get(key)
        if value and str(value).strip().lower() not in _EMPTY:
            parts.append(str(value).strip())
    return " - ".join(parts)


def fetch() -> list[dict]:
    cats = _menu_tree()
    codes = sorted(cats)
    out: list[dict] = []
    seen: set[str] = set()

    for start in range(0, len(codes), _BATCH):
        chunk = codes[start:start + _BATCH]
        query = _PRODUCT_QUERY % ",".join(json.dumps(c) for c in chunk)
        data = _post(query)
        if not data:
            continue
        for mp in (data.get("masterProducts") or {}).get("items") or []:
            base = (mp.get("productDisplayName") or "").strip()
            if not base:
                continue
            category = cats.get(mp.get("groupCode") or "")
            for np in mp.get("nutritionProducts") or []:
                variations = np.get("variations") or {}
                if variations.get("serviceDelivery") == "Eat In":
                    continue          # duplicate of the Takeaway row
                n = np.get("nutritionPerPortion") or {}
                kcal, protein = n.get("energykCal"), n.get("protein")
                if kcal is None or protein is None:
                    continue
                try:
                    kcal, protein = float(kcal), float(protein)
                except (TypeError, ValueError):
                    continue
                if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
                    continue          # missing or misread macros
                name = _variant_name(base, variations)
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                diet = np.get("dietaryChoices") or {}
                weight = n.get("portionWeight")
                out.append(item(
                    CHAIN, name, SOURCE, SOURCE_URL, item_id=name,
                    category=category,
                    serving_desc=(f"per portion ({weight}g)" if weight
                                  else "per portion"),
                    kcal=kcal, protein_g=protein,
                    carbs_g=n.get("carbohydrates"), fat_g=n.get("fat"),
                    salt_g=n.get("salt"),
                    vegetarian=diet.get("suitableForVegetarians") == "Yes",
                    vegan=diet.get("suitableForVegans") == "Yes"))
    return out
