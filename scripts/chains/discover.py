"""Probe every catalogued chain for a reachable nutrition source.

Hand-checking ~60 brand websites is the slow way to find out which ones are
tractable. This walks each chain's candidate URLs, records what came back, and
classifies the likely source type so adapter work can be batched:

    pdf         a nutrition PDF was linked or served -> pdfplumber adapter
    json_api    a JSON endpoint answered             -> plain HTTP adapter
    html_table  macros appear in server-rendered HTML-> parse in place
    js_only     page loads but macros aren't in the  -> needs endpoint hunting
                HTML (client-rendered)
    blocked     403/blocked even with TLS impersonation
    unresolved  none of this chain's *guessed* URLs answered

Everything is tried with plain `requests` first, then with browser TLS
impersonation, because several chains 403 the former (that's how Papa John's
and GDK were unblocked).

**These labels describe what this tool found, never what a chain publishes.**
The distinction is not pedantic. `unresolved` was previously called "dead", and
a run of empty results was written up as "these chains only publish allergen
data" — which was false: Chipotle publishes a full nutrition table at
/nutrition-calculator, and the probe had simply matched their menu PDF instead.
This tool guesses URLs from a fixed list of common paths, so a miss is nearly
always a wrong guess, not an absent source. Only a positively verified brand
statement may be recorded as "publishes nothing", and this tool cannot produce
one.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pathlib
import re
import sys

from ..scrapers.base import fetch_protected, now_iso, session
from .catalog import CATALOG, pending

DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "db"

#: Macro words that indicate real nutrition content rather than a menu page.
_MACRO_HINTS = re.compile(r"\bprotein\b", re.I)
_ENERGY_HINTS = re.compile(r"\bkcal\b|energy \(kcal\)|kJ\b", re.I)
_PDF_LINK = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)


def _classify(url: str, status: int, body: bytes, content_type: str) -> dict:
    if status != 200:
        return {"type": "blocked" if status in (401, 403) else "unresolved",
                "status": status}
    if "pdf" in content_type.lower() or body[:4] == b"%PDF":
        return {"type": "pdf", "status": status, "pdf_url": url}

    text = body.decode("utf-8", "ignore")
    pdfs = [p for p in _PDF_LINK.findall(text)
            if re.search(r"nutrit|allergen|calorie", p, re.I)]
    if pdfs:
        link = pdfs[0]
        if link.startswith("/"):
            root = "/".join(url.split("/")[:3])
            link = root + link
        return {"type": "pdf", "status": status, "pdf_url": link}

    has_protein = bool(_MACRO_HINTS.search(text))
    has_energy = bool(_ENERGY_HINTS.search(text))
    if has_protein and has_energy:
        # Distinguish real tables from a page that merely mentions the words.
        numeric = len(re.findall(r">\s*\d{1,4}(?:\.\d)?\s*<", text))
        return {"type": "html_table" if numeric > 30 else "js_only",
                "status": status, "numeric_cells": numeric}
    return {"type": "js_only", "status": status}


def probe_url(s, url: str) -> dict | None:
    try:
        r = s.get(url, timeout=20, allow_redirects=True)
        if r.status_code == 200:
            return {"url": url, **_classify(url, 200, r.content,
                                            r.headers.get("Content-Type", ""))}
        if r.status_code in (401, 403):
            pr = fetch_protected(url, timeout=45)
            if pr is not None:
                return {"url": url, "via": "tls-impersonation",
                        **_classify(url, 200, pr.content,
                                    pr.headers.get("Content-Type", ""))}
            return {"url": url, "type": "blocked", "status": r.status_code}
    except Exception:
        return None
    return None


def probe_chain(chain) -> dict:
    s = session()
    findings = []
    for url in chain.candidates:
        got = probe_url(s, url)
        if got and got["type"] in ("pdf", "html_table", "json_api"):
            findings.append(got)
            break                      # a usable source is enough
        if got:
            findings.append(got)
    best = next((f for f in findings if f["type"] in ("pdf", "html_table")), None)
    if best is None:
        best = next((f for f in findings if f["type"] == "js_only"),
                    findings[0] if findings else {"type": "unresolved"})
    return {"chain_id": chain.chain_id, "name": chain.name, "kind": chain.kind,
            "best": best, "tried": len(chain.candidates)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", help="comma-separated subset")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    targets = pending()
    if args.chains:
        wanted = {c.strip() for c in args.chains.split(",")}
        targets = [CATALOG[c] for c in wanted if c in CATALOG]

    print(f"probing {len(targets)} chains...\n")
    results = []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        for res in ex.map(probe_chain, targets):
            results.append(res)
            b = res["best"]
            extra = b.get("pdf_url") or b.get("url") or ""
            print(f"  {res['name'][:24]:24s} {b['type']:11s} {extra[:64]}")

    by_type: dict[str, list[str]] = {}
    for r in results:
        by_type.setdefault(r["best"]["type"], []).append(r["chain_id"])
    print("\nsummary:")
    for t, ids in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        print(f"  {t:11s} {len(ids):3d}  {', '.join(ids[:12])}")

    out = DB / "chain_discovery.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"generated_at": now_iso(), "results": results},
                              indent=1))
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
