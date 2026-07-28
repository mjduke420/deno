import sqlite3

import pytest

from core.catalog import SCHEMA_VERSION, Catalog, PhotoFilter
from core.edit_state import EditState
from core.tone_pipeline import ToneSettings


@pytest.fixture
def catalog():
    with Catalog(":memory:") as cat:
        yield cat


@pytest.fixture
def folder_id(catalog):
    return catalog.add_folder("/library/shoot")


def _add_photo(catalog, folder_id, name="IMG_0001.CR3", **metadata):
    return catalog.upsert_photo(folder_id, f"/library/shoot/{name}", **metadata)


# ---------- schema / folders ----------


def test_schema_version_is_recorded(catalog):
    assert catalog.schema_version == SCHEMA_VERSION


def test_add_folder_is_idempotent(catalog):
    first = catalog.add_folder("/library/shoot")
    second = catalog.add_folder("/library/shoot")
    assert first == second
    assert len(catalog.list_folders()) == 1


def test_removing_a_folder_removes_its_photos(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    catalog.remove_folder(folder_id)

    assert catalog.list_folders() == []
    assert catalog.get_photo(photo_id) is None


# ---------- photos ----------


def test_upsert_stores_metadata(catalog, folder_id):
    photo_id = _add_photo(
        catalog,
        folder_id,
        captured_at="2026-01-15 09:30:00",
        camera_model="Canon EOS R8",
        lens_model="RF100-400mm F5.6-8 IS USM",
        iso=800.0,
        aperture=8.0,
        focal_length_mm=400.0,
        width=6000,
        height=4000,
    )
    photo = catalog.get_photo(photo_id)

    assert photo.filename == "IMG_0001.CR3"
    assert photo.camera_model == "Canon EOS R8"
    assert photo.iso == 800.0
    assert photo.width == 6000
    assert photo.rating == 0
    assert photo.flag == "none"
    assert photo.color_label is None
    assert photo.is_missing is False


def test_upsert_is_idempotent_on_path(catalog, folder_id):
    first = _add_photo(catalog, folder_id)
    second = _add_photo(catalog, folder_id)
    assert first == second
    assert catalog.count_photos() == 1


def test_rescan_refreshes_metadata_but_preserves_user_work(catalog, folder_id):
    """The single most important catalog guarantee: re-scanning a folder must never
    discard ratings, flags, labels or edits."""
    photo_id = _add_photo(catalog, folder_id, iso=800.0)
    catalog.set_rating(photo_id, 4)
    catalog.set_flag(photo_id, "pick")
    catalog.set_color_label(photo_id, "green")
    catalog.save_edits(photo_id, EditState(tone=ToneSettings(exposure=1.25)))

    _add_photo(catalog, folder_id, iso=1600.0)  # simulate a re-scan with updated EXIF

    photo = catalog.get_photo(photo_id)
    assert photo.iso == 1600.0  # metadata refreshed
    assert photo.rating == 4  # user work preserved
    assert photo.flag == "pick"
    assert photo.color_label == "green"
    assert photo.edits.tone.exposure == 1.25


def test_get_photo_by_path_and_missing_id(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    assert catalog.get_photo_by_path("/library/shoot/IMG_0001.CR3").id == photo_id
    assert catalog.get_photo(99999) is None


# ---------- ratings / flags / labels ----------


def test_set_rating_round_trips(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    catalog.set_rating(photo_id, 5)
    assert catalog.get_photo(photo_id).rating == 5


@pytest.mark.parametrize("bad_rating", [-1, 6, 100])
def test_invalid_rating_is_rejected(catalog, folder_id, bad_rating):
    photo_id = _add_photo(catalog, folder_id)
    with pytest.raises(ValueError):
        catalog.set_rating(photo_id, bad_rating)


def test_flag_and_color_label_round_trip(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    catalog.set_flag(photo_id, "reject")
    catalog.set_color_label(photo_id, "blue")

    photo = catalog.get_photo(photo_id)
    assert photo.flag == "reject"
    assert photo.color_label == "blue"


def test_color_label_can_be_cleared(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    catalog.set_color_label(photo_id, "red")
    catalog.set_color_label(photo_id, None)
    assert catalog.get_photo(photo_id).color_label is None


def test_invalid_flag_and_label_are_rejected(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    with pytest.raises(ValueError):
        catalog.set_flag(photo_id, "maybe")
    with pytest.raises(ValueError):
        catalog.set_color_label(photo_id, "chartreuse")


def test_rating_an_unknown_photo_raises(catalog):
    with pytest.raises(KeyError):
        catalog.set_rating(99999, 3)


# ---------- edits ----------


def test_edits_round_trip_through_the_catalog(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    state = EditState(tone=ToneSettings(exposure=2.0, contrast=15.0), denoise_enabled=True)

    catalog.save_edits(photo_id, state)

    assert catalog.load_edits(photo_id) == state
    assert catalog.get_photo(photo_id).has_edits


def test_unedited_photo_reports_default_edits(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    assert catalog.load_edits(photo_id) == EditState()
    assert not catalog.get_photo(photo_id).has_edits


# ---------- filtering ----------


def test_filter_by_minimum_rating(catalog, folder_id):
    for index, rating in enumerate([0, 2, 4, 5]):
        photo_id = _add_photo(catalog, folder_id, name=f"IMG_{index}.CR3")
        catalog.set_rating(photo_id, rating)

    keepers = catalog.query_photos(PhotoFilter(min_rating=4))
    assert sorted(p.rating for p in keepers) == [4, 5]


def test_filter_by_flag_and_color_label(catalog, folder_id):
    picked = _add_photo(catalog, folder_id, name="pick.CR3")
    rejected = _add_photo(catalog, folder_id, name="reject.CR3")
    catalog.set_flag(picked, "pick")
    catalog.set_flag(rejected, "reject")
    catalog.set_color_label(picked, "green")

    assert [p.id for p in catalog.query_photos(PhotoFilter(flag="pick"))] == [picked]
    assert [p.id for p in catalog.query_photos(PhotoFilter(color_label="green"))] == [picked]


def test_filter_by_folder_isolates_shoots(catalog):
    shoot_a = catalog.add_folder("/library/a")
    shoot_b = catalog.add_folder("/library/b")
    catalog.upsert_photo(shoot_a, "/library/a/one.CR3")
    catalog.upsert_photo(shoot_b, "/library/b/two.CR3")

    assert len(catalog.query_photos(PhotoFilter(folder_id=shoot_a))) == 1
    assert len(catalog.query_photos()) == 2


def test_missing_photos_can_be_excluded(catalog, folder_id):
    present = _add_photo(catalog, folder_id, name="here.CR3")
    gone = _add_photo(catalog, folder_id, name="gone.CR3")
    catalog.mark_missing(gone)

    visible = catalog.query_photos(PhotoFilter(include_missing=False))
    assert [p.id for p in visible] == [present]
    assert catalog.get_photo(gone).is_missing is True


def test_photos_sort_by_capture_time_with_undated_last(catalog, folder_id):
    _add_photo(catalog, folder_id, name="undated.CR3")
    _add_photo(catalog, folder_id, name="later.CR3", captured_at="2026-01-15 12:00:00")
    _add_photo(catalog, folder_id, name="earlier.CR3", captured_at="2026-01-15 09:00:00")

    order = [p.filename for p in catalog.query_photos()]
    assert order == ["earlier.CR3", "later.CR3", "undated.CR3"]


def test_bulk_rating_updates_every_photo(catalog, folder_id):
    ids = [_add_photo(catalog, folder_id, name=f"IMG_{i}.CR3") for i in range(4)]

    changed = catalog.set_rating_bulk(ids, 4)

    assert changed == 4
    assert all(catalog.get_photo(photo_id).rating == 4 for photo_id in ids)


def test_bulk_flag_and_label_updates(catalog, folder_id):
    ids = [_add_photo(catalog, folder_id, name=f"IMG_{i}.CR3") for i in range(3)]

    catalog.set_flag_bulk(ids, "pick")
    catalog.set_color_label_bulk(ids, "blue")

    assert all(catalog.get_photo(i).flag == "pick" for i in ids)
    assert all(catalog.get_photo(i).color_label == "blue" for i in ids)


def test_bulk_updates_validate_their_values(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    with pytest.raises(ValueError):
        catalog.set_rating_bulk([photo_id], 9)
    with pytest.raises(ValueError):
        catalog.set_flag_bulk([photo_id], "sideways")


def test_bulk_update_skips_unknown_ids_instead_of_raising(catalog, folder_id):
    """A bulk cull shouldn't abort because one photo left the catalog meanwhile."""
    real_id = _add_photo(catalog, folder_id)

    changed = catalog.set_rating_bulk([real_id, 99999], 3)

    assert changed == 1
    assert catalog.get_photo(real_id).rating == 3


def test_bulk_update_of_an_empty_selection_is_a_no_op(catalog):
    assert catalog.set_rating_bulk([], 5) == 0


def test_photo_paths_in_folder_lists_only_that_folders_photos(catalog):
    shoot_a = catalog.add_folder("/library/a")
    shoot_b = catalog.add_folder("/library/b")
    catalog.upsert_photo(shoot_a, "/library/a/one.CR3")
    catalog.upsert_photo(shoot_b, "/library/b/two.CR3")

    paths = catalog.photo_paths_in_folder(shoot_a)

    assert len(paths) == 1
    assert paths[0].endswith("one.CR3")


# ---------- directories / folder tree ----------


def _add_tree(catalog):
    """Mirrors the real library shape: a root with shoot folders, some nested by date."""
    root = catalog.add_folder(r"C:\RAW")
    paths = [
        r"C:\RAW\top.CR3",
        r"C:\RAW\macro\a.CR3",
        r"C:\RAW\macro\b.CR3",
        r"C:\RAW\2026 July\2026_07_20\x.CR3",
        r"C:\RAW\2026 July\2026_07_21\y.CR3",
    ]
    for path in paths:
        catalog.upsert_photo(root, path)
    return root


def test_directory_is_derived_from_the_photo_path(catalog, folder_id):
    photo_id = _add_photo(catalog, folder_id)
    assert catalog.get_photo(photo_id).directory.endswith("shoot")


def test_list_directories_returns_each_directory_once(catalog):
    _add_tree(catalog)
    directories = catalog.list_directories()

    assert directories == sorted(directories)
    assert r"C:\RAW" in directories
    assert r"C:\RAW\macro" in directories
    assert r"C:\RAW\2026 July\2026_07_20" in directories
    assert len(directories) == len(set(directories))


def test_filtering_by_directory_includes_subfolders_by_default(catalog):
    _add_tree(catalog)

    july = catalog.query_photos(PhotoFilter(directory=r"C:\RAW\2026 July"))

    assert sorted(p.filename for p in july) == ["x.CR3", "y.CR3"]


def test_filtering_by_directory_can_exclude_subfolders(catalog):
    _add_tree(catalog)

    just_root = catalog.query_photos(PhotoFilter(directory=r"C:\RAW", include_subfolders=False))

    assert [p.filename for p in just_root] == ["top.CR3"]


def test_filtering_by_root_directory_includes_everything_beneath(catalog):
    _add_tree(catalog)
    assert len(catalog.query_photos(PhotoFilter(directory=r"C:\RAW"))) == 5


def test_directory_filter_is_not_fooled_by_underscore_wildcards(catalog):
    """Real folders like '2026_07_20' would match '2026x07x20' if this used LIKE."""
    root = catalog.add_folder(r"C:\RAW")
    catalog.upsert_photo(root, r"C:\RAW\2026_07_20\real.CR3")
    catalog.upsert_photo(root, r"C:\RAW\2026x07x20\decoy.CR3")

    matched = catalog.query_photos(PhotoFilter(directory=r"C:\RAW\2026_07_20"))

    assert [p.filename for p in matched] == ["real.CR3"]


def test_directory_filter_does_not_match_sibling_prefixes(catalog):
    root = catalog.add_folder(r"C:\RAW")
    catalog.upsert_photo(root, r"C:\RAW\May\a.CR3")
    catalog.upsert_photo(root, r"C:\RAW\May Long Weekend\b.CR3")

    matched = catalog.query_photos(PhotoFilter(directory=r"C:\RAW\May"))

    assert [p.filename for p in matched] == ["a.CR3"]


def test_unknown_directory_yields_no_photos(catalog):
    _add_tree(catalog)
    assert catalog.query_photos(PhotoFilter(directory=r"C:\RAW\nope")) == []


def test_directory_filter_combines_with_rating(catalog):
    root = _add_tree(catalog)
    macro = [p for p in catalog.query_photos(PhotoFilter(directory=r"C:\RAW\macro"))]
    catalog.set_rating(macro[0].id, 5)

    keepers = catalog.query_photos(PhotoFilter(directory=r"C:\RAW\macro", min_rating=5))

    assert len(keepers) == 1


# ---------- migration ----------


def test_v1_catalog_is_migrated_without_losing_user_work(tmp_path):
    """A pre-existing catalog must gain the directory column and keep its ratings."""
    db_path = tmp_path / "old.db"
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """
        CREATE TABLE folders (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, added_at TEXT NOT NULL);
        CREATE TABLE photos (
            id INTEGER PRIMARY KEY,
            folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
            path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
            file_mtime REAL, file_size INTEGER, captured_at TEXT, camera_model TEXT,
            lens_model TEXT, iso REAL, aperture REAL, shutter_speed REAL,
            focal_length_mm REAL, width INTEGER, height INTEGER,
            rating INTEGER NOT NULL DEFAULT 0, flag TEXT NOT NULL DEFAULT 'none',
            color_label TEXT, edits_json TEXT, is_missing INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO folders (id, path, added_at) VALUES (1, 'C:\\RAW', '2026-01-01 00:00:00');
        INSERT INTO photos (id, folder_id, path, filename, rating, flag, color_label)
            VALUES (1, 1, 'C:\\RAW\\macro\\keep.CR3', 'keep.CR3', 5, 'pick', 'green');
        PRAGMA user_version = 1;
        """
    )
    legacy.commit()
    legacy.close()

    with Catalog(db_path) as migrated:
        assert migrated.schema_version == SCHEMA_VERSION

        photo = migrated.get_photo(1)
        assert photo.rating == 5  # user work preserved
        assert photo.flag == "pick"
        assert photo.color_label == "green"
        assert photo.directory == r"C:\RAW\macro"  # backfilled

        assert migrated.query_photos(PhotoFilter(directory=r"C:\RAW\macro"))


def test_migration_is_idempotent(tmp_path):
    db_path = tmp_path / "twice.db"
    with Catalog(db_path) as first:
        folder_id = first.add_folder(r"C:\RAW")
        first.upsert_photo(folder_id, r"C:\RAW\macro\a.CR3")
        first.set_rating(1, 4)

    with Catalog(db_path) as second:
        assert second.schema_version == SCHEMA_VERSION
        assert second.get_photo(1).rating == 4
        assert second.get_photo(1).directory == r"C:\RAW\macro"


def test_combined_filters_narrow_to_portfolio_picks(catalog, folder_id):
    for index in range(4):
        photo_id = _add_photo(catalog, folder_id, name=f"IMG_{index}.CR3")
        catalog.set_rating(photo_id, index + 2)  # 2,3,4,5
        if index >= 2:
            catalog.set_flag(photo_id, "pick")

    portfolio = catalog.query_photos(PhotoFilter(min_rating=5, flag="pick"))
    assert [p.rating for p in portfolio] == [5]
