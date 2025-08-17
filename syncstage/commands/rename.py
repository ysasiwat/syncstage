# syncstage/commands/rename.py
from __future__ import annotations

import csv
import datetime as dt
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from ..fs import iter_files, matches_any, safe_rel
from ..utils import (
    sanitize_filename,
    split_name_ext,
    normalize_stem,
    get_created_datetime,
)

# Translation is optional; we import lazily in run()
# from ..translate import translate_cached


# ------------------------------ plan helpers ------------------------------ #

def _apply_substitutions(
    name: str,
    subs: Optional[List[Tuple[str, str]]] = None,
    resubs: Optional[List[Tuple[str, str]]] = None,
) -> str:
    s = name
    if subs:
        for a, b in subs:
            s = s.replace(a, b)
    if resubs:
        for pat, repl in resubs:
            s = re.sub(pat, repl, s)
    return s


def _write_plan_csv(plan_path: Path, rows: List[Tuple[Path, str]]) -> None:
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with plan_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["old_path", "new_name"])
        for old, new in rows:
            w.writerow([str(old), new])


def _read_plan_csv(plan_path: Path) -> List[Tuple[Path, str]]:
    rows: List[Tuple[Path, str]] = []
    with plan_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if "old_path" not in r.fieldnames or "new_name" not in r.fieldnames:
            raise ValueError("plan CSV must contain headers: old_path,new_name")
        for row in r:
            rows.append((Path(row["old_path"]), row["new_name"]))
    return rows


# ----------------------------- template render ---------------------------- #

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


# ---------------------------------- main ---------------------------------- #

def run(args, cfg):
    """Entry point for the rename subcommand."""
    roots = [Path(p) for p in (getattr(args, "roots", None) or cfg.get("roots") or [])]
    if not roots:
        print("[error] no roots provided (use --root or config)")
        return 2

    ignore = cfg.get("ignore", [])
    template: str = getattr(args, "template", "{created:%Y-%m-%d} {stem}{ext}")
    pad = int(getattr(args, "pad", "2"))
    dry = not getattr(args, "apply", False)
    rename_dirs: bool = bool(getattr(args, "include_dirs", False))

    # Optional features from CLI (safe getattr with defaults)
    no_sanitize: bool = bool(getattr(args, "no_sanitize", False))
    keep_ext: bool = bool(getattr(args, "keep_ext", False))
    case_mode: str = getattr(args, "case", "smart")
    ext_case: str = getattr(args, "ext_case", "keep")
    keep_symbols: bool = bool(getattr(args, "keep_symbols", False))
    keep_underscores: bool = bool(getattr(args, "keep_underscores", False))
    convert_dashes: bool = bool(getattr(args, "convert_dashes", False))
    sanitize_mode: str = getattr(args, "sanitize_mode", "drop")
    skip_if_already: bool = bool(getattr(args, "skip_if_already", True))
    # idempotent_prefix may be bool True (use default regex) or a regex string or None
    idempotent_prefix = getattr(args, "idempotent_prefix", None)

    # Post-processing substitutions
    subs: Optional[List[Tuple[str, str]]] = None
    resubs: Optional[List[Tuple[str, str]]] = None
    if hasattr(args, "sub") and args.sub:
        subs = [tuple(x) for x in args.sub]
    if hasattr(args, "re") and args.re:
        resubs = [tuple(x) for x in args.re]

    # Translation options (true translation; optional)
    translate_mode = getattr(args, "translate", None)  # e.g., "th-en" or None
    translate_provider = getattr(args, "translate_provider", "googletrans")
    translate_cache = getattr(args, "translate_cache", None)

    # Plan in/out
    plan_out: Optional[Path] = getattr(args, "plan_out", None)
    plan_in: Optional[Path] = getattr(args, "plan_in", None)

    # --------------------------- plan-in fast path -------------------------- #
    if plan_in:
        plan_rows = _read_plan_csv(plan_in)
        total = 0
        changed = 0
        for old_path, new_name in plan_rows:
            if not old_path.exists():
                print(f"  [skip] missing: {old_path}")
                continue
            target = old_path.with_name(new_name)
            counter_n = 2
            # minimal collision handling for plan mode
            while target.exists() and target.resolve() != old_path.resolve():
                target = target.with_name(f"{target.stem} {counter_n:0{pad}d}{target.suffix}")
                counter_n += 1
            if old_path.name == target.name:
                continue
            total += 1
            print(f"  rename(plan): {old_path.name} -> {target.name}")
            if not dry:
                try:
                    old_path.rename(target)
                    changed += 1
                except OSError as e:
                    print(f"    [warn] rename failed: {e}")
        print(f"[done] plan entries={len(plan_rows)} renamed={changed} (dry-run={dry})")
        return 0

    # ------------------------ prepare idempotency regex --------------------- #
    prefix_re = None
    if skip_if_already:
        ipp = idempotent_prefix
        if ipp is True:
            # Built-in default: 8-digit date or ISO date, followed by delimiter
            ipp = r"^(?:\d{8}|\d{4}-\d{2}-\d{2})[ _-]"
        if isinstance(ipp, str) and ipp:
            try:
                prefix_re = re.compile(ipp)
            except re.error:
                prefix_re = None

    # ------------------------------ main logic ------------------------------ #
    total = 0
    changed = 0
    planned_rows: List[Tuple[Path, str]] = []

    for root in roots:
        print(f"[rename] root={root} template='{template}' sanitize={not no_sanitize}")
        if rename_dirs:
            iterator = os.walk(root, topdown=True)
            files_only = None
            use_iterator = True
        else:
            # Collect a stable list of files with full paths (keeps subfolders)
            files_only = list(iter_files(root, ignore))
            use_iterator = False

        if use_iterator:
            # Directory + file renames in a single walk
            for dirpath, dirnames, filenames in iterator:
                d = Path(dirpath)
                # prune ignored directories
                dirnames[:] = [
                    dn
                    for dn in dirnames
                    if not matches_any((Path(safe_rel(d / dn, root))).as_posix(), ignore)
                    and not matches_any((Path(safe_rel(d / dn, root))).as_posix() + "/**", ignore)
                ]

                items: List[Path] = []
                items.extend([d / dn for dn in dirnames])    # dirs
                items.extend([d / fn for fn in filenames])   # files

                # process both
                _process_items(
                    items=items,
                    root=root,
                    ignore=ignore,
                    template=template,
                    keep_ext=keep_ext,
                    case_mode=case_mode,
                    ext_case=ext_case,
                    keep_symbols=keep_symbols,
                    keep_underscores=keep_underscores,
                    convert_dashes=convert_dashes,
                    no_sanitize=no_sanitize,
                    sanitize_mode=sanitize_mode,
                    subs=subs,
                    resubs=resubs,
                    skip_if_already=skip_if_already,
                    prefix_re=prefix_re,
                    pad=pad,
                    dry=dry,
                    total_ref=[total],
                    changed_ref=[changed],
                    planned_rows=planned_rows,
                    translate_mode=translate_mode,
                    translate_provider=translate_provider,
                    translate_cache=translate_cache,
                )
                # update counters from refs
                total = planned_rows and len(planned_rows) or total
                changed = changed_ref[0] if (changed_ref := [changed]) else changed
        else:
            # Files-only mode: process the collected file list directly
            _process_items(
                items=files_only or [],
                root=root,
                ignore=ignore,
                template=template,
                keep_ext=keep_ext,
                case_mode=case_mode,
                ext_case=ext_case,
                keep_symbols=keep_symbols,
                keep_underscores=keep_underscores,
                convert_dashes=convert_dashes,
                no_sanitize=no_sanitize,
                sanitize_mode=sanitize_mode,
                subs=subs,
                resubs=resubs,
                skip_if_already=skip_if_already,
                prefix_re=prefix_re,
                pad=pad,
                dry=dry,
                total_ref=[total],
                changed_ref=[changed],
                planned_rows=planned_rows,
                translate_mode=translate_mode,
                translate_provider=translate_provider,
                translate_cache=translate_cache,
            )
            total = planned_rows and len(planned_rows) or total

    # write plan if requested
    if plan_out:
        _write_plan_csv(plan_out, planned_rows)
        print(f"[plan] wrote {len(planned_rows)} entries to {plan_out}")

    # totals (best-effort for both paths)
    print(f"[done] candidates={len(planned_rows)} renamed={changed} (dry-run={dry})")
    return 0


# ----------------------------- worker routine ----------------------------- #

def _process_items(
    *,
    items: List[Path],
    root: Path,
    ignore: List[str],
    template: str,
    keep_ext: bool,
    case_mode: str,
    ext_case: str,
    keep_symbols: bool,
    keep_underscores: bool,
    convert_dashes: bool,
    no_sanitize: bool,
    sanitize_mode: str,
    subs: Optional[List[Tuple[str, str]]],
    resubs: Optional[List[Tuple[str, str]]],
    skip_if_already: bool,
    prefix_re: Optional[re.Pattern],
    pad: int,
    dry: bool,
    total_ref: List[int],
    changed_ref: List[int],
    planned_rows: List[Tuple[Path, str]],
    translate_mode: Optional[str],
    translate_provider: str,
    translate_cache: Optional[Path],
) -> None:
    """Processes a batch of paths (files and/or directories)."""
    # Lazy import translation to avoid hard dependency
    translate_cached = None
    if translate_mode:
        try:
            from ..translate import translate_cached as _tc  # type: ignore
            translate_cached = _tc
        except Exception as e:
            print(f"    [warn] translation disabled (import failed): {e}")

    changed = changed_ref[0] if changed_ref else 0

    for p in items:
        try:
            if p.is_symlink():
                continue
        except OSError:
            continue

        # Respect ignore patterns for files-only mode (when items came from a raw list)
        rel = safe_rel(p, root).replace("\\", "/")
        if matches_any(rel, ignore):
            continue

        try:
            st = p.stat()
        except OSError:
            continue

        created_dt = get_created_datetime(p)
        modified_dt = dt.datetime.fromtimestamp(st.st_mtime)

        # Render template
        base_name = _format_with_dates(p, template, created_dt, modified_dt)
        if not keep_ext and "{ext}" not in template:
            base_name += p.suffix

        # Work with stem only from here
        stem_part, ext_part = split_name_ext(base_name)

        # Optional: true translation of the stem
        if translate_mode == "th-en" and translate_cached:
            try:
                stem_part = translate_cached(
                    stem_part,
                    src="th",
                    dest="en",
                    provider=translate_provider,
                    cache_path=translate_cache,
                )
            except Exception as e:
                print(f"    [warn] translation failed for '{stem_part}': {e}")

        # Normalize the stem (case/symbols/spacing)
        stem_part = normalize_stem(
            stem_part,
            case_mode=case_mode,
            drop_symbols=not keep_symbols,
            convert_underscores=not keep_underscores,
            convert_dashes=convert_dashes,
        )

        # Reassemble + extension case handling
        new_name = stem_part + (ext_part if ext_part else "")
        if ext_part and ext_case != "keep":
            new_name = stem_part + (ext_part.lower() if ext_case == "lower" else ext_part.upper())

        # Post-processing substitutions (substring and/or regex)
        new_name = _apply_substitutions(new_name, subs=subs, resubs=resubs)

        # Sanitize for filesystem
        if not no_sanitize:
            new_name = sanitize_filename(new_name, mode=sanitize_mode)

        if not new_name or new_name in {".", ".."}:
            continue

        # -------------------- Idempotency (skip if already) ------------------- #
        if skip_if_already:
            # 1) exact name match
            if p.name == new_name:
                continue
            # 2) regex prefix guard (compiled once)
            if prefix_re and prefix_re.match(p.name):
                continue
            # 3) heuristic prefix guard if no regex provided:
            if prefix_re is None:
                m = re.match(r"^([^\s_\-]+)[\s_\-]+", new_name)
                if m:
                    intended_prefix = m.group(1)
                    if (
                        p.name.startswith(intended_prefix + " ")
                        or p.name.startswith(intended_prefix + "_")
                        or p.name.startswith(intended_prefix + "-")
                    ):
                        continue
        # --------------------------------------------------------------------- #

        # Collision handling
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
                if not keep_ext and "{ext}" not in template:
                    tmp += p.suffix
                sp, ep = split_name_ext(tmp)
                # repeat normalization on the new stem
                sp = normalize_stem(
                    sp,
                    case_mode=case_mode,
                    drop_symbols=not keep_symbols,
                    convert_underscores=not keep_underscores,
                    convert_dashes=convert_dashes,
                )
                tmp_full = sp + ep
                tmp_full = _apply_substitutions(tmp_full, subs=subs, resubs=resubs)
                tmp_full = sanitize_filename(tmp_full, mode=sanitize_mode) if not no_sanitize else tmp_full
                target = p.with_name(tmp_full)
            else:
                target = p.with_name(f"{Path(new_name).stem}{suffix}{Path(new_name).suffix}")
            counter += 1

        if p.name == target.name:
            continue

        planned_rows.append((p, target.name))
        print(f"  rename: {p.name}  ->  {target.name}")
        if not dry:
            try:
                p.rename(target)
                changed += 1
            except OSError as e:
                print(f"    [warn] rename failed: {e}")

    if changed_ref:
        changed_ref[0] = changed
