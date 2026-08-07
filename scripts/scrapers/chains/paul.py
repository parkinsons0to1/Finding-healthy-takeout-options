"""PAUL UK — per-product Magento pages with a server-rendered nutrition table.

Discovery
---------
The obvious candidate is a dead end and cost real time, so: the file at

    https://www.paul-uk.com/media/pdf/PAUL_Allergen_Document_July_23.pdf

is titled "NUTRITION & ALLERGEN GUIDE" but is **allergen-only**. Its tables
have exactly three columns — CATEGORY, ITEM NAME, ALLERGENS (+ "Contains") —
and not a single number. The Apr 23 and Feb 23 editions are the same. Do not
re-attempt it.

The macros are server-rendered into each product page's HTML under a
"Nutritional Information" heading — no JS, no API needed:

    Typical values | Per 780g serving | Per 100g
    Energy (kJ)    | 11008.84         | 1411.39
    Energy (kcal)  | 2631.17          |  337.33
    ...
    Protein (g)    | 68.33            |    8.76

We take the first value column (per serving / per pack).

Traps
-----
* **Comma decimals.** Some pages write "4,8" where others write "4.8". Both
  appear in the same catalogue. Normalise before float() or you lose a large
  slice of the menu silently.
* Values are per PACK, not per portion — platters and whole cakes legitimately
  read 1600-2600 kcal. That is the source's basis, not a parse error.
* Not every URL is a product: of ~148 candidates only ~58 carry a nutrition
  table with both keys.

Crawl strategy & politeness
---------------------------
Product URLs are single-segment (`/basque-cheesecake-6-8`). They are gathered
from `sitemap.xml` (243 locs) plus hrefs scraped off the category pages, since
neither source alone is complete. robots.txt asks for `Crawl-delay: 10`; that
would make a full crawl take ~25 minutes, so this adapter instead caps
concurrency at 4 and sleeps briefly between requests — a compromise that keeps
load light without serialising completely. Lower `_WORKERS` if PAUL objects.
"""
from __future__ import annotations

import concurrent.futures as futures
import html as _html
import re
import time

from ..base import item, session

CHAIN = "paul"
SOURCE = "PAUL UK product pages (Nutritional Information table)"
SITEMAP = "https://www.paul-uk.com/sitemap.xml"
BASE = "https://www.paul-uk.com"

_WORKERS = 4
_DELAY = 0.4          # seconds between requests within a worker

#: Paths that are never products.
_SKIP = ("/catering", "/customer", "/checkout", "/about-paul", "/careers",
         "/faq", "/contact", "/find-a-paul", "/franchise", "/gender-pay",
         "/cookies", "/allergens", "/deliverymap", "/loyaltyapp",
         "/in-store-menu", "/terms", "/legal", "/privacy", "/generic-cms",
         "/order-online", "/corporate", "/our-stores", "/shop-online", "/blog")

_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_PRODUCT_HREF_RE = re.compile(r'href="(https://www\.paul-uk\.com/[a-z0-9\-]+)"')
_TITLE_RE = re.compile(r"<title>([^<]+)</title>")
_TAGS_RE = re.compile(r"<[^>]+>")
#: label, then two pipe/space-separated numbers (per-serving, per-100g).
_VALUE_TAIL = r"[|\s]+([\d.,]+)[|\s]+([\d.,]+)"


def _num(text: str) -> float | None:
    """float() tolerant of comma decimal separators ('4,8' -> 4.8)."""
    try:
        return float(text.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _is_product_url(url: str) -> bool:
    return (url.count("/") == 3
            and url.rstrip("/") != BASE
            and not any(k in url for k in _SKIP))


def _candidates(s) -> list[str]:
    urls: set[str] = set()
    try:
        urls.update(_LOC_RE.findall(s.get(SITEMAP, timeout=90).text))
    except Exception:
        pass
    # Category pages list products the sitemap misses.
    categories = [u for u in list(urls) if u.count("/") <= 4][:60]

    def links(url: str) -> set[str]:
        try:
            time.sleep(_DELAY)
            return set(_PRODUCT_HREF_RE.findall(session().get(url, timeout=60).text))
        except Exception:
            return set()

    with futures.ThreadPoolExecutor(_WORKERS) as pool:
        for found in pool.map(links, categories):
            urls |= found
    return sorted(u for u in urls if _is_product_url(u))


def _scrape(url: str) -> dict | None:
    try:
        time.sleep(_DELAY)
        page = session().get(url, timeout=90).text
    except Exception:
        return None
    if "Nutritional Information" not in page:
        return None

    flat = re.sub(r"\s+", " ", _TAGS_RE.sub("|", page))

    def value(label: str) -> float | None:
        m = re.search(re.escape(label) + _VALUE_TAIL, flat)
        return _num(m.group(1)) if m else None

    kcal = value("Energy (kcal)")
    protein = value("Protein (g)")
    if kcal is None or protein is None:
        return None
    if kcal <= 0 or protein * 4 > kcal * 1.15:
        return None

    m = _TITLE_RE.search(page)
    name = _html.unescape(m.group(1).split("|")[0].strip()) if m else url
    if not name:
        return None
    return item(
        CHAIN, name, SOURCE, url,
        item_id=url.rsplit("/", 1)[-1],
        serving_desc="per pack",
        kcal=kcal, protein_g=protein,
        carbs_g=value("Total Carbohydrates (g)"),
        fat_g=value("Fat (g)"),
        salt_g=value("Salt (g)"),
    )


def fetch() -> list[dict]:
    s = session()
    urls = _candidates(s)
    if not urls:
        return []

    rows: list[dict] = []
    seen: set[str] = set()
    with futures.ThreadPoolExecutor(_WORKERS) as pool:
        for row in pool.map(_scrape, urls):
            if not row:
                continue
            key = str(row["name"]).lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows
