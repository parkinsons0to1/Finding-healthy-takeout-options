"""McDonald's UK — server-rendered menu pages + public dnaapp JSON API.

Discovery notes (2026-07-28):
  * Menu category pages embed data-product-id attributes.
  * https://www.mcdonalds.com/dnaapp/itemDetails?country=UK&language=en
    &showLiveData=true&item={id} returns full nutrient facts per item.
"""
from __future__ import annotations

import concurrent.futures as cf
import re

from .base import item, session, to_float

MENU_PAGES = [
    "https://www.mcdonalds.com/gb/en-gb/menu/burgers.html",
    "https://www.mcdonalds.com/gb/en-gb/menu/chicken-and-nuggets.html",
    "https://www.mcdonalds.com/gb/en-gb/menu/wraps-and-salads.html",
    "https://www.mcdonalds.com/gb/en-gb/menu/breakfast.html",
    "https://www.mcdonalds.com/gb/en-gb/menu/sides.html",
]
ITEM_API = ("https://www.mcdonalds.com/dnaapp/itemDetails"
            "?country=UK&language=en&showLiveData=true&item={id}")

CHAIN = "mcdonalds"
SOURCE = "live-scrape mcdonalds.com dnaapp API"


def _harvest_ids(s) -> set[str]:
    ids = set()
    for url in MENU_PAGES:
        try:
            html = s.get(url, timeout=25).text
            ids |= set(re.findall(r'data-product-id="(\d+)"', html))
        except Exception as e:
            print(f"  warn: {url}: {e}")
    return ids


def _fetch_item(s, pid):
    url = ITEM_API.format(id=pid)
    d = s.get(url, timeout=25).json()
    it = d.get("item")
    if not it:
        return None
    nut = {n.get("name"): n.get("value")
           for n in it.get("nutrient_facts", {}).get("nutrient", [])}
    name = it.get("item_name") or ""
    return item(
        CHAIN, name, SOURCE, url,
        item_id=str(pid), category=it.get("menu_item_no"),
        kcal=to_float(nut.get("Energy kcal")), protein_g=to_float(nut.get("protein")),
        carbs_g=to_float(nut.get("carbohydrates")), fat_g=to_float(nut.get("fat")),
        salt_g=to_float(nut.get("salt")),
        vegetarian="McPlant" in name or "Veggie" in name,
        vegan="Vegan" in name,
    )


def fetch() -> list[dict]:
    s = session()
    ids = _harvest_ids(s)
    out = []
    with cf.ThreadPoolExecutor(6) as ex:
        for r in ex.map(lambda i: _fetch_item(s, i), sorted(ids)):
            if r and r["kcal"] is not None:
                out.append(r)
    return out
