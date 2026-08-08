"""Shared plumbing for MacroMeter chain scrapers.

Every adapter is plain HTTP (requests) — no browser automation. Each exposes
`fetch() -> list[dict]` returning normalized item dicts (see NORMALIZED_FIELDS).
"""
from __future__ import annotations

import datetime
import os
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


#: Browser TLS profiles tried in order by `fetch_protected`. Order matters:
#: in a proxied environment "chrome" can have its connection reset while
#: "safari" succeeds, so never rely on a single profile.
_IMPERSONATE_PROFILES = ("safari", "chrome", "edge")


def fetch_protected(url: str, timeout: int = 90, referer: str | None = None,
                    headers: dict | None = None):
    """Fetch a URL whose host rejects Python's TLS handshake.

    Some chains (Papa John's, GDK) sit behind Cloudflare, which fingerprints
    the TLS handshake itself — no combination of headers gets `requests`
    through, and they 403 even on a static nutrition PDF. `curl_cffi`
    reproduces a real browser's handshake, which is enough. This is still
    plain HTTP: no browser, no JS execution, no automation.

    `headers` merges in on top of `referer` (e.g. an `Origin` header some
    origins gate on) — see `wingstop.py` for a case where the *presence* of
    `Origin` (with no `Referer` at all) is what a Vita Mojo endpoint needs to
    stop 500ing on `Referer`-bearing or header-bare requests alike.

    Returns the response, or None if every profile failed.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    merged_headers = {}
    if referer:
        merged_headers["Referer"] = referer
    if headers:
        merged_headers.update(headers)
    kwargs = {"timeout": timeout, "headers": merged_headers or None}
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(ca):
        kwargs["verify"] = ca

    for profile in _IMPERSONATE_PROFILES:
        try:
            r = cffi_requests.get(url, impersonate=profile,
                                  **{k: v for k, v in kwargs.items() if v is not None})
            if r.status_code == 200:
                return r
        except Exception:
            continue
    return None


def post_protected(url: str, data=None, headers: dict | None = None,
                   timeout: int = 90):
    """POST to a host that hangs or resets plain `requests` connections.

    Some ordering platforms (Taco Bell UK's `order.tacobell.co.uk`, on the
    same Yum! storefront-GraphQL stack as Pizza Hut) don't 403 a bad client —
    the TCP connection is accepted and then simply never answers, so plain
    `requests` times out rather than failing fast. `curl_cffi`'s browser TLS
    fingerprint gets an immediate reply. Still plain HTTP underneath: no
    browser, no JS execution, no automation.

    `data` is sent as the raw request body (pass pre-serialized JSON bytes
    or str — this does not set Content-Type for you, put it in `headers`).
    Returns the response, or None if every profile failed.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    kwargs = {"timeout": timeout, "data": data, "headers": headers}
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(ca):
        kwargs["verify"] = ca

    for profile in _IMPERSONATE_PROFILES:
        try:
            r = cffi_requests.post(url, impersonate=profile,
                                   **{k: v for k, v in kwargs.items() if v is not None})
            if r.status_code == 200:
                return r
        except Exception:
            continue
    return None


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
