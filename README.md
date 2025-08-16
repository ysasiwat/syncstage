# SyncStage

A lean, cross-platform CLI to manage files **inside local OneDrive/Google Drive sync folders**.  
No cloud APIs. The native sync clients do the uploading.

## Features
- `scan` – inventory + quick duplicate estimate
- `organize` – sort files into `YYYY/MM/<ext>/...`
- `dedupe` – remove/replace duplicates (optional hardlink)
- `clean` – delete OS junk; prune empty directories
- `mirror` – mirror a source -> target drive folder
- `verify` – write/check checksum manifests
- `rename` – flexible renamer with date tokens, smart casing, and symbol cleanup

**Dry-run by default.** Use `--apply` to commit changes.

## Install (editable dev)
```bash
git clone https://github.com/ysasiwat/syncstage.git
cd syncstage
pip install -e .
```

## Basic usage
```bash
# 1. Scan a OneDrive folder and show duplicate groups
syncstage --root "C:/Users/you/OneDrive" scan --show-dupes

# 2. Organize files into Organized/YYYY/MM/<ext>/...
syncstage -c examples/syncstage.config.json --apply organize

# 3. Rename files to prepend created date + smart capitalization
syncstage --root "/path/to/GoogleDrive/My Drive" --apply rename \
    --template "{created:%Y-%m-%d} {stem}{ext}"

# 4. Remove duplicates (delete or replace with hardlinks)
syncstage --root "/path/OneDrive" --apply dedupe
syncstage --root "/path/OneDrive" --apply dedupe --hardlink

# 5. Clean junk and prune empty directories
syncstage --root "/path/Drive" --apply clean --prune-empty

# 6. Mirror a folder into a sync root
syncstage --apply mirror "/data/photos" "C:/Users/you/OneDrive/Photos"

# 7. Write and verify checksum manifest
syncstage verify --root "/path/Drive/Projects" --write --apply
syncstage verify --root "/path/Drive/Projects" --manifest MANIFEST-20250305.blake2b.txt
```

## Rename Templates
You can use tokens in rename templates:
- {stem} – original filename without extension
- {ext} – file extension (with dot, e.g. .pdf)
- {parent} – parent directory name
- {created:%Y-%m-%d} – creation date (strftime format)
- {modified:%H%M%S} – modified time (strftime format)
- {counter} – auto-increment counter for collisions

### Example
```
syncstage --root "/path/Drive" --apply rename \
  --template "{created:%Y-%m-%d} {stem}{ext}" \
  --ext-case lower
```

## Config file
Example: examples/syncstage.config.json
```
{
  "roots": ["C:/Users/you/OneDrive"],
  "ignore": [".DS_Store","._*","Thumbs.db","desktop.ini","~$*","*.tmp"],
  "organize": {
    "destination": "{root}/Organized",
    "by": "date_ext",
    "date_format": "%Y/%m",
    "lowercase_ext": true
  },
  "mirror": { "checksum": false, "delete_extraneous": false },
  "dedupe": { "algorithm": "blake2b", "block_size": 1048576 }
}
```

## Tests
```
pip install pytest
pytest -q
```

## Roadmap
- [ ] Add EXIF-based rename for photos (optional Pillow dependency)
- [ ] Add watch mode to monitor and auto-organize
- [ ] Add GUI wrapper (optional, later)