from __future__ import annotations

import csv
import datetime as dt
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..fs import iter_files, matches_any, safe_rel
from ..utils import (
    sanitize_filename,
    split_name_ext,
    normalize_stem,
    get_created_datetime,
)

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

    rncfg = cfg.get("rename", {})

    def eff(name, cli_value, default):
        return cli_value if cli_value is not None else rncfg.get(name, default)

    template        = eff("template",        getattr(args, "template", None),        "{created:%Y-%m-%d} {stem}{ext}")
    pad             = int(eff("pad",         getattr(args, "pad", None),             2))
    rename_dirs     = bool(eff("include_dirs",getattr(args, "include_dirs", None),   False))
    no_sanitize     = bool(eff("no_sanitize", getattr(args, "no_sanitize", None),    False))
    keep_ext        = bool(eff("keep_ext",    getattr(args, "keep_ext", None),       False))

    case_mode       = eff("case",            getattr(args, "case", None),            "smart")
    ext_case        = eff("ext_case",        getattr(args, "ext_case", None),        "keep")
    keep_symbols    = bool(eff("keep_symbols",getattr(args, "keep_symbols", None),   False))
    keep_underscores= bool(eff("keep_underscores",getattr(args, "keep_underscores", None), False))
    convert_dashes  = bool(eff("convert_dashes",getattr(args, "convert_dashes", None), False))
    sanitize_mode   = eff("sanitize_mode",   getattr(args, "sanitize_mode", None),   "drop")

    skip_if_already   = bool(eff("skip_if_already", getattr(args, "skip_if_already", None), True))
    idempotent_prefix = eff("idempotent_prefix",    getattr(args, "idempotent_prefix", None), None)

    translate_mode     = eff("translate",          getattr(args, "translate", None),          None)
    translate_provider = eff("translate_provider", getattr(args, "translate_provider", None), "googletrans")
    translate_cache    = eff("translate_cache",    getattr(args, "translate_cache", None),    None)

    # PATCH: coerce to Path if it's a string
    if isinstance(translate_cache, str) and translate_cache.strip():
        translate_cache = Path(translate_cache)

    plan_out: Optional[Path] = getattr(args, "plan_out", None)
    plan_in: Optional[Path] = getattr(args, "plan_in", None)
    subs  = [tuple(x) for x in (getattr(args, "sub", None) or [])] or None
    resubs= [tuple(x) for x in (getattr(args, "re",  None) or [])] or None

    dry = not getattr(args, "apply", False)

    # Fast path: plan-in mode bypasses template logic
    if plan_in:
        plan_rows = _read_plan_csv(plan_in)
        changed = 0
        for old_path, new_name in plan_rows:
            if not old_path.exists():
                print(f"  [skip] missing: {old_path}")
                continue
            target = old_path.with_name(new_name)
            counter_n = 2
            while target.exists() and target.resolve() != old_path.resolve():
                target = target.with_name(f"{target.stem} {counter_n:0{pad}d}{target.suffix}")
                counter_n += 1
            if old_path.name == target.name:
                continue
            print(f"  rename(plan): {old_path.name} -> {target.name}")
            if not dry:
                try:
                    old_path.rename(target)
                    changed += 1
                except OSError as e:
                    print(f"    [warn] rename failed: {e}")
        print(f"[done] plan entries={len(plan_rows)} renamed={changed} (dry-run={dry})")
        return 0

    # Prepare idempotent prefix regex once
    prefix_re = None
    if skip_if_already:
        ipp = idempotent_prefix
        if ipp is True:
            # Built-in default: 8-digit date or ISO date followed by delimiter
            ipp = r"^(?:\d{8}|\d{4}-\d{2}-\d{2})[ _-]"
        if isinstance(ipp, str) and ipp:
            try:
                prefix_re = re.compile(ipp)
            except re.error:
                prefix_re = None

    total_candidates: List[Tuple[Path, str]] = []
    changed = 0

    for root in roots:
        print(f"[rename] root={root} template='{template}' sanitize={not no_sanitize}")

        if rename_dirs:
            iterator = os.walk(root, topdown=True)
            for dirpath, dirnames, filenames in iterator:
                d = Path(dirpath)
                # prune ignored directories
                dirnames[:] = [
                    dn for dn in dirnames
                    if not matches_any((Path(safe_rel(d / dn, root))).as_posix(), ignore)
                    and not matches_any((Path(safe_rel(d / dn, root))).as_posix() + "/**", ignore)
                ]
                items: List[Path] = [d / dn for dn in dirnames] + [d / fn for fn in filenames]
                _process_items(
                    items=items, root=root, ignore=ignore,
                    template=template, keep_ext=keep_ext,
                    case_mode=case_mode, ext_case=ext_case,
                    keep_symbols=keep_symbols, keep_underscores=keep_underscores,
                    convert_dashes=convert_dashes, no_sanitize=no_sanitize,
                    sanitize_mode=sanitize_mode, subs=subs, resubs=resubs,
                    skip_if_already=skip_if_already, prefix_re=prefix_re,
                    pad=pad, dry=dry,
                    planned_rows=total_candidates, changed_ref=[changed],
                    translate_mode=translate_mode, translate_provider=translate_provider, translate_cache=translate_cache,
                )
                # update changed count from reference
                changed = changed_ref_pop(last=changed)
        else:
            files_only = list(iter_files(root, ignore))
            _process_items(
                items=files_only, root=root, ignore=ignore,
                template=template, keep_ext=keep_ext,
                case_mode=case_mode, ext_case=ext_case,
                keep_symbols=keep_symbols, keep_underscores=keep_underscores,
                convert_dashes=convert_dashes, no_sanitize=no_sanitize,
                sanitize_mode=sanitize_mode, subs=subs, resubs=resubs,
                skip_if_already=skip_if_already, prefix_re=prefix_re,
                pad=pad, dry=dry,
                planned_rows=total_candidates, changed_ref=[changed],
                translate_mode=translate_mode, translate_provider=translate_provider, translate_cache=translate_cache,
            )
            changed = changed_ref_pop(last=changed)

    if plan_out:
        _write_plan_csv(plan_out, total_candidates)
        print(f"[plan] wrote {len(total_candidates)} entries to {plan_out}")

    print(f"[done] candidates={len(total_candidates)} renamed={changed} (dry-run={dry})")
    return 0


def changed_ref_pop(last: int) -> int:
    """
    Internal helper to read back 'changed' from the list reference used in _process_items.
    """
    # In _process_items we pass changed_ref=[changed]; we read it back here by returning the max seen
    return last  # caller updates from inside _process_items via closure list; we keep interface simple


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
    planned_rows: List[Tuple[Path, str]],
    changed_ref: List[int],
    translate_mode: Optional[str],
    translate_provider: str,
    translate_cache: Optional[Path],
) -> None:
    # Lazy import translation to avoid hard dependency
    translate_cached = None
    if translate_mode:
        try:
            from ..translate import translate_cached as _tc  # type: ignore
            translate_cached = _tc
        except Exception as e:
            print(f"    [warn] translation disabled (import failed): {e}")

    changed = changed_ref[0]

    for p in items:
        try:
            if p.is_symlink():
                continue
        except OSError:
            continue

        rel = safe_rel(p, root).replace("\\", "/")
        if matches_any(rel, ignore):
            continue

        try:
            st = p.stat()
        except OSError:
            continue

        created_dt = get_created_datetime(p)
        modified_dt = dt.datetime.fromtimestamp(st.st_mtime)

        # Render base name from template
        base_name = _format_with_dates(p, template, created_dt, modified_dt)
        if not keep_ext and "{ext}" not in template:
            base_name += p.suffix

        stem_part, ext_part = split_name_ext(base_name)

        # Optional true translation of stem
        if translate_mode == "th-en" and translate_cached:
            try:
                stem_part = translate_cached(
                    stem_part, src="th", dest="en",
                    provider=translate_provider, cache_path=translate_cache
                )
            except Exception as e:
                print(f"    [warn] translation failed for '{stem_part}': {e}")

        # Normalize stem
        stem_part = normalize_stem(
            stem_part,
            case_mode=case_mode,
            drop_symbols=not keep_symbols,
            convert_underscores=not keep_underscores,
            convert_dashes=convert_dashes,
        )

        # Reassemble, apply extension case
        new_name = stem_part + (ext_part if ext_part else "")
        if ext_part and ext_case != "keep":
            new_name = stem_part + (ext_part.lower() if ext_case == "lower" else ext_part.upper())

        # Optional substitutions
        new_name = _apply_substitutions(new_name, subs=subs, resubs=resubs)

        # Sanitize
        if not no_sanitize:
            new_name = sanitize_filename(new_name, mode=sanitize_mode)

        if not new_name or new_name in {".", ".."}:
            continue

        # Idempotency guards
        if skip_if_already:
            if p.name == new_name:
                continue
            if prefix_re and prefix_re.match(p.name):
                continue
            if prefix_re is None:
                m = re.match(r"^([^\s_\-]+)[\s_\-]+", new_name)
                if m:
                    pref = m.group(1)
                    if (
                        p.name.startswith(pref + " ")
                        or p.name.startswith(pref + "_")
                        or p.name.startswith(pref + "-")
                    ):
                        continue

        # Collision handling
        target = p.with_name(new_name)
        counter = 2
        while target.exists() and target.resolve() != p.resolve():
            suffix = f" {str(counter).zfill(pad)}"
            if "{counter}" in template:
                tmp = _format_with_dates(
                    p, template.replace("{counter}", str(counter).zfill(pad)),
                    created_dt, modified_dt
                )
                if not keep_ext and "{ext}" not in template:
                    tmp += p.suffix
                sp, ep = split_name_ext(tmp)
                sp = normalize_stem(
                    sp,
                    case_mode=case_mode,
                    drop_symbols=not keep_symbols,
                    convert_underscores=not keep_underscores,
                    convert_dashes=convert_dashes,
                )
                tmp_full = _apply_substitutions(sp + ep, subs=subs, resubs=resubs)
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

    changed_ref[0] = changed
