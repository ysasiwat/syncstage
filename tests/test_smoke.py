from pathlib import Path
import os
import re
import io

import pytest

from syncstage.commands import scan as cmd_scan
from syncstage.commands import organize as cmd_organize
from syncstage.commands import dedupe as cmd_dedupe
from syncstage.commands import clean as cmd_clean
from syncstage.commands import mirror as cmd_mirror
from syncstage.commands import verify as cmd_verify
from syncstage.commands import rename as cmd_rename
from .conftest import ns, write_file

def test_scan_runs_and_shows_dupes(sandbox, cfg_default, capsys):
    root = sandbox["root"]
    # two identical files (dupes), and one unique
    f1 = write_file(root / "A/file1.txt", "hello world")
    f2 = write_file(root / "B/file2.txt", "hello world")  # duplicate content
    f3 = write_file(root / "C/file3.bin", b"\x00\x01\x02")

    args = ns(roots=[str(root)], cmd="scan", show_dupes=True, apply=False)
    rc = cmd_scan.run(args, cfg_default)
    captured = capsys.readouterr().out
    assert rc == 0
    assert "summary" in captured.lower()
    assert "duplicate groups" in captured.lower()

def test_organize_moves_into_date_ext(sandbox, cfg_default, fixed_time, capsys):
    root = sandbox["root"]
    f = write_file(root / "inbox" / "photo.JPG", "img", mtime=fixed_time)

    args = ns(roots=[str(root)], cmd="organize", apply=True)
    rc = cmd_organize.run(args, cfg_default)
    assert rc == 0

    # Expect Organized/YYYY/MM/jpg/photo.JPG (ext lowercased per config)
    yyyy = "2024"; mm = "03"
    expected = root / "Organized" / yyyy / mm / "jpg" / "photo.JPG"
    assert expected.exists()
    assert not f.exists()

def test_rename_template_with_normalization(sandbox, cfg_default, fixed_time):
    root = sandbox["root"]
    src = write_file(root / 'docs' / 'my_file "draft"?.TXT', "x", mtime=fixed_time)

    # Use modified date (deterministic) and enforce lower-case extension
    args = ns(
        roots=[str(root)],
        cmd="rename",
        template="{modified:%Y-%m-%d} {stem}{ext}",
        pad="2",
        include_dirs=False,
        no_sanitize=False,
        keep_ext=False,
        case="smart",
        ext_case="lower",
        keep_symbols=False,
        keep_underscores=False,
        convert_dashes=False,
        sanitize_mode="drop",
        apply=True,
    )
    rc = cmd_rename.run(args, cfg_default)
    assert rc == 0

    expected = root / "docs" / "2024-03-05 My File Draft.txt"
    assert expected.exists()
    assert not src.exists()

def test_dedupe_removes_duplicate_files(sandbox, cfg_default):
    root = sandbox["root"]
    a = write_file(root / "dup" / "same1.bin", b"abcdefg")
    b = write_file(root / "dup" / "same2.bin", b"abcdefg")  # duplicate
    c = write_file(root / "dup" / "other.bin", b"xyz")

    args = ns(roots=[str(root)], cmd="dedupe", hardlink=False, apply=True)
    rc = cmd_dedupe.run(args, cfg_default)
    assert rc == 0
    # One of the duplicate files should remain; other removed
    assert (root / "dup" / "same1.bin").exists() ^ (root / "dup" / "same2.bin").exists()
    assert (root / "dup" / "other.bin").exists()

def test_clean_removes_junk_and_prunes(sandbox, cfg_default):
    root = sandbox["root"]
    junk1 = write_file(root / "X" / ".DS_Store", "")
    junk2 = write_file(root / "X" / "Thumbs.db", "")
    normal = write_file(root / "X" / "keep.txt", "ok")

    args = ns(roots=[str(root)], cmd="clean", prune_empty=True, apply=True)
    rc = cmd_clean.run(args, cfg_default)
    assert rc == 0
    assert not junk1.exists()
    assert not junk2.exists()
    # Directory X should still exist because keep.txt is inside
    assert (root / "X").exists()

def test_mirror_copy_and_delete_extraneous(sandbox, cfg_default):
    src = sandbox["src"]
    tgt_base = sandbox["tgt"]
    mirror_root = tgt_base  # configured root; target folder inside it
    target = tgt_base / "Dest"

    # Source has one file
    sfile = write_file(src / "p" / "a.txt", "data")
    # Target has an extra file that should be deleted with --delete
    extraneous = write_file(target / "old.txt", "old")

    # 1) copy/update
    args = ns(
        roots=[str(mirror_root)], cmd="mirror",
        source=str(src), target=str(target),
        checksum=False, delete=False, apply=True
    )
    rc = cmd_mirror.run(args, cfg_default)
    assert rc == 0
    assert (target / "p" / "a.txt").exists()

    # 2) delete extraneous
    args2 = ns(
        roots=[str(mirror_root)], cmd="mirror",
        source=str(src), target=str(target),
        checksum=False, delete=True, apply=True
    )
    rc2 = cmd_mirror.run(args2, cfg_default)
    assert rc2 == 0
    assert not (target / "old.txt").exists()

def test_verify_write_and_check(sandbox, cfg_default, capsys):
    root = sandbox["root"]
    f1 = write_file(root / "docs" / "a.txt", "aaa")
    f2 = write_file(root / "docs" / "b.txt", "bbb")

    # Write manifest
    args_w = ns(cmd="verify", root=str(root), write=True, manifest=None, algo=None, apply=True)
    rc_w = cmd_verify.run(args_w, cfg_default)
    assert rc_w == 0

    # Find the auto-created manifest in root
    manifests = list(p for p in root.iterdir() if p.name.startswith("MANIFEST-") and p.suffix in (".blake2b.txt", ".sha256.txt", ".txt"))
    assert manifests, "manifest not created"
    manifest = sorted(manifests)[-1]

    # Check manifest (should be clean)
    args_c = ns(cmd="verify", root=str(root), write=False, manifest=manifest, algo=None, apply=False)
    rc_c = cmd_verify.run(args_c, cfg_default)
    assert rc_c == 0

    # Modify a file to cause mismatch
    (root / "docs" / "a.txt").write_text("changed")
    rc_c2 = cmd_verify.run(args_c, cfg_default)
    assert rc_c2 == 0  # command returns 0 but reports mismatches in output
