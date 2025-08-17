from __future__ import annotations

import argparse
import os
from pathlib import Path

from .config import load_config
from .commands import scan, organize, dedupe, clean, mirror, verify, rename


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="syncstage",
        description="Manage files inside local OneDrive/Google Drive folders (no cloud APIs).",
    )
    p.add_argument("-c", "--config", type=Path, help="Path to JSON config.")
    p.add_argument(
        "--root",
        dest="roots",
        action="append",
        help="Add a sync root folder (repeatable).",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry-run).",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    # --- scan ---
    sc = sub.add_parser("scan", help="Inventory & quick duplicate report.")
    sc.add_argument("--show-dupes", action="store_true", help="List duplicate groups.")

    # --- organize ---
    sub.add_parser("organize", help="Organize into YYYY/MM/<ext>/ under an 'Organized' area.")

    # --- dedupe ---
    dd = sub.add_parser("dedupe", help="Find duplicates; delete or hardlink duplicates to a keeper.")
    dd.add_argument(
        "--hardlink",
        action="store_true",
        help="Replace dupes with hardlinks to keeper (same volume only).",
    )

    # --- clean ---
    cl = sub.add_parser("clean", help="Remove OS junk and optional empty directories.")
    cl.add_argument("--prune-empty", action="store_true", help="Prune empty directories.")

    # --- mirror ---
    mi = sub.add_parser("mirror", help="Mirror a source folder into a target within a sync root.")
    mi.add_argument("source", help="Source directory to mirror from.")
    mi.add_argument("target", help="Target directory (must be within a configured root).")
    mi.add_argument("--checksum", action="store_true", help="Use hashes to detect changes.")
    mi.add_argument("--delete", action="store_true", help="Delete extraneous files in target.")

    # --- verify ---
    ve = sub.add_parser("verify", help="Write or check a checksum manifest for a folder.")
    ve.add_argument("--root", required=True, help="Folder to verify.")
    ve.add_argument("--write", action="store_true", help="Write manifest instead of checking it.")
    ve.add_argument("--manifest", type=Path, help="Manifest path (default auto-named in --root).")
    ve.add_argument("--algo", choices=["blake2b", "sha256"], help="Hash algorithm.")

    # --- rename ---
    rn = sub.add_parser("rename", help="Rename files (and optionally directories) using a template.")
    # defaults = None so config can supply values
    rn.add_argument("--template", default=None, help="Rename template.")
    rn.add_argument("--pad", default=None, help="Zero-pad width (default 2).")
    rn.add_argument("--include-dirs", action="store_true", default=None, help="Also rename directories.")
    rn.add_argument("--no-sanitize", action="store_true", default=None, help="Disable filename sanitization.")
    rn.add_argument("--keep-ext", action="store_true", default=None, help="Keep original extension if {ext} missing.")
    rn.add_argument("--case", choices=["smart", "title", "lower", "upper", "keep"], default=None)
    rn.add_argument("--ext-case", choices=["keep", "lower", "upper"], default=None)
    rn.add_argument("--keep-symbols", action="store_true", default=None)
    rn.add_argument("--keep-underscores", action="store_true", default=None)
    rn.add_argument("--convert-dashes", action="store_true", default=None)
    rn.add_argument("--sanitize-mode", choices=["drop", "underscore"], default=None)
    rn.add_argument("--no-skip-if-already", dest="skip_if_already", action="store_false", default=None)
    rn.add_argument("--idempotent-prefix", default=None)
    rn.add_argument("--translate", choices=["th-en"], default=None)
    rn.add_argument("--translate-provider", choices=["googletrans", "gcloud"], default=None)
    rn.add_argument("--translate-cache", type=Path, default=None)
    rn.add_argument("--plan-out", type=Path, default=None)
    rn.add_argument("--plan-in", type=Path, default=None)
    rn.add_argument("--sub", nargs=2, action="append", default=None)
    rn.add_argument("--re", nargs=2, action="append", default=None)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if os.getenv("SYNCSTAGE_DEBUG") == "1":
        print(f"[debug] parsed args: {args}")

    cfg = load_config(getattr(args, "config", None))

    if args.cmd == "scan":
        return scan.run(args, cfg)
    if args.cmd == "organize":
        return organize.run(args, cfg)
    if args.cmd == "dedupe":
        return dedupe.run(args, cfg)
    if args.cmd == "clean":
        return clean.run(args, cfg)
    if args.cmd == "mirror":
        return mirror.run(args, cfg)
    if args.cmd == "verify":
        return verify.run(args, cfg)
    if args.cmd == "rename":
        return rename.run(args, cfg)

    parser.print_help()
    return 1
