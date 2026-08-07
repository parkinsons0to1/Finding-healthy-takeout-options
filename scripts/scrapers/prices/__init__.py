"""Per-store REAL price adapters.

Each module exposes:

    CHAIN = "<chain_id>"
    def fetch_prices(store_id: str | None = None) -> list[dict]

returning ``[{"name": str, "price_gbp": float, "basis": str, "store": str}, ...]``
where ``basis`` is ``"collection"`` or ``"delivery"`` — never an estimate. If an
adapter cannot reach a real priced menu it raises rather than guessing.
"""
from __future__ import annotations

import importlib
import pkgutil

#: chain_id -> adapter module, auto-discovered so adding a chain is one file.
ADAPTERS: dict[str, object] = {}

for _finder, _name, _ispkg in pkgutil.iter_modules(__path__):
    if _name.startswith("_") or _name == "run":
        continue
    try:
        _mod = importlib.import_module(f"{__name__}.{_name}")
    except Exception:          # a broken adapter must not break the rest
        continue
    _chain = getattr(_mod, "CHAIN", None)
    if _chain and callable(getattr(_mod, "fetch_prices", None)):
        ADAPTERS[_chain] = _mod
