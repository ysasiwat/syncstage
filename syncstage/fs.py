from __future__ import annotations
import os
from pathlib import Path
from typing import Iterable, List

def safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)

def matches_any(rel: str, patterns: List[str]) -> bool:
    import fnmatch
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
    return False

def iter_files(root: Path, ignore: List[str]) -> Iterable[Path]:
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel_dir = safe_rel(d, root)
        pruned = []
        for dn in list(dirnames):
            rel = (Path(rel_dir) / dn).as_posix()
            if matches_any(rel, ignore) or matches_any(rel + "/**", ignore):
                continue
            pruned.append(dn)
        dirnames[:] = pruned
        for fn in filenames:
            p = d / fn
            rel = (Path(rel_dir) / fn).as_posix()
            if matches_any(rel, ignore):
                continue
            try:
                if p.is_symlink():
                    continue
            except OSError:
                continue
            yield p
