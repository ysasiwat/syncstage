from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from .ignore import DEFAULT_IGNORE

DEFAULT_CONFIG = {
    "roots": [],
    "ignore": DEFAULT_IGNORE,
    "organize": {
        "destination": "{root}/Organized",
        "by": "date_ext",          # date | ext | date_ext
        "date_format": "%Y/%m",
        "lowercase_ext": True
    },
    "mirror": {
        "checksum": False,
        "delete_extraneous": False
    },
    "dedupe": {
        "algorithm": "blake2b",    # blake2b | sha256
        "block_size": 1024 * 1024
    }
}

def load_config(path: Optional[Path]) -> dict:
    if not path:
        return DEFAULT_CONFIG.copy()
    if not path.exists():
        print(f"[warn] config not found at {path}; using defaults")
        return DEFAULT_CONFIG.copy()
    
    with path.open("r", encoding="utf-8") as f:
        user = json.load(f)

    # deep-merge defaults with user config
    import copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    def merge(a, b):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                merge(a[k], v)
            else:
                a[k] = v
                
    merge(cfg, user)
    return cfg
