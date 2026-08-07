"""Per-chain nutrition adapters, auto-discovered.

Every module in this package that exposes ``CHAIN`` (a chain id) and
``fetch() -> list[dict]`` is registered automatically. One file per chain keeps
adapters independent: they can be written in parallel, and a chain whose
website changes breaks only its own module.

Each `fetch()` must return rows built with `scrapers.base.item`, i.e. carrying
`name`, `kcal`, `protein_g`, `source` and `source_url` at minimum.
"""
from __future__ import annotations

import importlib
import pkgutil

ADAPTERS: dict[str, object] = {}

for _finder, _name, _ispkg in pkgutil.iter_modules(__path__):
    if _name.startswith("_"):
        continue
    try:
        _mod = importlib.import_module(f"{__name__}.{_name}")
    except Exception:            # a broken adapter must not break the rest
        continue
    _chain = getattr(_mod, "CHAIN", None)
    if _chain and callable(getattr(_mod, "fetch", None)):
        ADAPTERS[_chain] = _mod
