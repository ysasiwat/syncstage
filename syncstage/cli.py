from __future__ import annotations
import argparse
from pathlib import Path

from .config import load_config
from .commands import scan, organize, dedupe, clean, mirror, verify, rename


def build_parser() -> argparse.ArgumentParser:
    # Create the main argument parser
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
        "--apply", action="store_true", help="Apply changes (default is dry-run)."
    )

    # Add subparsers for commands
    sub = p.add_subparsers(dest="cmd", required=True)

    # scan command
    sc = sub.add_parser("scan", help="Inventory & quick duplicate report.")
    sc.add_argument("--show-dupes", action="store_true", help="List duplicate groups.")

    # organize command
    org = sub.add_parser(
        "organize", help="Organize into YYYY/MM/<ext>/ under an 'Organized' area."
    )
    # uses global --apply

    # dedupe command
    dd = sub.add_parser(
        "dedupe", help="Find duplicates; delete or hardlink duplicates to a keeper."
    )
    dd.add_argument(
        "--hardlink",
        action="store_true",
        help="Replace dupes with hardlinks to keeper (same volume only).",
    )

    # clean command
    cl = sub.add_parser("clean", help="Remove OS junk and optional empty directories.")
    cl.add_argument(
        "--prune-empty", action="store_true", help="Prune empty directories."
    )

    # mirror command
    mi = sub.add_parser(
        "mirror", help="Mirror a source folder into a target within a sync root."
    )
    mi.add_argument("source", help="Source directory to mirror from.")
    mi.add_argument(
        "target", help="Target directory (must be within a configured root)."
    )
    mi.add_argument(
        "--checksum", action="store_true", help="Use hashes to detect changes."
    )
    mi.add_argument(
        "--delete", action="store_true", help="Delete extraneous files in target."
    )

    # verify command
    ve = sub.add_parser(
        "verify", help="Write or check a checksum manifest for a folder."
    )
    ve.add_argument("--root", required=True, help="Folder to verify.")
    ve.add_argument(
        "--write", action="store_true", help="Write manifest instead of checking it."
    )
    ve.add_argument(
        "--manifest", type=Path, help="Manifest path (default auto-named in --root)."
    )
    ve.add_argument("--algo", choices=["blake2b", "sha256"], help="Hash algorithm.")

    # rename command
    rn = sub.add_parser(
        "rename", help="Rename files (and optionally directories) using a template."
    )
    rn.add_argument(
        "--template",
        default="{created:%Y%m%d} {stem}{ext}",
        help="Tokens: {created:%%fmt}, {modified:%%fmt}, {stem}, {ext}, {parent}, {counter}. "
        "Default: '{created:%Y-%m-%d} {stem}{ext}'",
    )
    rn.add_argument(
        "--pad", default="2", help="Zero-pad width for collision counter (default 2)."
    )
    rn.add_argument(
        "--include-dirs", action="store_true", help="Also rename directories."
    )
    rn.add_argument(
        "--no-sanitize", action="store_true", help="Disable filename sanitization."
    )
    rn.add_argument(
        "--keep-ext",
        action="store_true",
        help="Do not auto-append original extension when {ext} is missing.",
    )
    rn.add_argument(
        "--case",
        choices=["smart", "title", "lower", "upper", "keep"],
        default="smart",
        help="Casing for the filename (without extension). Default: smart.",
    )
    rn.add_argument(
        "--ext-case",
        choices=["keep", "lower", "upper"],
        default="keep",
        help="Casing for the extension. Default: keep.",
    )
    rn.add_argument(
        "--keep-symbols",
        action="store_true",
        help="Do NOT strip symbols like _ \" ' ? (keeps them).",
    )
    rn.add_argument(
        "--keep-underscores",
        action="store_true",
        help="Do NOT convert underscores to spaces.",
    )
    rn.add_argument(
        "--convert-dashes", action="store_true", help="Convert '-' to spaces too."
    )
    rn.add_argument(
        "--sanitize-mode",
        choices=["drop", "underscore"],
        default="drop",
        help="How to handle OS-invalid characters; default: drop.",
    )
    # Idempotency controls
    rn.add_argument(
        "--no-skip-if-already",
        dest="skip_if_already",
        action="store_false",
        help="Do not skip files that already match the target name (default: skip).",
    )
    rn.set_defaults(skip_if_already=True)

    rn.add_argument(
        "--idempotent-prefix",
        help=(
            "Regex for a leading prefix that indicates the file was already renamed "
            "(e.g., '^(\\d{8})[ _-]' for 8-digit dates). "
            "If provided and current filename matches this prefix, the tool will skip."
        ),
    )
    # Translation (true translation, not transliteration)
    rn.add_argument(
        "--translate",
        choices=["th-en"],
        help="Translate filename stems (content) before normalization. Example: th-en (Thai → English).",
    )
    rn.add_argument(
        "--translate-provider",
        choices=["googletrans", "gcloud"],
        default="googletrans",
        help="Translation backend: 'googletrans' (no key) or 'gcloud' (requires Google Cloud credentials).",
    )
    rn.add_argument(
        "--translate-cache",
        type=Path,
        help="Path to a JSON cache for translations to avoid repeated calls (optional).",
    )

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config(args.config)

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
