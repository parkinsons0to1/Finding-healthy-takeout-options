"""Wetherspoon UK — REAL per-pub prices from Wetherspoon's own public menu PDFs.

WHICH SURFACE — a static per-pub PDF, not the "Order & Pay" app
    Wetherspoon's actual ordering system is the "Order & Pay" app/website
    (`jdwetherspoon.com/order-and-pay-app/`) — investigated first per this
    project's brief, and it needs a customer inside a specific pub (table
    number/QR code) to place a real order, so it is not a usable anonymous
    pricing source. But every pub's own page on the main marketing site
    (`jdwetherspoon.com/pub-menus/<slug>/`) links a "View table menu" PDF —
    `wp-content/uploads/menus/currentmenus/MENU_<id>.pdf` — which is the
    actual current priced, calorie-annotated menu for that specific pub,
    public with no account, no app, no table required. This module reads
    that PDF, not the Order & Pay flow.

Handshake
---------
Plain `requests`, three GETs, no auth, no session:

1. ``GET https://www.jdwetherspoon.com/pub-menus-sitemap.xml`` — every pub's
   menu-page URL (`<loc>https://www.jdwetherspoon.com/pub-menus/<slug>/</loc>`).
   Used by `find_pubs` to resolve a name fragment to a slug; the full list is
   ~3,300 lines and is cached in-process for the run.
2. ``GET https://www.jdwetherspoon.com/pub-menus/<slug>/`` — a plain
   WordPress page; regex out the one `.../currentmenus/MENU_<id>.pdf` link
   (each pub has exactly one, ID unique to that pub's current menu set, e.g.
   The Moon Under Water Enfield is `MENU_24.pdf`, The Moon on the Hill Sutton
   is `MENU_106.pdf` — never hardcode an ID, always resolved fresh per pub).
3. ``GET`` that PDF — a 2-page InDesign-style menu, breakfast/food/drinks
   with kcal and price printed against most (not all — see PARSING SCOPE)
   items.

TRAP — `pdfplumber` (this project's usual PDF library) JUMBLES this PDF; use
       `pypdf` instead, whose plainer text extraction happens to preserve it
    The pub-menu PDF is laid out in two text columns per page. `pdfplumber`'s
    `extract_text()` reconstructs reading order from character *coordinates*,
    which interleaves the two columns mid-sentence — confirmed by inspection,
    its output opens "noitcelloC / htirF / sicnarF" (mirrored fragments) and
    mixes unrelated dishes onto one line ("Five chicken wings 445 kcal 3.15
    Large breakfast 1312 kcal 6.89 American breakfast..."). `pypdf`'s
    `extract_text()` instead walks the PDF content stream's text-showing
    operators in the order they were drawn — which for this WordPress/print
    template is column-by-column, dish-by-dish — and comes out clean:
    "Large breakfast 1312 kcal 6.89" on its own line, matching the printed
    page. `layout=True` mode on `pdfplumber` was also tried and made it
    worse (blank/whitespace-only extraction on this file). This module
    depends on `pypdf` for that reason (see requirements.txt).

PARSING SCOPE — only single-price "Name … N kcal PRICE" rows are read;
    dual-price "meal deal with a drink" rows and per-topping "Add: X (Y kcal)
    PRICE" addon lines are deliberately skipped, not guessed
    The PDF text (after pypdf's extraction) comes out as either one line
    ("Large breakfast 1312 kcal 6.89") or two ("Small breakfast" then " 435
    kcal 3.29" on the next line, when the name itself wrapped) — this module
    handles both shapes, joining the second case onto the immediately
    preceding non-empty line. But `Pub classics` rows print TWO prices side
    by side ("Freshly battered fish and chips 12.19 13.72" — soft-drink-
    included vs alcoholic-drink-included), and no rule in this project's
    house style picks one price to represent the dish without guessing which
    drink the customer meant — those rows do not match the "single price"
    regex and are silently skipped, not mispriced. Likewise "Add: Black
    pudding (67 kcal) 95p" topping lines are toppings, not separately priced
    dishes in the nutrition table, and are skipped the same way.

NAME/KCAL DRIFT — a pub's own printed menu and `data/db/wetherspoons.json`
    (a brand-wide nutrition table) sometimes name-match but calorie-disagree,
    and that is preserved, not corrected
    E.g. this menu's "Spicy chicken" pizza prints 687 kcal; the nutrition
    table's "Spicy chicken" entry is 1373 kcal — almost exactly double,
    consistent with the nutrition table using a different serving size
    (whole vs half, or a different pizza range) to this pub's current
    printed menu. Checked against the PDF itself (not a transcription
    error): 687 kcal is what is printed next to the £7.01 price on this
    pub's own menu. This module emits the pub's own printed number
    unchanged — reconciling it to the nutrition table's serving size would
    be a guess this project's house style avoids (see `costa.py`'s milk
    limitation, `gdk.py`'s granularity gap).

PRICE BASIS — dine-in / table price, not takeaway
    These are the prices printed for ordering at the pub (via app or bar),
    the only price Wetherspoon publishes per-pub. Labelled "collection" for
    consistency with every other adapter's schema (this project's basis enum
    is collection/delivery/estimated/community, and dine-in-at-the-venue is
    closest in kind to a collection price — no delivery or true takeaway
    channel exists for this chain), but it is honestly a pub-till price, not
    a bag-it-and-leave price.

PER PUB
    The Moon on the Hill, Sutton (`the-moon-on-the-hill-sutton`) is the
    default, matching every other adapter's south-London convention — found
    by searching the sitemap for "sutton", the same way `find_pubs` does.
"""
from __future__ import annotations

import io
import re

from ..base import session

CHAIN = "wetherspoons"

SITEMAP_URL = "https://www.jdwetherspoon.com/pub-menus-sitemap.xml"
PUB_PAGE = "https://www.jdwetherspoon.com/pub-menus/{slug}/"

#: The Moon on the Hill, Sutton — matches every other adapter's south-London
#: default.
DEFAULT_PUB_SLUG = "the-moon-on-the-hill-sutton"

_SITEMAP_LOC_RE = re.compile(
    r"<loc>https://www\.jdwetherspoon\.com/pub-menus/([a-z0-9-]+)/</loc>")
_MENU_PDF_RE = re.compile(
    r'href="(https://www\.jdwetherspoon\.com/wp-content/uploads/menus/'
    r'currentmenus/MENU_\d+\.pdf[^"]*)"')

#: "Name … N kcal PRICE" all on one line.
_ITEM_INLINE_RE = re.compile(r"^(.+?)\s+(\d{2,4})\s*kcal\.?\s*(\d{1,2}\.\d{2})$")
#: A bare "N kcal PRICE" line — the name wrapped onto the previous line.
_KCAL_PRICE_ONLY_RE = re.compile(r"^(\d{2,4})\s*kcal\.?\s*(\d{1,2}\.\d{2})$")

_sitemap_cache: list[str] | None = None


def _get(url: str):
    s = session()
    r = s.get(url, timeout=60)
    return r


def _all_pub_slugs() -> list[str]:
    global _sitemap_cache
    if _sitemap_cache is not None:
        return _sitemap_cache
    r = _get(SITEMAP_URL)
    if r.status_code != 200:
        raise RuntimeError(f"wetherspoons: sitemap HTTP {r.status_code}")
    slugs = _SITEMAP_LOC_RE.findall(r.text)
    if not slugs:
        raise RuntimeError("wetherspoons: sitemap had no pub-menu URLs — "
                           "the sitemap shape has moved")
    _sitemap_cache = slugs
    return slugs


def find_pubs(query: str) -> list[str]:
    """Pub-menu slugs whose URL contains `query` (case-insensitive), e.g.
    a town or pub-name fragment — "sutton" -> "the-moon-on-the-hill-sutton"
    among others. Not a geocoded nearest-pub search (Wetherspoon publishes
    no public postcode-search API); a substring match over the sitemap."""
    q = query.strip().lower().replace(" ", "-")
    return [s for s in _all_pub_slugs() if q in s]


def _menu_pdf_url(slug: str) -> str:
    r = _get(PUB_PAGE.format(slug=slug))
    if r.status_code == 404:
        raise RuntimeError(f"wetherspoons: no pub-menu page for slug {slug!r}")
    if r.status_code != 200:
        raise RuntimeError(f"wetherspoons: pub page HTTP {r.status_code} "
                           f"for {slug!r}")
    m = _MENU_PDF_RE.search(r.text)
    if not m:
        raise RuntimeError(f"wetherspoons: no currentmenus PDF link found "
                           f"for {slug!r} — the page template has moved")
    return m.group(1)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """pypdf's linear text extraction — see the module docstring's trap for
    why pdfplumber (this project's usual PDF library) is not used here."""
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_items(text: str) -> list[tuple[str, float, float]]:
    """[(name, kcal, price_gbp), ...] for every single-price row. See the
    module docstring's PARSING SCOPE for what is deliberately skipped."""
    items: list[tuple[str, float, float]] = []
    prev_line: str | None = None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = _ITEM_INLINE_RE.match(line)
        if m:
            name = m.group(1).strip()
            if name:
                items.append((name, float(m.group(2)), float(m.group(3))))
            prev_line = None
            continue
        m2 = _KCAL_PRICE_ONLY_RE.match(line)
        if m2 and prev_line:
            items.append((prev_line, float(m2.group(1)), float(m2.group(2))))
            prev_line = None
            continue
        prev_line = line
    return items


def fetch_prices(pub_slug: str | None = None, query: str | None = None) -> list[dict]:
    """Priced menu for one Wetherspoon pub, read from its own menu PDF.

    Give a `pub_slug` (from `find_pubs`, or the tail of a
    `jdwetherspoon.com/pub-menus/<slug>/` URL), or a `query` substring to
    resolve one via the sitemap. Every row is labelled "collection" — see
    the module docstring's PRICE BASIS note, this is a dine-in/table price.
    """
    if pub_slug is None and query:
        found = find_pubs(query)
        if not found:
            raise RuntimeError(f"wetherspoons: no pub-menu slug matched "
                               f"{query!r}")
        pub_slug = found[0]
    slug = pub_slug or DEFAULT_PUB_SLUG

    pdf_url = _menu_pdf_url(slug)
    r = _get(pdf_url)
    if r.status_code != 200:
        raise RuntimeError(f"wetherspoons: menu PDF HTTP {r.status_code} "
                           f"for {slug!r} ({pdf_url})")
    text = _extract_pdf_text(r.content)
    if not text.strip():
        raise RuntimeError(f"wetherspoons: menu PDF for {slug!r} extracted "
                           f"no text — the PDF shape has moved, not that "
                           f"the pub has no menu")

    label = slug.replace("-", " ").strip().title()
    items = _parse_items(text)
    if not items:
        raise RuntimeError(f"wetherspoons: menu PDF for {slug!r} had text "
                           f"but no rows matched the 'Name N kcal PRICE' "
                           f"pattern — the template has moved")

    out: list[dict] = []
    seen: set[str] = set()
    for name, kcal, price in items:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "price_gbp": round(price, 2),
                    "basis": "collection", "store": label,
                    "category": None, "kcal": kcal})
    return out


if __name__ == "__main__":  # pragma: no cover
    rows = fetch_prices()
    print(f"{len(rows)} items @ {rows[0]['store']}")
    for row in rows:
        print(f"{row['price_gbp']:>7.2f}  [{row['basis']}] {row['name']} "
             f"({row['kcal']} kcal)")
