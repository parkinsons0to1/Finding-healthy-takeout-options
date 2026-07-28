"""Shared plumbing for MacroMeter chain scrapers.

Every adapter is plain HTTP (requests) — no browser automation. Each exposes
`fetch() -> list[dict]` returning normalized item dicts (see NORMALIZED_FIELDS).
"""
from __future__ import annotations

import datetime
import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")

NORMALIZED_FIELDS = [
    "chain_id", "item_id", "name", "category", "serving_desc",
    "kcal", "protein_g", "carbs_g", "fat_g", "salt_g",
    "vegetarian", "vegan", "allergens",
    "source", "source_url", "fetched_at", "quality_flags",
]


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json,text/html,*/*"})
    return s


def item(chain_id, name, source, source_url, **kw) -> dict:
    d = {f: kw.get(f) for f in NORMALIZED_FIELDS}
    d.update(chain_id=chain_id, name=name, source=source, source_url=source_url,
             fetched_at=now_iso())
    d.setdefault("quality_flags", kw.get("quality_flags") or [])
    return d


def to_float(v):
    if v is None:
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def protein_share(it) -> float | None:
    if it.get("kcal") and it.get("protein_g"):
        return round(it["protein_g"] * 4 / it["kcal"], 4)
    return None
