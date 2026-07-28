"""Location entry and outlet discovery — for anywhere in the UK.

Nothing here is tied to a particular town. Give it a postcode (typed by the
user) or a lat/lng (from the browser's Geolocation API, which on iOS Safari is
backed by Apple's Core Location), and it returns the food outlets around that
point using the FSA's national Food Hygiene Rating register.

FHRS is the right discovery backbone because it is chain-agnostic and covers
every food business in the UK: independents show up alongside chains, which is
what Phase 4's photo/OCR ingestion will need. Chain identification is then a
matching step on top, not a hardcoded list of shops.
"""
from __future__ import annotations

import re

from ..scrapers.base import session

POSTCODES_API = "https://api.postcodes.io/postcodes/{postcode}"
POSTCODES_REVERSE = "https://api.postcodes.io/postcodes"
FHRS_API = "https://api.ratings.food.gov.uk/Establishments"
FHRS_HEADERS = {"x-api-version": "2", "Accept": "application/json"}

#: FHRS business types worth searching for takeaway/restaurant food.
FHRS_TYPES = {
    "takeaway": 7844,
    "restaurant_cafe": 1,
    "retailer_other": 4613,
    "supermarket": 7840,
    "retailer_small": 7843,
    "mobile_caterer": 7846,
}

#: Name fragment -> our chain id. Ordered so longer/more specific wins.
CHAIN_PATTERNS: list[tuple[str, str]] = [
    (r"german doner|gdk\b", "gdk"),
    (r"burger king", "burger_king"),
    (r"taco bell", "taco_bell"),
    (r"pret a manger", "pret"),
    (r"nando", "nandos"),
    (r"mcdonald", "mcdonalds"),
    (r"popeyes", "popeyes"),
    (r"\bkfc\b|kentucky fried", "kfc"),
    (r"subway", "subway"),
    (r"greggs", "greggs"),
    (r"morley", "morleys"),
    (r"kokoro", "kokoro"),
    (r"\btesco\b", "tesco"),
    (r"sainsbury", "sainsburys"),
    (r"\basda\b", "asda"),
    (r"\blidl\b", "lidl"),
    (r"\baldi\b", "aldi"),
    (r"marks and spencer|marks & spencer|m&s\b", "marks_spencer"),
    (r"\bboots\b", "boots"),
    (r"co-?operative|co-?op\b", "coop"),
    (r"morrison", "morrisons"),
    (r"waitrose", "waitrose"),
]

SUPERMARKET_CHAINS = {"tesco", "sainsburys", "asda", "lidl", "aldi",
                      "marks_spencer", "boots", "coop", "morrisons", "waitrose"}


def identify_chain(business_name: str) -> str | None:
    low = business_name.lower()
    for pattern, chain_id in CHAIN_PATTERNS:
        if re.search(pattern, low):
            return chain_id
    return None


def geocode_postcode(postcode: str, s=None) -> dict | None:
    """UK postcode -> coordinates. Returns None for an unrecognised postcode."""
    s = s or session()
    pc = postcode.replace(" ", "").upper()
    try:
        r = s.get(POSTCODES_API.format(postcode=pc), timeout=20)
        if r.status_code != 200:
            return None
        res = r.json().get("result") or {}
    except Exception:
        return None
    return {"postcode": res.get("postcode"), "lat": res.get("latitude"),
            "lng": res.get("longitude"), "district": res.get("admin_district"),
            "region": res.get("region"), "country": res.get("country")}


def reverse_geocode(lat: float, lng: float, s=None) -> dict | None:
    """Coordinates (e.g. from the browser) -> nearest postcode, for display."""
    s = s or session()
    try:
        r = s.get(POSTCODES_REVERSE, params={"lat": lat, "lon": lng, "limit": 1},
                  timeout=20)
        results = (r.json() or {}).get("result") or []
    except Exception:
        return None
    if not results:
        return None
    res = results[0]
    return {"postcode": res.get("postcode"), "lat": res.get("latitude"),
            "lng": res.get("longitude"), "district": res.get("admin_district")}


def find_outlets(lat: float, lng: float, radius_miles: float = 1.0,
                 s=None, types: list[str] | None = None) -> list[dict]:
    """Every food outlet near a point, from the national FHRS register."""
    s = s or session()
    wanted = types or ["takeaway", "restaurant_cafe", "retailer_other", "supermarket"]
    seen: set[tuple] = set()
    out: list[dict] = []
    for type_name in wanted:
        params = {"latitude": lat, "longitude": lng,
                  "maxDistanceLimit": radius_miles, "pageSize": 250,
                  "businessTypeId": FHRS_TYPES[type_name]}
        try:
            r = s.get(FHRS_API, headers=FHRS_HEADERS, params=params, timeout=40)
            r.raise_for_status()
            establishments = r.json().get("establishments", [])
        except Exception:
            continue
        for e in establishments:
            name = (e.get("BusinessName") or "").strip()
            key = (name.lower(), (e.get("AddressLine1") or "").lower())
            if key in seen:
                continue
            seen.add(key)
            chain_id = identify_chain(name)
            geo = e.get("geocode") or {}
            out.append({
                "business_name": name,
                "chain_id": chain_id,
                "kind": ("supermarket" if chain_id in SUPERMARKET_CHAINS
                         else "chain" if chain_id else "independent"),
                "address": ", ".join(filter(None, [
                    e.get("AddressLine1"), e.get("AddressLine2"),
                    e.get("AddressLine3"), e.get("PostCode")])),
                "postcode": e.get("PostCode"),
                "lat": float(geo["latitude"]) if geo.get("latitude") else None,
                "lng": float(geo["longitude"]) if geo.get("longitude") else None,
                "distance_miles": round(float(e.get("Distance") or 0), 2),
                "fhrs_rating": e.get("RatingValue"),
                "fhrs_id": e.get("FHRSID"),
                "business_type": type_name,
            })
    # FHRS treats maxDistanceLimit as a coarse band and returns wider results,
    # so enforce the caller's radius here.
    out = [o for o in out if o["distance_miles"] <= radius_miles]
    out.sort(key=lambda o: o["distance_miles"])
    return out


def resolve_location(postcode: str | None = None, lat: float | None = None,
                     lng: float | None = None, s=None) -> dict | None:
    """Accept either input the UI can produce, return a common shape."""
    if postcode:
        return geocode_postcode(postcode, s)
    if lat is not None and lng is not None:
        got = reverse_geocode(lat, lng, s)
        return got or {"postcode": None, "lat": lat, "lng": lng, "district": None}
    return None
