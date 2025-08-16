from __future__ import annotations
import hashlib
import os
import platform
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Iterable, List

SPACE_RE = re.compile(r"\s+")
INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]')  # Windows-invalid + control chars
SAFE_CHARS = "-_.() []{}@~^+=,"

SMALL_WORDS = {"a","an","and","as","at","but","by","for","from","in","of","on","or","the","to","vs","via"}
ACRONYMS = {"PDF","CAD","RF","SDR","STM32","FPGA","SAR","GNSS","IOT","CPU","GPU","GPS","USB","I2C","SPI","CAN","AI","ML"}

def human(n: int) -> str:
    for unit in ["B","KB","MB","GB","TB"]:
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}PB"

def sanitize_filename(name: str, keep: str = SAFE_CHARS, collapse_spaces: bool = True, mode: str = "drop"):
    """Drop or underscore invalid filesystem chars; keep spaces and SAFE_CHARS."""
    def ok(ch):
        return ch.isalnum() or ch in keep or ch.isspace()
    if mode == "underscore":
        cleaned = "".join(ch if ok(ch) else "_" for ch in name)
    else:
        cleaned = "".join(ch for ch in name if ok(ch))
    return SPACE_RE.sub(" ", cleaned).strip() if collapse_spaces else cleaned

def split_name_ext(name: str) -> tuple[str, str]:
    """Return (stem, ext). For 'archive.tar.gz' -> ('archive.tar', '.gz')."""
    if name.startswith(".") and name.count(".") == 1:
        return name, ""
    idx = name.rfind(".")
    if idx <= 0:
        return name, ""
    return name[:idx], name[idx:]

def smart_title_case(text: str) -> str:
    # split preserving separators
    parts = re.split(r"(\s+|-)", text)
    word_idx = [i for i,t in enumerate(parts) if t and not t.isspace() and t != "-"]
    last = word_idx[-1] if word_idx else -1

    def norm(tok: str, pos: int) -> str:
        if not tok or tok.isspace() or tok == "-":
            return tok
        bare = re.sub(r"[^\w]", "", tok).upper()
        if bare in ACRONYMS:
            return bare
        low = tok.lower()
        if 0 < pos < last and low in SMALL_WORDS:
            return low
        return low.capitalize()

    return "".join(norm(t, i) for i, t in enumerate(parts))

def normalize_stem(stem: str,
                   case_mode: str = "smart",
                   drop_symbols: bool = True,
                   convert_underscores: bool = True,
                   convert_dashes: bool = False) -> str:
    s = unicodedata.normalize("NFKC", stem)
    if convert_underscores:
        s = s.replace("_", " ")
    if convert_dashes:
        s = s.replace("-", " ")
    if drop_symbols:
        s = re.sub(r"[\"'?!`·•^/\\|*<>]+", "", s)
    s = SPACE_RE.sub(" ", s).strip()

    if case_mode == "keep":
        pass
    elif case_mode == "lower":
        s = s.lower()
    elif case_mode == "upper":
        s = s.upper()
    elif case_mode == "title":
        s = s.title()
    else:
        s = smart_title_case(s)
    return s

def hash_file(path: Path, algo: str = "blake2b", block_size: int = 1024 * 1024) -> str:
    h = hashlib.blake2b(digest_size=32) if algo.lower() == "blake2b" else hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(block_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def atomic_move_or_replace(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)  # atomic on same volume
    except OSError:
        tmp = dst.with_suffix(dst.suffix + ".tmp-syncstage")
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        src.unlink(missing_ok=True)

def try_hardlink(src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
        return True
    except OSError:
        return False

def get_created_datetime(p: Path):
    import datetime as dt
    try:
        st = p.stat()
    except OSError:
        return dt.datetime.fromtimestamp(0)
    system = platform.system()
    if hasattr(st, "st_birthtime"):
        ts = getattr(st, "st_birthtime", st.st_mtime)
    elif system == "Windows":
        ts = st.st_ctime
    else:
        ts = min(st.st_mtime, st.st_ctime)
    return dt.datetime.fromtimestamp(ts)
