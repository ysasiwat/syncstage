from __future__ import annotations
import os
from pathlib import Path

from ..ignore import DEFAULT_IGNORE
from ..fs import iter_files, matches_any, safe_rel

def run(args, cfg):
    roots = [Path(p) for p in (args.roots or cfg["roots"])]
    ignore = cfg["ignore"]
    removed = 0
    pruned = 0

    junk = DEFAULT_IGNORE
    for root in roots:
        print(f"[clean] {root}")
        for p in iter_files(root, ignore=[]):
            rel = safe_rel(p, root).replace("\\", "/")
            if matches_any(rel, junk):
                print(f"  rm: {p}")
                if args.apply:
                    try:
                        p.unlink()
                        removed += 1
                    except FileNotFoundError:
                        pass
        if args.prune_empty:
            for dirpath, dirnames, filenames in os.walk(root, topdown=False):
                d = Path(dirpath)
                if d == root:
                    continue
                try:
                    if not any(d.iterdir()):
                        print(f"  rmdir: {d}")
                        if args.apply:
                            d.rmdir()
                            pruned += 1
                except OSError:
                    pass
    print(f"[done] removed_files={removed} pruned_dirs={pruned} (dry-run={not args.apply})")
    return 0
