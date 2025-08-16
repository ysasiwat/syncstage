from __future__ import annotations
import os
from pathlib import Path
import concurrent.futures as cf

from ..fs import iter_files
from ..utils import hash_file, human, try_hardlink

def run(args, cfg):
    roots = [Path(p) for p in (args.roots or cfg["roots"])]
    ignore = cfg["ignore"]
    algo = cfg["dedupe"]["algorithm"]
    block = cfg["dedupe"]["block_size"]

    files = []
    for root in roots:
        files.extend(iter_files(root, ignore))

    size_groups = {}
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size == 0:
            continue
        size_groups.setdefault(st.st_size, []).append(p)

    total_removed = 0
    with cf.ThreadPoolExecutor(max_workers=min(32, os.cpu_count() or 8)) as ex:
        for size, paths in size_groups.items():
            if len(paths) < 2:
                continue
            futs = {ex.submit(hash_file, p, algo, block): p for p in paths}
            by_hash = {}
            for fut, p in futs.items():
                h = fut.result()
                by_hash.setdefault(h, []).append(p)

            for h, group in by_hash.items():
                if len(group) < 2:
                    continue
                group_sorted = sorted(group, key=lambda p: str(p).lower())
                keeper = group_sorted[0]
                dupes = group_sorted[1:]
                print(f"[dupe] {human(size)} hash={h[:12]} keep={keeper.name} remove={len(dupes)}")
                for d in dupes:
                    if args.hardlink and keeper.exists():
                        print(f"  link: {d} -> {keeper}")
                        if args.apply:
                            try:
                                d.unlink(missing_ok=False)
                                tmp = d.with_suffix(d.suffix + ".syncstage-linktmp")
                                if try_hardlink(keeper, tmp):
                                    os.replace(tmp, d)
                                    total_removed += 1
                            except FileNotFoundError:
                                continue
                    else:
                        print(f"  rm  : {d}")
                        if args.apply:
                            try:
                                d.unlink()
                                total_removed += 1
                            except FileNotFoundError:
                                pass
    print(f"[done] removed/linked={total_removed} (dry-run={not args.apply})")
    return 0
