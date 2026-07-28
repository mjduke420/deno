# RAW Library

A Lightroom-style photo manager and RAW editor: catalog your shoots, cull them with
star ratings, develop the keepers with GPU AI denoise, and batch-export portfolio JPEGs.

Non-destructive and reference-in-place — your original RAW files are never modified,
moved or copied.

## Running

```bash
.venv\Scripts\python.exe main.py            # opens the library
.venv\Scripts\python.exe main.py photo.CR3  # opens one file straight into Develop
```

## Modules

| Key | Module | What it does |
|-----|--------|--------------|
| `G` | **Library** | Thumbnail grid, folders, rating and filtering |
| `D` | **Develop** | Denoise, exposure, lens corrections, single export |

### Library

- **Add Folder…** (`Ctrl+O`) catalogs a folder recursively. Re-scanning is safe — it
  refreshes file metadata and *never* touches your ratings or edits.
- Filter by folder, minimum star rating, flag and colour label.
- **Batch Export** sends either the selected photos or everything matching the current
  filter to a folder of JPEGs, each rendered with its own saved adjustments.

Culling keys (apply to the whole selection):

| Keys | Action |
|------|--------|
| `0`–`5` | Set star rating |
| `P` / `X` / `U` | Pick / reject / unflag |
| `6` `7` `8` `9` | Red / yellow / green / blue label |
| `` ` `` | Clear colour label |
| `Enter` or double-click | Open in Develop |

### Develop

Adjustments are saved per photo automatically — switching photos, returning to the
library, or quitting all flush your edits to the catalog first.

- **AI Denoise** runs NAFNet-SIDD on the GPU (~13s for a 24MP frame on an RTX 3090).
  It is per-photo and must be re-run after reopening a photo.
- `\` toggles the before/after view.
- Batch export applies exposure and lens corrections but **not** AI denoise, since that
  is a multi-second GPU pass per photo.

## Where your data lives

```
%LOCALAPPDATA%\RawDenoise\
  catalog.db     <- folders, photos, ratings, flags, labels, per-photo edits
  thumbs\        <- cached grid thumbnails (safe to delete; they regenerate)
models\          <- NAFNet denoise weights (~443 MB, downloaded on first denoise)
```

**`catalog.db` is the only irreplaceable file** — it holds every rating and edit you've
made. Back it up. Deleting `thumbs/` only costs regeneration time.

## Supported formats

RAW: CR3, CR2, ORF, NEF, ARW, DNG, RAF, RW2, PEF, SRW — plus JPEG, PNG and TIFF.

## Performance notes

The grid runs on the full-size JPEG preview embedded in each RAW (~0.1s per photo)
rather than a full demosaic decode (~1s), so browsing thousands of photos stays fast.
Thumbnails generate lazily as you scroll and are cached to disk; decoded pixmaps are
held in a bounded LRU so memory doesn't grow with library size.

Cataloging runs about 0.17s per photo, so a 100–250 shot shoot takes 20–45 seconds.

## Tests

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```
