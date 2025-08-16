from __future__ import annotations
import os
from pathlib import Path
import concurrent.futures as cf

from ..fs import iter_files
from ..utils import hash_file, human

def run(args, cfg):
    roots = [Path(p) for p in (args.roots or cfg["roots"])]
    if not roots:
        print("[error] no roots provided (use --root or config)")
        return 2
    ignore = cfg["ignore"]

    total_files = 0
    total_bytes = 0
    ext_hist = {}
    size_hist = {}
    candidates_by_size = {}

    for root in roots:
        print(f"[scan] {root}")
        for p in iter_files(root, ignore):
            total_files += 1
            try:
                st = p.stat()
            except OSError:
                continue
            total_bytes += st.st_size
            ext = p.suffix.lower() or "<noext>"
            ext_hist[ext] = ext_hist.get(ext, 0) + 1
            sz = st.st_size
            candidates_by_size.setdefault(sz, []).append(p)
            bucket = (
                "<1MB" if sz < 1<<20 else
                "<10MB" if sz < 10<<20 else
                "<100MB" if sz < 100<<20 else
                "<1GB" if sz < 1<<30 else
                ">=1GB"
            )
            size_hist[bucket] = size_hist.get(bucket, 0) + 1

    algo = cfg["dedupe"]["algorithm"]
    block = cfg["dedupe"]["block_size"]
    dupe_groups = []
    with cf.ThreadPoolExecutor(max_workers=min(32, os.cpu_count() or 8)) as ex:
        for size, paths in candidates_by_size.items():
            if size == 0 or len(paths) < 2:
                continue
            futs = {ex.submit(hash_file, p, algo, block): p for p in paths}
            by_hash = {}
            for fut, p in futs.items():
                h = fut.result()
                by_hash.setdefault(h, []).append(p)
            for h, group in by_hash.items():
                if len(group) > 1:
                    dupe_groups.append((size, h, group))

    print("\n[summary]")
    print(f"  files : {total_files}")
    print(f"  bytes : {total_bytes} ({human(total_bytes)})")
    print(f"  roots : {len(roots)}")
    print(f"  dupes : {sum(len(g)-1 for _,_,g in dupe_groups)} extra copies in {len(dupe_groups)} groups")

    print("\n[top extensions]")
    for ext, cnt in sorted(ext_hist.items(), key=lambda kv: kv[1], reverse=True)[:20]:
        print(f"  {ext:>8} : {cnt}")

    if args.show_dupes:
        print("\n[duplicate groups]")
        for size, h, group in sorted(dupe_groups, key=lambda x: (-x[0], len(x[2]))):
            print(f"  • {human(size)}  hash={h[:12]}  x{len(group)}")
            for p in group:
                print(f"      {p}")
    return 0
