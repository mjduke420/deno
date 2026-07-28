from pathlib import Path

import pytest
from PIL import Image

from core.catalog import Catalog
from core.scanner import (
    SUPPORTED_SUFFIXES,
    _parse_exif_datetime,
    find_photos,
    read_metadata,
    scan_folder,
)

SAMPLE_RAW = Path(__file__).parent.parent / "IMG_7346.CR3"


@pytest.fixture
def catalog():
    with Catalog(":memory:") as cat:
        yield cat


def _make_jpeg(path: Path, size=(64, 48)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (120, 90, 60)).save(path, format="JPEG")
    return path


# ---------- discovery ----------


def test_find_photos_picks_up_supported_formats_only(tmp_path):
    _make_jpeg(tmp_path / "keep.jpg")
    (tmp_path / "notes.txt").write_text("not a photo")
    (tmp_path / "sidecar.xmp").write_text("<xmp/>")

    found = [p.name for p in find_photos(tmp_path)]
    assert found == ["keep.jpg"]


def test_find_photos_recurses_into_subfolders(tmp_path):
    _make_jpeg(tmp_path / "a.jpg")
    _make_jpeg(tmp_path / "sub" / "b.jpg")
    _make_jpeg(tmp_path / "sub" / "deeper" / "c.jpg")

    assert sorted(p.name for p in find_photos(tmp_path)) == ["a.jpg", "b.jpg", "c.jpg"]


def test_find_photos_is_case_insensitive_on_extension(tmp_path):
    _make_jpeg(tmp_path / "shouty.JPG")
    assert [p.name for p in find_photos(tmp_path)] == ["shouty.JPG"]


def test_find_photos_on_a_nonexistent_folder_yields_nothing(tmp_path):
    assert list(find_photos(tmp_path / "nope")) == []


def test_common_raw_formats_are_supported():
    for suffix in (".cr3", ".cr2", ".orf", ".nef", ".arw", ".dng"):
        assert suffix in SUPPORTED_SUFFIXES


# ---------- metadata ----------


def test_read_metadata_of_a_plain_image(tmp_path):
    photo = _make_jpeg(tmp_path / "plain.jpg", size=(120, 80))
    metadata = read_metadata(photo)

    assert metadata.filename == "plain.jpg"
    assert metadata.width == 120
    assert metadata.height == 80
    assert metadata.file_size > 0
    assert metadata.file_mtime is not None


@pytest.mark.skipif(not SAMPLE_RAW.exists(), reason="sample CR3 not present")
def test_read_metadata_of_a_real_raw_file():
    metadata = read_metadata(SAMPLE_RAW)

    assert metadata.filename == "IMG_7346.CR3"
    assert metadata.camera_model == "Canon EOS R8"
    assert metadata.lens_model == "RF100-400mm F5.6-8 IS USM"
    assert metadata.iso == 10000.0
    assert metadata.aperture == 8.0
    assert metadata.focal_length_mm == 400.0
    assert metadata.width and metadata.height
    assert metadata.captured_at and metadata.captured_at.startswith("20")


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("2026:01:15 09:30:00", "2026-01-15 09:30:00"),
        ("  2026:01:15 09:30:00  ", "2026-01-15 09:30:00"),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_exif_datetime_is_normalized_to_iso(raw_value, expected):
    assert _parse_exif_datetime(raw_value) == expected


# ---------- scanning ----------


def test_scan_folder_catalogs_every_photo(tmp_path, catalog):
    _make_jpeg(tmp_path / "one.jpg")
    _make_jpeg(tmp_path / "two.jpg")
    _make_jpeg(tmp_path / "sub" / "three.jpg")

    result = scan_folder(catalog, tmp_path)

    assert result.added == 3
    assert result.failed == 0
    assert catalog.count_photos() == 3


def test_scan_folder_reports_progress_to_completion(tmp_path, catalog):
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        _make_jpeg(tmp_path / name)
    seen = []

    scan_folder(catalog, tmp_path, progress_cb=lambda done, total: seen.append((done, total)))

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_scan_folder_can_be_cancelled_midway(tmp_path, catalog):
    for index in range(5):
        _make_jpeg(tmp_path / f"{index}.jpg")

    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 2

    result = scan_folder(catalog, tmp_path, should_cancel=should_cancel)

    assert result.cancelled is True
    assert result.added < 5


def test_unreadable_file_is_counted_but_does_not_abort_the_scan(tmp_path, catalog):
    _make_jpeg(tmp_path / "good.jpg")
    (tmp_path / "corrupt.jpg").write_bytes(b"this is not a JPEG")

    result = scan_folder(catalog, tmp_path)

    assert result.added == 1
    assert result.failed == 1
    assert result.total == 2


def test_rescanning_does_not_duplicate_photos(tmp_path, catalog):
    _make_jpeg(tmp_path / "one.jpg")

    scan_folder(catalog, tmp_path)
    scan_folder(catalog, tmp_path)

    assert catalog.count_photos() == 1
    assert len(catalog.list_folders()) == 1


def test_rescanning_preserves_ratings(tmp_path, catalog):
    _make_jpeg(tmp_path / "keeper.jpg")
    scan_folder(catalog, tmp_path)
    photo = catalog.query_photos()[0]
    catalog.set_rating(photo.id, 5)
    catalog.set_flag(photo.id, "pick")

    scan_folder(catalog, tmp_path)

    refreshed = catalog.get_photo(photo.id)
    assert refreshed.rating == 5
    assert refreshed.flag == "pick"


def test_scan_registers_the_folder(tmp_path, catalog):
    _make_jpeg(tmp_path / "one.jpg")
    scan_folder(catalog, tmp_path)

    folders = catalog.list_folders()
    assert len(folders) == 1
    assert Path(folders[0].path) == tmp_path.resolve()
