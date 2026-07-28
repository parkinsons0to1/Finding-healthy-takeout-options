#!/usr/bin/env python3
"""MacroMeter web app + JSON API.

    python3 -m scripts.api.server          # http://localhost:8000

Deliberately dependency-free (stdlib http.server): the whole point of Phase 0–3
was to prove the data pipeline, and a framework would add deployment weight
without changing anything we've learned. The Next.js/Vercel front end in the
technical plan is the production target; this serves the same JSON contract, so
the front end can be swapped in without touching the pipeline.

Endpoints
    GET /                     the app
    GET /api/search?...       ranked items for a location
    GET /api/mealdeals?...    best fixed-price supermarket bundles
    GET /api/health
"""
from __future__ import annotations

import json
import pathlib
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..mealdeals.cli import load_products
from ..mealdeals.deals import DEALS
from ..mealdeals.optimiser import optimise_all
from .search import search

STATIC = pathlib.Path(__file__).resolve().parents[2] / "web"

#: Halal resolution hits chain sites per outlet, so cache within the process.
_HALAL_CACHE: dict = {}


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def _mealdeal_payload(q: dict) -> dict:
    diet = {d for d in (q.get("diet", [""])[0] or "").split(",") if d}
    min_share = float(q.get("min_protein_share", ["0"])[0] or 0)
    loyalty = _bool(q.get("loyalty", ["1"])[0], True)

    by_retailer = {}
    for deal in DEALS:
        products = load_products(deal.retailer_id)
        if products:
            by_retailer[deal.retailer_id] = products
    if not by_retailer:
        return {"bundles": [],
                "note": "no cached meal-deal products — run "
                        "'python3 -m scripts.mealdeals.cli fetch'"}
    bundles = optimise_all(DEALS, by_retailer, diet=diet,
                           min_protein_share=min_share, loyalty=loyalty)
    return {"bundles": [b.to_row() for b in bundles],
            "retailers_with_data": sorted(by_retailer)}


class Handler(BaseHTTPRequestHandler):
    server_version = "MacroMeter/1.0"

    def log_message(self, fmt, *args):        # keep the console readable
        pass

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload).encode(), "application/json")

    def _static(self, name: str, content_type: str):
        path = STATIC / name
        if not path.exists():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, path.read_bytes(), content_type)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        try:
            if route in ("/", "/index.html"):
                return self._static("index.html", "text/html; charset=utf-8")
            if route == "/app.js":
                return self._static("app.js", "application/javascript")
            if route == "/styles.css":
                return self._static("styles.css", "text/css")
            if route == "/api/health":
                return self._json({"ok": True, "service": "macrometer"})
            if route == "/api/mealdeals":
                return self._json(_mealdeal_payload(q))
            if route == "/api/search":
                postcode = (q.get("postcode", [None])[0] or None)
                lat = q.get("lat", [None])[0]
                lng = q.get("lng", [None])[0]
                diet = {d for d in (q.get("diet", [""])[0] or "").split(",") if d}
                payload = search(
                    postcode=postcode,
                    lat=float(lat) if lat else None,
                    lng=float(lng) if lng else None,
                    radius_miles=float(q.get("radius", ["1"])[0]),
                    diet=diet,
                    min_protein_share=float(q.get("min_protein_share", ["0.35"])[0]),
                    strict_halal=_bool(q.get("strict_halal", ["1"])[0], True),
                    sort_by=q.get("sort_by", ["protein_per_pound"])[0],
                    limit=int(q.get("limit", ["25"])[0]),
                    halal_cache=_HALAL_CACHE)
                return self._json(payload)
            self._send(404, b"not found", "text/plain")
        except Exception as e:
            traceback.print_exc()
            self._json({"error": str(e)}, 500)


def main(port: int = 8000):
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"MacroMeter running on http://localhost:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
