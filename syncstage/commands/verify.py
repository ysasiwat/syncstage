from __future__ import annotations
from pathlib import Path
import datetime as dt

from ..fs import iter_files
from ..utils import hash_file

def run(args, cfg):
    root = Path(args.root).resolve()
    algo = (args.algo or cfg["dedupe"]["algorithm"]).lower()
    block = cfg["dedupe"]["block_size"]
    ignore = cfg["ignore"]

    manifest = args.manifest or root / f"MANIFEST-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.{algo}.txt"
    mode = "write" if args.write else "check"
    print(f"[verify] {mode} manifest={manifest}")

    if args.write:
        lines = []
        for p in iter_files(root, ignore):
            h = hash_file(p, algo, block)
            rel = str(p.relative_to(root)).replace("\\","/")
            lines.append(f"{h}  {rel}\n")
            print(f"  {rel}")
        if args.apply:
            manifest.parent.mkdir(parents=True, exist_ok=True)
            with open(manifest, "w", encoding="utf-8") as f:
                f.writelines(lines)
        print(f"[done] wrote {len(lines)} entries (dry-run={not args.apply})")
        return 0

    if not Path(manifest).exists():
        print(f"[error] manifest not found: {manifest}")
        return 2

    with open(manifest, "r", encoding="utf-8") as f:
        entries = [line.strip().split(None, 1) for line in f if line.strip()]
    mismatches = 0
    missing = 0
    for h, rel in entries:
        p = root / rel
        if not p.exists():
            print(f"  MISSING: {rel}")
            missing += 1
            continue
        hh = hash_file(p, algo, block)
        if hh != h:
            print(f"  MISMATCH: {rel}")
            mismatches += 1
    print(f"[done] checked={len(entries)} mismatches={mismatches} missing={missing}")
    return 0
