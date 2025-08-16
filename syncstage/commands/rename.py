from __future__ import annotations
import datetime as dt
import re
from pathlib import Path

from ..fs import iter_files, matches_any, safe_rel
from ..utils import (
    sanitize_filename,
    split_name_ext,
    normalize_stem,
    get_created_datetime,
)

from ..translate import translate_cached
import os


def _format_with_dates(
    p: Path,
    template: str,
    created_dt: dt.datetime,
    modified_dt: dt.datetime,
    counter: int | None = None,
) -> str:
    """
    Tokens:
      {created:%Y-%m-%d}, {modified:%H%M%S}, {stem}, {ext}, {parent}, {counter}
    {ext} includes the leading dot.
    """
    ext = p.suffix
    stem = p.stem
    parent = p.parent.name

    def sub_date(m: re.Match):
        kind = m.group(1)
        fmt = m.group(2)
        base = created_dt if kind == "created" else modified_dt
        return base.strftime(fmt or "%Y-%m-%d")

    s = template
    s = re.sub(r"\{(created|modified)(?::(%[^}]+))?\}", sub_date, s)
    s = s.replace("{stem}", stem).replace("{ext}", ext).replace("{parent}", parent)
    if "{counter}" in s:
        s = s.replace("{counter}", f"{counter}" if counter is not None else "1")
    return s


def run(args, cfg):
    roots = [Path(p) for p in (args.roots or cfg["roots"])]
    if not roots:
        print("[error] no roots provided (use --root or config)")
        return 2

    ignore = cfg["ignore"]
    template = args.template
    pad = int(args.pad)
    dry = not args.apply
    rename_dirs = args.include_dirs

    total = 0
    changed = 0

    for root in roots:
        print(
            f"[rename] root={root} template='{template}' sanitize={not args.no_sanitize}"
        )
        if rename_dirs:
            iterator = __import__("os").walk(root)
        else:
            iterator = ((str(root), [], [p.name for p in iter_files(root, ignore)]),)

        for dirpath, dirnames, filenames in iterator:
            d = Path(dirpath)

            if rename_dirs:
                # prune ignored directories
                dirnames[:] = [
                    dn
                    for dn in dirnames
                    if not matches_any(
                        (Path(safe_rel(d / dn, root))).as_posix(), ignore
                    )
                    and not matches_any(
                        (Path(safe_rel(d / dn, root))).as_posix() + "/**", ignore
                    )
                ]

            items = []
            if rename_dirs:
                items.extend([d / dn for dn in dirnames])
                items.extend([d / fn for fn in filenames])
            else:
                items.extend([d / fn for fn in filenames])

            for p in items:
                try:
                    if p.is_symlink():
                        continue
                except OSError:
                    continue

                rel = safe_rel(p, root).replace("\\", "/")
                if not rename_dirs and matches_any(rel, ignore):
                    continue

                try:
                    st = p.stat()
                except OSError:
                    continue

                created_dt = get_created_datetime(p)
                modified_dt = dt.datetime.fromtimestamp(st.st_mtime)

                base_name = _format_with_dates(p, template, created_dt, modified_dt)
                if not args.keep_ext and "{ext}" not in template:
                    base_name += p.suffix

                # --- NEW: translate stem (true translation) BEFORE normalization ---
                stem_part, ext_part = split_name_ext(base_name)
                if args.translate == "th-en":
                    # Translate Thai → English only on the stem content
                    try:
                        translated = translate_cached(
                            stem_part,
                            src="th",
                            dest="en",
                            provider=args.translate_provider,
                            cache_path=args.translate_cache,
                        )
                        # Replace stem with translated text for subsequent normalization
                        stem_part = translated
                    except Exception as e:
                        # Fail-safe: if translation fails, keep original stem
                        print(f"    [warn] translation failed for '{stem_part}': {e}")

                # Now normalize the (possibly translated) stem
                stem_part = normalize_stem(
                    stem_part,
                    case_mode=args.case,
                    drop_symbols=not args.keep_symbols,
                    convert_underscores=not args.keep_underscores,
                    convert_dashes=args.convert_dashes,
                )

                new_name = stem_part + (ext_part if ext_part else "")
                if ext_part and args.ext_case != "keep":
                    new_name = stem_part + (
                        ext_part.lower()
                        if args.ext_case == "lower"
                        else ext_part.upper()
                    )

                if not args.no_sanitize:
                    new_name = sanitize_filename(new_name, mode=args.sanitize_mode)

                if not new_name or new_name in {".", ".."}:
                    continue

                # ---------------- Idempotency guards ----------------
                # 1) Exact-match guard: if the computed name equals current name, skip.
                if args.skip_if_already and p.name == new_name:
                    continue

                # 2) Prefix guard:
                #    If user supplies --idempotent-prefix REGEX and the current name
                #    already starts with that prefix, assume it's already renamed and skip.
                if args.skip_if_already and args.idempotent_prefix:
                    try:
                        prefix_re = re.compile(args.idempotent_prefix)
                        if prefix_re.match(p.name):
                            continue
                    except re.error as _e:
                        # Bad regex? Ignore the prefix guard but still proceed.
                        pass

                # 3) Heuristic prefix guard (no regex provided):
                #    Use the first token of new_name up to the first space/underscore/hyphen
                #    as the intended prefix and skip if current name starts with it.
                if args.skip_if_already and not args.idempotent_prefix:
                    # Extract prefix token (e.g., "20250816" from "20250816 Report.txt")
                    m = re.match(r"^([^\s_\-]+)[\s_\-]+", new_name)
                    if m:
                        intended_prefix = m.group(1)
                        if (
                            p.name.startswith(intended_prefix + " ")
                            or p.name.startswith(intended_prefix + "_")
                            or p.name.startswith(intended_prefix + "-")
                        ):
                            continue
                # ----------------------------------------------------

                target = p.with_name(new_name)
                counter = 2
                while target.exists() and target.resolve() != p.resolve():
                    suffix = f" {str(counter).zfill(pad)}"
                    if "{counter}" in template:
                        tmp = _format_with_dates(
                            p,
                            template.replace("{counter}", str(counter).zfill(pad)),
                            created_dt,
                            modified_dt,
                        )
                        if not args.keep_ext and "{ext}" not in template:
                            tmp += p.suffix
                        sp, ep = split_name_ext(tmp)
                        sp = normalize_stem(
                            sp,
                            args.case,
                            not args.keep_symbols,
                            not args.keep_underscores,
                            args.convert_dashes,
                        )
                        tmp = (
                            sanitize_filename(sp + ep, mode=args.sanitize_mode)
                            if not args.no_sanitize
                            else sp + ep
                        )
                        target = p.with_name(tmp)
                    else:
                        target = p.with_name(
                            f"{Path(new_name).stem}{suffix}{Path(new_name).suffix}"
                        )
                    counter += 1

                if p.name == target.name:
                    continue

                total += 1
                print(f"  rename: {p.name}  ->  {target.name}")
                if args.apply:
                    try:
                        p.rename(target)
                        changed += 1
                    except OSError as e:
                        print(f"    [warn] rename failed: {e}")

    print(f"[done] candidates={total} renamed={changed} (dry-run={dry})")
    return 0
