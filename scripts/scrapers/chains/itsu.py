"""itsu — per-product macros from the per-item nutrition-facts pages.

Discovery
---------
itsu.com/menu/ is a server-rendered Nuxt page. It lists every product but
shows CALORIES ONLY ("32 kcal") on the listing cards — reading only that page
is how you conclude itsu publishes no protein. Each product's own page carries
the full panel:

    https://www.itsu.com/menu/<category>/<slug>/

    <dl class="nutrition-facts">
      <dt class="fact-title">energy (kcal)</dt><dd class="fact-description">137</dd>
      <dt class="fact-title">fat (g)</dt>      <dd class="fact-description">3.9</dd>
      <dt>of which saturates (g)</dt> <dt>protein (g)</dt>
      <dt>carbohydrates (g)</dt> <dt>of which sugars (g)</dt>
      <dt>fibre (g)</dt> <dt>salt (g)</dt> <dt>plant points</dt>

So this adapter is two-stage: scrape the product URLs off /menu/, then fetch
each product page. That is ~120 requests, run on a small thread pool.

Traps
-----
* Names are lower-case by brand style ("miso soup") — that is the source's
  own casing, not a parsing artefact, so it is preserved.
* Match nutrient labels exactly, not by prefix: "fat (g)" and "of which
  saturates (g)" both contain "fat"-ish text, and "carbohydrates (g)" vs
  "of which sugars (g)" need to stay distinct.
* Product URLs carry a date-ish suffix (``-120925``) that itsu rotates when a
  recipe changes, so the slugs must be re-read from /menu/ each run rather
  than cached in code.
"""
from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor

from ..base import fetch_protected, item, session

CHAIN = "itsu"
SOURCE = "brand site (itsu per-product nutrition facts)"
SOURCE_URL = "https://www.itsu.com/menu/"
BASE = "https://www.itsu.com"

_TAG = re.compile(r"<[^>]+>")
_PRODUCT_LINK = re.compile(r'href="(/menu/[^"?#]+/[^"?#]+/)"')
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_FACT = re.compile(
    r'<dt class="fact-title[^"]*"[^>]*>(.*?)</dt>\s*'
    r'<dd class="fact-description"[^>]*>(.*?)</dd>', re.S)

#: Exact fact label (normalized) -> field.
_FIELDS = {
    "energy (kcal)": "kcal",
    "protein (g)": "protein_g",
    "carbohydrates (g)": "carbs_g",
    "fat (g)": "fat_g",
    "salt (g)": "salt_g",
    "fibre (g)": "fibre_g",
    "of which sugars (g)": "sugars_g",
    "of which saturates (g)": "sat_g",
}
#: Keep the request burst polite; itsu is a small site.
WORKERS = 8


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).replace("\xa0", " ").split())


def _get(url: str, timeout: int = 60) -> str | None:
    s = session()
    try:
        r = s.get(url, timeout=timeout)
        if r.status_code == 200 and r.content:
            return r.content.decode(r.encoding or "utf-8", errors="replace")
    except Exception:
        pass
    pr = fetch_protected(url, timeout=timeout + 30)
    if pr is not None and pr.content:
        return pr.content.decode("utf-8", errors="replace")
    return None


def _product_urls(listing: str) -> list[str]:
    seen: list[str] = []
    for path in _PRODUCT_LINK.findall(listing):
        url = BASE + path
        if url not in seen:
            seen.append(url)
    return seen


def _parse_product(url: str) -> dict | None:
    body = _get(url)
    if not body:
        return None
    title = _H1.search(body)
    name = _text(title.group(1)) if title else ""
    if not name:
        return None

    rec: dict = {"name": name, "url": url}
    for label, value in _FACT.findall(body):
        key = _text(label).lower()
        field = _FIELDS.get(key)
        if not field:
            continue
        m = re.search(r"-?\d+(?:\.\d+)?", _text(value).replace(",", ""))
        if m:
            rec[field] = float(m.group(0))

    # Category is the first path segment under /menu/.
    parts = [p for p in url[len(BASE):].strip("/").split("/") if p]
    if len(parts) >= 2:
        rec["category"] = parts[1].replace("-", " ")
    return rec


def fetch() -> list[dict]:
    listing = _get(SOURCE_URL, timeout=90)
    if not listing:
        return []
    urls = _product_urls(listing)
    if not urls:
        return []

    with ThreadPoolExecutor(WORKERS) as pool:
        records = [r for r in pool.map(_parse_product, urls) if r]

    out: list[dict] = []
    seen: set[str] = set()
    for rec in records:
        name = rec.get("name")
        kcal = rec.get("kcal")
        protein = rec.get("protein_g")
        # Plausibility gate: reject rows missing a name, kcal or protein, and
        # rows where protein alone would exceed the stated calories.
        if not name or not kcal or protein is None:
            continue
        if kcal <= 0 or protein < 0 or protein * 4 > kcal * 1.15:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item(
            CHAIN, name, SOURCE, rec["url"],
            item_id=name,
            category=rec.get("category"),
            serving_desc="per portion",
            kcal=kcal,
            protein_g=protein,
            carbs_g=rec.get("carbs_g"),
            fat_g=rec.get("fat_g"),
            salt_g=rec.get("salt_g"),
        ))
    return out
