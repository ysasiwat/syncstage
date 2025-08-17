from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Optional

from .ignore import DEFAULT_IGNORE

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "roots": [],  # must be provided via CLI --root or config file

    "ignore": DEFAULT_IGNORE,

    "organize": {
        "destination": "{root}/Organized",
        "by": "date_ext",            # date | ext | date_ext
        "date_format": "%Y/%m",
        "lowercase_ext": True,
    },

    "mirror": {
        "checksum": False,
        "delete_extraneous": False,
    },

    "dedupe": {
        "algorithm": "blake2b",      # blake2b | sha256
        "block_size": 1024 * 1024,   # 1 MiB
    },

    # New: defaults for the 'rename' command
    "rename": {
        "template": "{created:%Y-%m-%d} {stem}{ext}",

        # normalization
        "case": "smart",             # smart | title | lower | upper | keep
        "ext_case": "keep",          # keep | lower | upper
        "keep_symbols": False,
        "keep_underscores": False,
        "convert_dashes": False,
        "no_sanitize": False,
        "sanitize_mode": "drop",     # drop | underscore
        "keep_ext": False,
        "pad": 2,

        # idempotency
        "skip_if_already": True,
        # True = use built-in date-prefix regex; or provide a custom regex string
        "idempotent_prefix": True,

        # translation (true translation; optional)
        # None disables translation to avoid extra dependencies by default.
        "translate": None,                    # e.g. "th-en"
        "translate_provider": "googletrans",  # "googletrans" | "gcloud"
        "translate_cache": None               # path to a JSON file, or None
    },
}

# ---------------------------------------------------------------------------
# Loader: deep-merge user config over defaults
# ---------------------------------------------------------------------------

def load_config(path: Optional[Path]) -> dict:
    """Load config from JSON file and deep-merge into DEFAULT_CONFIG."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    if not path:
        if os.getenv("SYNCSTAGE_DEBUG") == "1":
            print("[debug] using DEFAULT_CONFIG (no --config provided)")
        return cfg

    if not path.exists():
        print(f"[warn] config not found at {path}; using defaults")
        return cfg

    try:
        with path.open("r", encoding="utf-8") as f:
            user = json.load(f)
    except Exception as e:
        print(f"[warn] failed to read config {path}: {e}; using defaults")
        return cfg

    def merge(a: dict, b: dict):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                merge(a[k], v)
            else:
                a[k] = v

    merge(cfg, user)

    # Quiet success log; path only. Full dump behind debug flag.
    print(f"[info] loaded config: {path}")
    if os.getenv("SYNCSTAGE_DEBUG") == "1":
        print(f"[debug] merged config: {cfg}")

    return cfg
