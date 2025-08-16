from __future__ import annotations
import os
from pathlib import Path

from ..fs import matches_any, safe_rel
from ..utils import hash_file

def ensure_within_root(path: Path, roots: list[Path]) -> Path:
    p = path.resolve()
    for r in roots:
        try:
            p.relative_to(r.resolve())
            return p
        except Exception:
            continue
    raise ValueError(f"Path {p} is not inside any configured root")

def newer_or_different(src: Path, dst: Path, checksum: bool, algo: str, block: int) -> bool:
    if not dst.exists():
        return True
    try:
        sst, dstt = src.stat(), dst.stat()
    except OSError:
        return True
    if not checksum:
        return (sst.st_size != dstt.st_size) or (int(sst.st_mtime) > int(dstt.st_mtime))
    return hash_file(src, algo, block) != hash_file(dst, algo, block)

def run(args, cfg):
    src = Path(args.source).resolve()
    tgt = Path(args.target).resolve()
    roots = [Path(p) for p in (args.roots or cfg["roots"])] or [tgt]
    _ = ensure_within_root(tgt, roots)

    ignore = cfg["ignore"]
    checksum = bool(args.checksum or cfg["mirror"]["checksum"])
    delete_extraneous = bool(args.delete or cfg["mirror"]["delete_extraneous"])
    algo = cfg["dedupe"]["algorithm"]
    block = cfg["dedupe"]["block_size"]

    print(f"[mirror] {src} -> {tgt}  checksum={checksum}  delete_extraneous={delete_extraneous}")
    copied = 0
    updated = 0
    removed = 0

    for dirpath, _, filenames in os.walk(src):
        d = Path(dirpath)
        rel_dir = safe_rel(d, src)
        if rel_dir and matches_any(rel_dir, ignore):
            continue
        for fn in filenames:
            s = d / fn
            rel = (Path(rel_dir) / fn).as_posix()
            if matches_any(rel, ignore):
                continue
            try:
                if s.is_symlink():
                    continue
            except OSError:
                continue
            dst = tgt / rel
            if newer_or_different(s, dst, checksum, algo, block):
                action = "copy " if not dst.exists() else "update"
                print(f"  {action}: {s} -> {dst}")
                if args.apply:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(s, dst)
                    if action == "copy ":
                        copied += 1
                    else:
                        updated += 1

    if delete_extraneous:
        src_set = set()
        for d, _, fns in os.walk(src):
            for fn in fns:
                src_set.add(str((Path(d) / fn).resolve().relative_to(src)))

        for d, _, fns in os.walk(tgt):
            for fn in fns:
                t = Path(d) / fn
                rel = str(t.resolve().relative_to(tgt))
                if rel not in src_set and not matches_any(rel.replace("\\","/"), ignore):
                    print(f"  rm    : {t}")
                    if args.apply:
                        try:
                            t.unlink()
                            removed += 1
                        except FileNotFoundError:
                            pass

    print(f"[done] copied={copied} updated={updated} removed={removed} (dry-run={not args.apply})")
    return 0
