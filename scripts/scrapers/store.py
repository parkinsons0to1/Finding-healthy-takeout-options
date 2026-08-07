"""Storage sinks: Firebase Firestore when credentials exist, local JSON otherwise.

Firestore layout:
    nutrition_items/{chain_id}            (doc: chain metadata + fetched_at)
    nutrition_items/{chain_id}/items/{item_key}

Setup for Firebase:
    1. Firebase console -> project settings -> service accounts -> generate key.
    2. Save the JSON key file and set env var:
         export FIREBASE_CREDENTIALS=/path/to/serviceAccountKey.json
       (GOOGLE_APPLICATION_CREDENTIALS also works.)
    3. pip install firebase-admin

Without credentials everything lands in data/db/{chain_id}.json so the
pipeline runs anywhere; the web app can read either store.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

DB_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "db"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


class LocalJSONSink:
    name = "local-json"

    def upsert_items(self, chain_id: str, items: list[dict]) -> str:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        path = DB_DIR / f"{chain_id}.json"
        payload = {
            "chain_id": chain_id,
            "item_count": len(items),
            "fetched_at": items[0]["fetched_at"] if items else None,
            "items": {(_slug(i.get("item_id") or i["name"])): i for i in items},
        }
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
        return str(path)


class FirestoreSink:
    name = "firestore"

    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            key = os.environ.get("FIREBASE_CREDENTIALS") or os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS")
            cred = credentials.Certificate(key) if key else credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()

    def upsert_items(self, chain_id: str, items: list[dict]) -> str:
        chain_ref = self.db.collection("nutrition_items").document(chain_id)
        chain_ref.set({"chain_id": chain_id, "item_count": len(items),
                       "fetched_at": items[0]["fetched_at"] if items else None},
                      merge=True)
        batch, n = self.db.batch(), 0
        for it in items:
            batch.set(chain_ref.collection("items").document(_slug(it.get("item_id") or it["name"])), it)
            n += 1
            if n % 400 == 0:      # Firestore batch limit is 500 writes
                batch.commit()
                batch = self.db.batch()
        batch.commit()
        return f"firestore:nutrition_items/{chain_id} ({len(items)} items)"


def get_sink():
    has_creds = os.environ.get("FIREBASE_CREDENTIALS") or os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS")
    if has_creds:
        try:
            return FirestoreSink()
        except ImportError:
            print("firebase-admin not installed; falling back to local JSON "
                  "(pip install firebase-admin)")
    return LocalJSONSink()
