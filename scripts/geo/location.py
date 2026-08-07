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
PLACES_API = "https://api.postcodes.io/places"

#: A UK postcode, loosely — enough to tell "SM1 4FR" from "St Ives Cornwall".
_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.I)
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
#:
#: Recall matters more than it looks: an unrecognised chain is silently
#: classified as an independent and vanishes from the results *and* from the
#: "chains nearby" count. A short list under-reports what's actually around
#: the user — a Papa John's inside a holiday park was being counted as an
#: independent purely because the name wasn't listed here.
CHAIN_PATTERNS: list[tuple[str, str]] = [
    # Burgers / chicken / fast food
    (r"german doner|gdk\b", "gdk"),
    (r"burger king", "burger_king"),
    (r"taco bell", "taco_bell"),
    (r"five guys", "five_guys"),
    (r"nando", "nandos"),
    (r"mcdonald", "mcdonalds"),
    (r"popeyes", "popeyes"),
    (r"\bkfc\b|kentucky fried", "kfc"),
    (r"morley", "morleys"),
    (r"chicken cottage", "chicken_cottage"),
    (r"chicken shop|dixy", "dixy_chicken"),
    (r"wingstop", "wingstop"),
    (r"slim chicken", "slim_chickens"),
    (r"shake shack", "shake_shack"),
    (r"wimpy", "wimpy"),
    # Pizza
    (r"papa john", "papa_johns"),
    (r"domino", "dominos"),
    (r"pizza hut", "pizza_hut"),
    (r"pizza express|pizzaexpress", "pizza_express"),
    (r"papa murphy", "papa_murphys"),
    (r"franco manca", "franco_manca"),
    (r"\bzizzi\b", "zizzi"),
    (r"\bask italian\b", "ask_italian"),
    # Sandwiches / bakery / coffee
    (r"subway", "subway"),
    (r"greggs", "greggs"),
    (r"pret a manger", "pret"),
    (r"\bitsu\b", "itsu"),
    (r"\bleon\b", "leon"),
    (r"costa coffee|\bcosta\b", "costa"),
    (r"starbucks", "starbucks"),
    (r"caffe nero|caff[eè] nero", "caffe_nero"),
    (r"tim hortons", "tim_hortons"),
    (r"gail'?s", "gails"),
    (r"warrens bakery", "warrens"),
    (r"\bpaul\b bakery", "paul"),
    # Asian / other
    (r"kokoro", "kokoro"),
    (r"wagamama", "wagamama"),
    (r"yo!? sushi", "yo_sushi"),
    (r"wasabi", "wasabi"),
    (r"chopstix", "chopstix"),
    (r"tortilla", "tortilla"),
    (r"chipotle", "chipotle"),
    (r"\bwok\b.*\bbox\b|wok to walk", "wok_to_walk"),
    # Pubs / casual dining that publish nutrition
    (r"wetherspoon|\bj ?d ?wetherspoon", "wetherspoons"),
    (r"harvester", "harvester"),
    (r"toby carvery", "toby_carvery"),
    (r"beefeater", "beefeater"),
    (r"brewers fayre", "brewers_fayre"),
    (r"hungry horse", "hungry_horse"),
    (r"\bmiller ?& ?carter", "miller_carter"),
    (r"frankie ?& ?benny", "frankie_bennys"),
    (r"\btgi\b|t\.?g\.?i\.? friday", "tgi_fridays"),
    # Supermarkets / convenience
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
    (r"\bspar\b", "spar"),
    (r"\bpremier\b", "premier"),
    (r"\bnisa\b", "nisa"),
    (r"londis", "londis"),
    (r"budgens", "budgens"),
    (r"one ?stop", "one_stop"),
    (r"iceland", "iceland"),
    (r"\bwhsmith|w h smith", "whsmith"),
    (r"costcutter", "costcutter"),
    (r"best ?one\b", "best_one"),
    (r"lifestyle express", "lifestyle_express"),
    (r"day ?today", "day_today"),
    (r"scotmid", "scotmid"),
    (r"farmfoods", "farmfoods"),
    (r"holland ?(&|and) ?barrett", "holland_barrett"),
    (r"home bargains", "home_bargains"),
    (r"poundland", "poundland"),
    (r"b ?(&|and) ?m\b", "bm_bargains"),
    # Found by scripts/chains/detect.py — see that module for the method.
    (r"black sheep coffee", "black_sheep_coffee"),
    (r"coffee ?#? ?1\b", "coffee_1"),
    (r"chaiiwala", "chaiiwala"),
    (r"pepe'?s piri", "pepes_piri_piri"),
    (r"krispy kreme", "krispy_kreme"),
    (r"sushi gourmet", "sushi_gourmet"),
    (r"yo!? to go", "yo_to_go"),
    (r"cake ?box|egg free cake box", "cake_box"),
    (r"cafe 0161", "cafe_0161"),
    (r"batch'?d", "batchd"),
    (r"hotel chocolat", "hotel_chocolat"),
    (r"german doner", "gdk"),
]

#: Retail/convenience chains, routed to the Open Food Facts meal-deal pipeline
#: rather than the food-service nutrition pipeline. Ten of these (costcutter
#: through scotmid) were recognised by CHAIN_PATTERNS but missing from this
#: set, so `search()` classified them as `kind: "chain"` and tried to load a
#: menu adapter that will never exist for a Poundland — they surfaced to users
#: as "chains nearby, not yet rankable" instead of being reported as the shops
#: they are. A retailer belongs here, never in a menu-adapter catalog: writing
#: a "menu" for a shop with barcoded groceries is a category error regardless
#: of how the mismatch happens to present.
SUPERMARKET_CHAINS = {"tesco", "sainsburys", "asda", "lidl", "aldi",
                      "marks_spencer", "boots", "coop", "morrisons", "waitrose",
                      "spar", "premier", "nisa", "londis", "budgens",
                      "one_stop", "iceland", "whsmith",
                      "costcutter", "best_one", "lifestyle_express", "day_today",
                      "scotmid", "farmfoods", "holland_barrett", "home_bargains",
                      "poundland", "bm_bargains"}


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


def looks_like_postcode(text: str) -> bool:
    return bool(_POSTCODE_RE.match(text.strip()))


def search_places(query: str, s=None, limit: int = 8) -> list[dict]:
    """Place-name lookup, e.g. "St Ives" or "St Ives Cornwall".

    Place names are genuinely ambiguous — there are three St Ives (Cornwall,
    Cambridgeshire, Dorset) — so this returns all candidates and lets the
    caller disambiguate rather than silently picking one. A user sent to the
    wrong St Ives gets a confidently wrong answer about food 300 miles away.

    A trailing county in the query ("St Ives Cornwall") is used to rank, since
    postcodes.io matches on the place name alone.
    """
    s = s or session()
    text = query.strip()
    try:
        r = s.get(PLACES_API, params={"q": text, "limit": 20}, timeout=25)
        results = (r.json() or {}).get("result") or []
    except Exception:
        return []
    if not results:
        # Retry on the leading words alone, so "St Ives Cornwall" still matches
        # the place "St Ives".
        words = text.split()
        if len(words) > 1:
            try:
                r = s.get(PLACES_API, params={"q": " ".join(words[:-1]), "limit": 20},
                          timeout=25)
                results = (r.json() or {}).get("result") or []
            except Exception:
                return []
    if not results:
        return []

    qualifier = text.lower()
    places = [{
        "name": p.get("name_1"),
        "county": p.get("county_unitary") or p.get("region"),
        "region": p.get("region"),
        "lat": p.get("latitude"), "lng": p.get("longitude"),
    } for p in results]
    for p in places:
        p.pop("challenge_placeholder", None)
        county = (p["county"] or "").lower()
        p["label"] = f"{p['name']}, {p['county']}" if p["county"] else p["name"]
        # Rank a place higher when its county was named in the query.
        p["_score"] = 1 if county and county.split(",")[0] in qualifier else 0
    places.sort(key=lambda p: p["_score"], reverse=True)
    for p in places:
        p.pop("_score", None)
    return places[:limit]


def search_pois(query: str, s=None, limit: int = 6) -> list[dict]:
    """Find a named venue — holiday park, hotel, pub, campus — by name.

    postcodes.io only knows settlements, so "Haven Riviere Sands" returns
    nothing there. But almost every such venue runs a food business (a site
    shop, bar or café) that is registered with the FSA, so the same national
    hygiene register we already use for outlet discovery doubles as a POI
    locator. Searching "Haven Holiday" finds "Haven Holiday Park Mini Market"
    at TR27 5AF — the Riviere Sands site shop — with coordinates attached.

    This matters because a holiday park is exactly where someone opens this
    app: away from home, unsure what's nearby.
    """
    s = s or session()
    text = query.strip()
    words = [w for w in text.split() if w]
    candidates: list[dict] = []
    seen: set[str] = set()

    # A trailing county or town is a *filter*, not part of the venue's name:
    # searching the name "Haven" alone finds a hotel in Rye, but name="Haven"
    # with address="Hayle" finds the Riviere Sands site shop exactly. FHRS
    # matches registered trading names, which rarely equal marketing names
    # ("Haven Riviere Sands" is registered as "Haven Holiday Park Mini
    # Market"), so try the full phrase then individual significant words.
    qualifiers = [w for w in words[-2:] if len(w) > 3]
    name_words = [w for w in words if w not in qualifiers and len(w) > 2]

    attempts: list[dict] = [{"name": text}]
    for qualifier in qualifiers:
        attempts.append({"name": " ".join(name_words), "address": qualifier})
        for word in name_words:
            attempts.append({"name": word, "address": qualifier})
    for word in name_words:
        attempts.append({"name": word})

    for attempt in attempts:
        if not attempt.get("name"):
            continue
        try:
            r = s.get(FHRS_API, headers=FHRS_HEADERS,
                      params={**attempt, "pageSize": 50}, timeout=30)
            r.raise_for_status()
            establishments = r.json().get("establishments", [])
        except Exception:
            continue
        for e in establishments:
            geo = e.get("geocode") or {}
            lat, lng = geo.get("latitude"), geo.get("longitude")
            if lat is None or lng is None:
                continue
            name = (e.get("BusinessName") or "").strip()
            key = f"{name}|{e.get('PostCode')}"
            if key in seen:
                continue
            seen.add(key)
            address = ", ".join(filter(None, [
                e.get("AddressLine1"), e.get("AddressLine2"),
                e.get("AddressLine3"), e.get("PostCode")]))
            candidates.append({
                "name": name, "address": address,
                "postcode": e.get("PostCode"),
                "lat": float(lat), "lng": float(lng),
                "label": f"{name} — {address}" if address else name,
            })
        if candidates:
            break

    # Rank by how much of the query the venue actually accounts for, so a
    # same-named venue in the wrong county loses to the one the user meant.
    hints = {w.lower() for w in words if len(w) > 3}
    for c in candidates:
        haystack = f"{c['name']} {c['address']}".lower()
        c["_score"] = sum(1 for h in hints if h in haystack)
    candidates = [c for c in candidates if c["_score"] > 0] or candidates
    candidates.sort(key=lambda c: c["_score"], reverse=True)
    for c in candidates:
        c.pop("_score", None)
    return candidates[:limit]


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
    """Accept either input the UI can produce, return a common shape.

    When the caller supplies coordinates, those coordinates *are* the search
    centre. Reverse geocoding is used only to put a human-readable postcode and
    district on screen — substituting the postcode's centroid would silently
    move the search by up to a few hundred metres and change which outlets fall
    inside the radius.
    """
    if postcode:
        return geocode_postcode(postcode, s)
    if lat is not None and lng is not None:
        label = reverse_geocode(lat, lng, s) or {}
        return {"postcode": label.get("postcode"), "lat": lat, "lng": lng,
                "district": label.get("district")}
    return None
