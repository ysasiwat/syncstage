import os
import io
import time
import json
import shutil
from pathlib import Path
import types
import pytest

# Small helper to mimic argparse.Namespace
def ns(**kwargs):
    return types.SimpleNamespace(**kwargs)

@pytest.fixture
def sandbox(tmp_path: Path):
    """
    Create a sandbox with:
      - root/ (the sync root)
      - src/  (a generic source for mirror tests)
      - tgt/  (a generic target base; mirror target is tgt/Dest)
    """
    root = tmp_path / "root"
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    for p in (root, src, tgt):
        p.mkdir(parents=True, exist_ok=True)
    return {"root": root, "src": src, "tgt": tgt}

@pytest.fixture
def cfg_default():
    # Minimal config; commands accept args.roots so we leave this mostly empty
    return {
        "roots": [],
        "ignore": [
            ".DS_Store","._*","Thumbs.db","desktop.ini","~$*","*.tmp",".Trash/**","**/.git/**"
        ],
        "organize": {"destination": "{root}/Organized", "by": "date_ext", "date_format": "%Y/%m", "lowercase_ext": True},
        "mirror": {"checksum": False, "delete_extraneous": False},
        "dedupe": {"algorithm": "blake2b", "block_size": 1024 * 1024},
    }

def write_file(p: Path, data: bytes | str, mtime: float | None = None):
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
    with open(p, mode) as f:
        f.write(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p

@pytest.fixture
def fixed_time():
    # Fixed timestamp: 2024-03-05 12:34:56 UTC
    return 1709642096.0
