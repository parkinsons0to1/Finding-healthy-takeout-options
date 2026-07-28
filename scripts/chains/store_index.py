"""National per-chain store indexes: slug -> location (+ halal, where published).

This layer exists so MacroMeter works **wherever the user is**, not just where
a developer hardcoded a slug. The flow for any postcode is:

    postcode -> lat/lng (postcodes.io)
             -> nearby outlets (FSA FHRS, chain-agnostic)
             -> match each outlet to that chain's own store record BY DISTANCE
             -> per-outlet halal/price/menu lookups keyed on the matched store

Building the index is a one-off national crawl per chain, cached in
``data/db/store_index_{chain}.json`` and refreshed on a schedule — not
something a user request ever waits for.

KFC is the nice case: its store pages carry latitude/longitude, postcode and
the halal marker, so a single national pass produces the geo index *and* the
halal registry together.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import math
import pathlib
import re

from ..scrapers.base import now_iso, session

DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "db"

KFC_SITEMAP = "https://www.kfc.co.uk/sitemap.xml"
KFC_STORE = "https://www.kfc.co.uk/kfc-near-me/{slug}"
NANDOS_ESTATE = "https://www.nandos.co.uk/restaurants"
NANDOS_HALAL = "https://www.nandos.co.uk/halal"
POPEYES_RESTAURANTS = ("https://pe-uk-ordering-api-fd-eecsdkg6btfeg0cc.z01."
                       "azurefd.net/api/v2/restaurants")

_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})\b")


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- KFC

def _kfc_store(s, slug: str) -> dict | None:
    url = KFC_STORE.format(slug=slug)
    try:
        r = s.get(url, timeout=30)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    html = r.text
    lat = re.search(r'"latitude":([-\d.]+)', html)
    lng = re.search(r'"longitude":([-\d.]+)', html)
    pc = _POSTCODE.search(html)
    return {
        "chain_id": "kfc", "slug": slug, "url": url,
        "lat": float(lat.group(1)) if lat else None,
        "lng": float(lng.group(1)) if lng else None,
        "postcode": pc.group(1) if pc else None,
        # Same fetch also settles halal — see halal/sources/kfc_store_pages.py
        "halal": "100% halal certified" in html.lower(),
    }


def build_kfc(s=None, limit: int = 0, workers: int = 8) -> dict:
    s = s or session()
    xml = s.get(KFC_SITEMAP, timeout=40).text
    slugs = sorted({m for m in re.findall(
        r"<loc>https://www\.kfc\.co\.uk/kfc-near-me/([^<]+)</loc>", xml)
        if not m.startswith("lab")})
    if limit:
        slugs = slugs[:limit]
    stores = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        for rec in ex.map(lambda sl: _kfc_store(s, sl), slugs):
            if rec and rec["lat"] is not None:
                stores[rec["slug"]] = rec
    return {"chain_id": "kfc", "built_at": now_iso(),
            "store_count": len(stores), "stores": stores}


# ---------------------------------------------------------------- Nando's

def build_nandos(s=None) -> dict:
    s = s or session()
    estate_html = s.get(NANDOS_ESTATE, timeout=60).text.replace('\\"', '"')
    halal_html = s.get(NANDOS_HALAL, timeout=40).text.replace('\\"', '"')

    halal_slugs = set(re.findall(r"/restaurants/([a-z0-9-]+)", halal_html))
    # Each card: href=/restaurants/{slug} ... <h5>Name</h5> ... postcode
    stores = {}
    for m in re.finditer(
            r'href="/restaurants/([a-z0-9-]+)"[^>]*>\s*<h5[^>]*>(.*?)</h5>(.{0,1200}?)</address>',
            estate_html, re.S):
        slug, name, tail = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip(), m.group(3)
        pc = _POSTCODE.search(re.sub(r"<[^>]+>", " ", tail))
        if slug in stores:
            continue
        stores[slug] = {"chain_id": "nandos", "slug": slug, "name": name,
                        "postcode": pc.group(1) if pc else None,
                        "url": f"https://www.nandos.co.uk/restaurants/{slug}",
                        "halal": slug in halal_slugs, "lat": None, "lng": None}
    # Slugs seen only in link form still matter for halal resolution.
    for slug in re.findall(r"/restaurants/([a-z0-9-]+)", estate_html):
        stores.setdefault(slug, {
            "chain_id": "nandos", "slug": slug, "name": slug.replace("-", " ").title(),
            "postcode": None, "url": f"https://www.nandos.co.uk/restaurants/{slug}",
            "halal": slug in halal_slugs, "lat": None, "lng": None})
    return {"chain_id": "nandos", "built_at": now_iso(),
            "store_count": len(stores), "halal_count": len(halal_slugs),
            "stores": stores}


# ---------------------------------------------------------------- Popeyes

def build_popeyes(s=None) -> dict:
    s = s or session()
    data = s.get(POPEYES_RESTAURANTS, timeout=40).json()
    stores = {}
    for r in data.get("data", []):
        coords = (r.get("storeLocation") or {}).get("coordinates") or {}
        slug = r.get("slug") or r.get("id")
        addr = r.get("storeAddress") or ""
        pc = _POSTCODE.search(addr)
        stores[slug] = {"chain_id": "popeyes", "slug": slug, "store_id": r.get("id"),
                        "name": r.get("storeName"), "address": addr,
                        "postcode": pc.group(1) if pc else None,
                        "lat": coords.get("latitude"), "lng": coords.get("longitude"),
                        "halal": True}  # chain-wide policy; see chain_policy.py
    return {"chain_id": "popeyes", "built_at": now_iso(),
            "store_count": len(stores), "stores": stores}


BUILDERS = {"kfc": build_kfc, "nandos": build_nandos, "popeyes": build_popeyes}


# ---------------------------------------------------------------- use

def path_for(chain_id: str) -> pathlib.Path:
    return DB / f"store_index_{chain_id}.json"


def save(index: dict) -> pathlib.Path:
    DB.mkdir(parents=True, exist_ok=True)
    p = path_for(index["chain_id"])
    p.write_text(json.dumps(index, indent=1))
    return p


def load(chain_id: str) -> dict | None:
    p = path_for(chain_id)
    return json.loads(p.read_text()) if p.exists() else None


def nearest_store(chain_id: str, lat: float, lng: float,
                  max_km: float = 1.5) -> dict | None:
    """The chain's own store record closest to a point, if within max_km.

    This is what replaces hardcoded slugs: give it where the user actually is
    and it finds that chain's branch there, anywhere in the country.
    """
    idx = load(chain_id)
    if not idx:
        return None
    best, best_d = None, None
    for rec in idx["stores"].values():
        if rec.get("lat") is None or rec.get("lng") is None:
            continue
        d = haversine_km(lat, lng, rec["lat"], rec["lng"])
        if best_d is None or d < best_d:
            best, best_d = rec, d
    if best is None or best_d > max_km:
        return None
    return {**best, "distance_km": round(best_d, 3)}


def find_by_postcode(chain_id: str, postcode: str) -> dict | None:
    """Fallback match for chains whose index has postcodes but not coordinates."""
    idx = load(chain_id)
    if not idx:
        return None
    want = postcode.replace(" ", "").upper()
    for rec in idx["stores"].values():
        pc = (rec.get("postcode") or "").replace(" ", "").upper()
        if pc and pc == want:
            return rec
    return None
