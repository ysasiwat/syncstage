from __future__ import annotations
import datetime as dt
from pathlib import Path

from ..fs import iter_files
from ..utils import atomic_move_or_replace

def run(args, cfg):
    roots = [Path(p) for p in (args.roots or cfg["roots"])]
    ignore = cfg["ignore"]
    org = cfg["organize"]
    moved = 0

    for root in roots:
        dest_root = Path(org["destination"].format(root=str(root)))
        print(f"[organize] root={root} -> {dest_root}  by={org['by']}")
        for p in iter_files(root, ignore):
            try:
                st = p.stat()
            except OSError:
                continue
            try:
                p.resolve().relative_to(dest_root.resolve())
                continue
            except Exception:
                pass
            mtime = dt.datetime.fromtimestamp(st.st_mtime)
            date_path = mtime.strftime(org["date_format"])
            ext = p.suffix.lower().lstrip(".") if org.get("lowercase_ext", True) else p.suffix.lstrip(".")
            ext = ext or "noext"

            if org["by"] == "date":
                rel_dest = Path(date_path) / p.name
            elif org["by"] == "ext":
                rel_dest = Path(ext) / p.name
            else:
                rel_dest = Path(date_path) / ext / p.name

            dst = dest_root / rel_dest
            if dst.exists():
                try:
                    if dst.stat().st_size == st.st_size and int(dst.stat().st_mtime) == int(st.st_mtime):
                        continue
                except OSError:
                    pass
                stem = dst.stem
                suffix = dst.suffix
                base = dst.with_suffix("")
                i = 1
                while dst.exists():
                    dst = base.with_name(f"{stem} ({i})").with_suffix(suffix)
                    i += 1

            print(f"  move: {p}  ->  {dst}")
            if args.apply:
                atomic_move_or_replace(p, dst)
                moved += 1

    print(f"[done] moved={moved} (dry-run={not args.apply})")
    return 0
