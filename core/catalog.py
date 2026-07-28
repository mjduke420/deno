"""SQLite catalog of the photo library: folders, photos, ratings and per-photo edits.

Reference-in-place and non-destructive: the catalog only ever stores paths and
metadata, never copies or modifies the original RAW files.

Connections are shared across threads (the folder scanner and batch exporter run on
background QThreads while the UI reads), so access is serialized behind a lock and
SQLite runs in WAL mode.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from core.edit_state import EditState

SCHEMA_VERSION = 2

MIN_RATING = 0
MAX_RATING = 5
FLAGS = ("none", "pick", "reject")
COLOR_LABELS = ("red", "yellow", "green", "blue", "purple")

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Columns describing the file on disk. A re-scan refreshes these but must never
# touch rating/flag/color_label/edits_json — those are the user's own work.
_SCANNABLE_COLUMNS = (
    "filename",
    "file_mtime",
    "file_size",
    "captured_at",
    "camera_model",
    "lens_model",
    "iso",
    "aperture",
    "shutter_speed",
    "focal_length_mm",
    "width",
    "height",
)


def default_catalog_dir() -> Path:
    """Per-user app data dir, so ratings survive moving or re-cloning the code."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "RawDenoise"


def format_timestamp(moment: datetime) -> str:
    return moment.strftime(_TIMESTAMP_FORMAT)


@dataclass(frozen=True)
class Folder:
    id: int
    path: str
    added_at: str


@dataclass(frozen=True)
class Photo:
    id: int
    folder_id: int
    path: str
    filename: str
    rating: int
    flag: str
    color_label: str | None
    is_missing: bool
    directory: str | None = None
    file_mtime: float | None = None
    file_size: int | None = None
    captured_at: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    iso: float | None = None
    aperture: float | None = None
    shutter_speed: float | None = None
    focal_length_mm: float | None = None
    width: int | None = None
    height: int | None = None
    edits_json: str | None = None

    @property
    def edits(self) -> EditState:
        return EditState.from_json(self.edits_json)

    @property
    def has_edits(self) -> bool:
        return not self.edits.is_default()


@dataclass(frozen=True)
class Preset:
    id: int
    name: str
    edits_json: str
    created_at: str

    @property
    def edits(self) -> EditState:
        return EditState.from_json(self.edits_json)


@dataclass(frozen=True)
class PhotoFilter:
    folder_id: int | None = None
    directory: str | None = None  # narrow to one directory within a catalogued folder
    include_subfolders: bool = True  # ...and everything nested beneath it
    min_rating: int = MIN_RATING
    flag: str | None = None
    color_label: str | None = None
    include_missing: bool = True


class Catalog:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ---------- schema ----------

    def _create_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS folders (
                    id       INTEGER PRIMARY KEY,
                    path     TEXT NOT NULL UNIQUE,
                    added_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS photos (
                    id              INTEGER PRIMARY KEY,
                    folder_id       INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
                    path            TEXT NOT NULL UNIQUE,
                    directory       TEXT,
                    filename        TEXT NOT NULL,
                    file_mtime      REAL,
                    file_size       INTEGER,
                    captured_at     TEXT,
                    camera_model    TEXT,
                    lens_model      TEXT,
                    iso             REAL,
                    aperture        REAL,
                    shutter_speed   REAL,
                    focal_length_mm REAL,
                    width           INTEGER,
                    height          INTEGER,
                    rating          INTEGER NOT NULL DEFAULT 0,
                    flag            TEXT NOT NULL DEFAULT 'none',
                    color_label     TEXT,
                    edits_json      TEXT,
                    is_missing      INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS presets (
                    id         INTEGER PRIMARY KEY,
                    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    edits_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos(folder_id);
                CREATE INDEX IF NOT EXISTS idx_photos_rating ON photos(rating);
                """
            )
        # Indexes on newer columns are created by _migrate, which runs after the
        # column itself is guaranteed to exist — on an existing catalog the CREATE
        # TABLE above is a no-op and would not have added it.
        self._migrate()

    def _migrate(self) -> None:
        """Bring an existing catalog up to the current schema without losing user work."""
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version >= SCHEMA_VERSION:
                with self._conn:
                    self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                return

            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(photos)")}
            with self._conn:
                if "directory" not in columns:
                    self._conn.execute("ALTER TABLE photos ADD COLUMN directory TEXT")
                    self._conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_directory ON photos(directory)")

                # Backfill in Python: deriving a parent path is not something SQLite
                # can do portably, and this only runs once per catalog.
                rows = self._conn.execute(
                    "SELECT id, path FROM photos WHERE directory IS NULL"
                ).fetchall()
                if rows:
                    self._conn.executemany(
                        "UPDATE photos SET directory = ? WHERE id = ?",
                        [(str(Path(row["path"]).parent), row["id"]) for row in rows],
                    )
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @property
    def schema_version(self) -> int:
        with self._lock:
            return self._conn.execute("PRAGMA user_version").fetchone()[0]

    # ---------- folders ----------

    def add_folder(self, path: str | Path) -> int:
        """Register a folder. Re-adding an existing folder returns its existing id."""
        resolved = str(Path(path).resolve())
        added_at = format_timestamp(datetime.now(timezone.utc))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO folders (path, added_at) VALUES (?, ?) ON CONFLICT(path) DO NOTHING",
                (resolved, added_at),
            )
            row = self._conn.execute("SELECT id FROM folders WHERE path = ?", (resolved,)).fetchone()
        return int(row["id"])

    def list_folders(self) -> list[Folder]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM folders ORDER BY path").fetchall()
        return [Folder(id=r["id"], path=r["path"], added_at=r["added_at"]) for r in rows]

    def remove_folder(self, folder_id: int) -> None:
        """Removes the folder and its photos from the catalog. Files on disk are untouched."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))

    # ---------- photos ----------

    def upsert_photo(self, folder_id: int, path: str | Path, **metadata) -> int:
        """Insert a photo, or refresh the file/EXIF columns of one already cataloged.

        Ratings, flags, labels and edits are deliberately preserved on conflict — a
        re-scan must never discard the user's own work.
        """
        resolved = str(Path(path).resolve())
        values = {key: metadata.get(key) for key in _SCANNABLE_COLUMNS}
        values["filename"] = values["filename"] or Path(resolved).name
        # Derived here rather than supplied by callers, so it can never disagree with `path`.
        directory = str(Path(resolved).parent)

        columns = ", ".join(_SCANNABLE_COLUMNS)
        placeholders = ", ".join("?" for _ in _SCANNABLE_COLUMNS)
        updates = ", ".join(f"{col} = excluded.{col}" for col in _SCANNABLE_COLUMNS)

        with self._lock, self._conn:
            self._conn.execute(
                f"""
                INSERT INTO photos (folder_id, path, directory, {columns}, is_missing)
                VALUES (?, ?, ?, {placeholders}, 0)
                ON CONFLICT(path) DO UPDATE SET
                    {updates}, directory = excluded.directory,
                    folder_id = excluded.folder_id, is_missing = 0
                """,
                (folder_id, resolved, directory, *(values[col] for col in _SCANNABLE_COLUMNS)),
            )
            row = self._conn.execute("SELECT id FROM photos WHERE path = ?", (resolved,)).fetchone()
        return int(row["id"])

    def get_photo(self, photo_id: int) -> Photo | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        return _to_photo(row) if row else None

    def get_photo_by_path(self, path: str | Path) -> Photo | None:
        resolved = str(Path(path).resolve())
        with self._lock:
            row = self._conn.execute("SELECT * FROM photos WHERE path = ?", (resolved,)).fetchone()
        return _to_photo(row) if row else None

    def query_photos(self, photo_filter: PhotoFilter | None = None) -> list[Photo]:
        photo_filter = photo_filter or PhotoFilter()
        clauses: list[str] = []
        params: list[object] = []

        if photo_filter.folder_id is not None:
            clauses.append("folder_id = ?")
            params.append(photo_filter.folder_id)
        if photo_filter.directory is not None:
            # Matched against an explicit set of known directories rather than a LIKE
            # prefix: real folder names are full of '_' and could contain '%', both of
            # which are LIKE wildcards (e.g. "2026_07_20" would match "2026x07x20").
            wanted = self._directories_under(photo_filter.directory, photo_filter.include_subfolders)
            if not wanted:
                return []
            clauses.append(f"directory IN ({', '.join('?' for _ in wanted)})")
            params.extend(wanted)
        if photo_filter.min_rating > MIN_RATING:
            clauses.append("rating >= ?")
            params.append(photo_filter.min_rating)
        if photo_filter.flag is not None:
            _validate_flag(photo_filter.flag)
            clauses.append("flag = ?")
            params.append(photo_filter.flag)
        if photo_filter.color_label is not None:
            _validate_color_label(photo_filter.color_label)
            clauses.append("color_label = ?")
            params.append(photo_filter.color_label)
        if not photo_filter.include_missing:
            clauses.append("is_missing = 0")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM photos {where} ORDER BY captured_at IS NULL, captured_at, filename",
                params,
            ).fetchall()
        return [_to_photo(row) for row in rows]

    def count_photos(self, photo_filter: PhotoFilter | None = None) -> int:
        return len(self.query_photos(photo_filter))

    def list_directories(self, folder_id: int | None = None) -> list[str]:
        """Every directory that actually contains photos, for building the folder tree."""
        sql = "SELECT DISTINCT directory FROM photos WHERE directory IS NOT NULL"
        params: list[object] = []
        if folder_id is not None:
            sql += " AND folder_id = ?"
            params.append(folder_id)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY directory", params).fetchall()
        return [row["directory"] for row in rows]

    def _directories_under(self, directory: str, include_subfolders: bool) -> list[str]:
        candidates = self.list_directories()
        if not include_subfolders:
            return [d for d in candidates if d == directory]
        prefix = directory.rstrip("\\/") + os.sep
        return [d for d in candidates if d == directory or d.startswith(prefix)]

    # ---------- ratings / flags / labels ----------

    def set_rating(self, photo_id: int, rating: int) -> None:
        if not MIN_RATING <= rating <= MAX_RATING:
            raise ValueError(f"rating must be {MIN_RATING}..{MAX_RATING}, got {rating}")
        self._update_photo(photo_id, "rating", rating)

    def set_flag(self, photo_id: int, flag: str) -> None:
        _validate_flag(flag)
        self._update_photo(photo_id, "flag", flag)

    def set_color_label(self, photo_id: int, color_label: str | None) -> None:
        if color_label is not None:
            _validate_color_label(color_label)
        self._update_photo(photo_id, "color_label", color_label)

    def mark_missing(self, photo_id: int, missing: bool = True) -> None:
        self._update_photo(photo_id, "is_missing", 1 if missing else 0)

    # Bulk variants: culling a large selection would otherwise mean one committed
    # transaction (and one fsync) per photo, which stalls the UI at library scale.

    def set_rating_bulk(self, photo_ids: Iterable[int], rating: int) -> int:
        if not MIN_RATING <= rating <= MAX_RATING:
            raise ValueError(f"rating must be {MIN_RATING}..{MAX_RATING}, got {rating}")
        return self._update_photos(photo_ids, "rating", rating)

    def set_flag_bulk(self, photo_ids: Iterable[int], flag: str) -> int:
        _validate_flag(flag)
        return self._update_photos(photo_ids, "flag", flag)

    def set_color_label_bulk(self, photo_ids: Iterable[int], color_label: str | None) -> int:
        if color_label is not None:
            _validate_color_label(color_label)
        return self._update_photos(photo_ids, "color_label", color_label)

    def photo_paths_in_folder(self, folder_id: int) -> list[str]:
        """Used to evict cached thumbnails when a folder leaves the catalog."""
        with self._lock:
            rows = self._conn.execute("SELECT path FROM photos WHERE folder_id = ?", (folder_id,)).fetchall()
        return [row["path"] for row in rows]

    # ---------- edits ----------

    def save_edits(self, photo_id: int, edits: EditState) -> None:
        self._update_photo(photo_id, "edits_json", edits.to_json())

    def load_edits(self, photo_id: int) -> EditState:
        photo = self.get_photo(photo_id)
        return photo.edits if photo else EditState()

    # ---------- presets ----------

    def save_preset(self, name: str, edits: EditState) -> int:
        """Store a named set of adjustments. Saving over an existing name replaces it,
        which is what 'save' means when the name already appears in the list."""
        name = name.strip()
        if not name:
            raise ValueError("preset name cannot be empty")
        created_at = format_timestamp(datetime.now(timezone.utc))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO presets (name, edits_json, created_at) VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET edits_json = excluded.edits_json
                """,
                (name, edits.to_json(), created_at),
            )
            row = self._conn.execute("SELECT id FROM presets WHERE name = ?", (name,)).fetchone()
        return int(row["id"])

    def list_presets(self) -> list[Preset]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM presets ORDER BY name COLLATE NOCASE").fetchall()
        return [_to_preset(row) for row in rows]

    def get_preset(self, preset_id: int) -> Preset | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
        return _to_preset(row) if row else None

    def get_preset_by_name(self, name: str) -> Preset | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM presets WHERE name = ?", (name.strip(),)).fetchone()
        return _to_preset(row) if row else None

    def delete_preset(self, preset_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))

    # ---------- internals ----------

    def _update_photo(self, photo_id: int, column: str, value) -> None:
        with self._lock, self._conn:
            cursor = self._conn.execute(f"UPDATE photos SET {column} = ? WHERE id = ?", (value, photo_id))
        if cursor.rowcount == 0:
            raise KeyError(f"no photo with id {photo_id}")

    def _update_photos(self, photo_ids: Iterable[int], column: str, value) -> int:
        """Set one column on many photos in a single transaction. Unknown ids are
        skipped rather than raising — a bulk cull shouldn't abort because one photo
        was removed from the catalog meanwhile. Returns the number of rows changed."""
        rows = [(value, photo_id) for photo_id in photo_ids]
        if not rows:
            return 0
        with self._lock, self._conn:
            cursor = self._conn.executemany(f"UPDATE photos SET {column} = ? WHERE id = ?", rows)
        return cursor.rowcount


def _validate_flag(flag: str) -> None:
    if flag not in FLAGS:
        raise ValueError(f"flag must be one of {FLAGS}, got {flag!r}")


def _validate_color_label(color_label: str) -> None:
    if color_label not in COLOR_LABELS:
        raise ValueError(f"color_label must be one of {COLOR_LABELS} or None, got {color_label!r}")


def _to_preset(row: sqlite3.Row) -> Preset:
    return Preset(
        id=row["id"],
        name=row["name"],
        edits_json=row["edits_json"],
        created_at=row["created_at"],
    )


def _to_photo(row: sqlite3.Row) -> Photo:
    return Photo(
        id=row["id"],
        folder_id=row["folder_id"],
        path=row["path"],
        filename=row["filename"],
        rating=row["rating"],
        flag=row["flag"],
        color_label=row["color_label"],
        is_missing=bool(row["is_missing"]),
        directory=row["directory"],
        file_mtime=row["file_mtime"],
        file_size=row["file_size"],
        captured_at=row["captured_at"],
        camera_model=row["camera_model"],
        lens_model=row["lens_model"],
        iso=row["iso"],
        aperture=row["aperture"],
        shutter_speed=row["shutter_speed"],
        focal_length_mm=row["focal_length_mm"],
        width=row["width"],
        height=row["height"],
        edits_json=row["edits_json"],
    )
