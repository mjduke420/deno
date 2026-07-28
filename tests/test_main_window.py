"""End-to-end wiring: catalog <-> library grid <-> develop module.

The headline guarantee under test is that adjustments are never silently lost —
not when switching photos, not when leaving the Develop module, not on restart.
"""
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from core.edit_state import EditState
from core.scanner import scan_folder
from core.tone_pipeline import ToneSettings
from ui.main_window import DEVELOP_PAGE, LIBRARY_PAGE, MainWindow


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shoot(tmp_path):
    """A folder of small synthetic photos standing in for a real shoot."""
    folder = tmp_path / "shoot"
    folder.mkdir()
    for index, color in enumerate([(200, 60, 60), (60, 200, 60), (60, 60, 200)]):
        Image.new("RGB", (48, 32), color).save(folder / f"IMG_{index}.jpg")
    return folder


def _shutdown(window: MainWindow) -> None:
    window.catalog.close()
    window.thumbnail_loader.stop()
    window.thumbnail_loader.wait(2000)


@pytest.fixture
def window(qt_app, tmp_path, shoot):
    win = MainWindow(catalog_dir=tmp_path / "catalog_data")
    # Scan synchronously so tests don't depend on worker-thread timing.
    scan_folder(win.catalog, shoot)
    win.refresh_folders()
    win.refresh_photos()
    yield win
    _shutdown(win)


def test_library_starts_populated_from_the_catalog(window):
    assert window.grid_model.rowCount() == 3
    assert window.pages.currentIndex() == LIBRARY_PAGE


def test_opening_a_photo_switches_to_develop(window):
    photo = window.grid_model.photo_at(0)

    window.open_in_develop(photo)

    assert window.pages.currentIndex() == DEVELOP_PAGE
    assert window.develop_view.has_photo()
    assert window.develop_view.current_path == photo.path


def test_edits_are_persisted_to_the_catalog(window):
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)

    window.develop_view._on_tone_settings_changed(ToneSettings(exposure=1.5))
    window.flush_pending_edits()

    assert window.catalog.load_edits(photo.id).tone.exposure == 1.5


def test_switching_photos_flushes_the_previous_photos_edits(window):
    first = window.grid_model.photo_at(0)
    second = window.grid_model.photo_at(1)

    window.open_in_develop(first)
    window.develop_view._on_tone_settings_changed(ToneSettings(exposure=2.0))
    # Deliberately do NOT flush — switching photos must do it for us.
    window.open_in_develop(second)

    assert window.catalog.load_edits(first.id).tone.exposure == 2.0


def test_switching_photos_loads_the_new_photos_own_edits(window):
    first = window.grid_model.photo_at(0)
    second = window.grid_model.photo_at(1)
    window.catalog.save_edits(second.id, EditState(tone=ToneSettings(exposure=-1.0, contrast=25.0)))

    window.open_in_develop(first)
    window.develop_view._on_tone_settings_changed(ToneSettings(exposure=2.0))
    window.open_in_develop(second)

    loaded = window.develop_view.edit_state()
    assert loaded.tone.exposure == -1.0
    assert loaded.tone.contrast == 25.0
    assert window.develop_view.exposure_panel.settings().exposure == -1.0


def test_returning_to_library_flushes_edits(window):
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)
    window.develop_view._on_tone_settings_changed(ToneSettings(shadows=45.0))

    window.show_library()

    assert window.catalog.load_edits(photo.id).tone.shadows == 45.0
    assert window.pages.currentIndex() == LIBRARY_PAGE


def test_edits_survive_a_restart(qt_app, tmp_path, shoot):
    catalog_dir = tmp_path / "catalog_data"

    first_session = MainWindow(catalog_dir=catalog_dir)
    scan_folder(first_session.catalog, shoot)
    first_session.refresh_photos()
    photo = first_session.grid_model.photo_at(0)
    first_session.open_in_develop(photo)
    first_session.develop_view._on_tone_settings_changed(ToneSettings(exposure=1.25))
    first_session.flush_pending_edits()
    _shutdown(first_session)

    second_session = MainWindow(catalog_dir=catalog_dir)
    try:
        reopened = second_session.catalog.get_photo_by_path(photo.path)
        assert reopened is not None
        assert second_session.catalog.load_edits(reopened.id).tone.exposure == 1.25
        assert reopened.has_edits
    finally:
        _shutdown(second_session)


# ---------- ratings ----------


def test_rating_a_selection_persists_and_updates_the_grid(window):
    photos = [window.grid_model.photo_at(0), window.grid_model.photo_at(1)]

    window._on_rating_requested(photos, 4)

    assert all(window.catalog.get_photo(p.id).rating == 4 for p in photos)
    assert window.grid_model.photo_at(0).rating == 4  # grid refreshed in place


def test_flagging_and_labelling_persist(window):
    photo = window.grid_model.photo_at(0)

    window._on_flag_requested([photo], "pick")
    window._on_color_label_requested([photo], "green")

    stored = window.catalog.get_photo(photo.id)
    assert stored.flag == "pick"
    assert stored.color_label == "green"


def test_filtering_by_rating_narrows_the_grid(window):
    keeper = window.grid_model.photo_at(0)
    window._on_rating_requested([keeper], 5)

    window.filter_panel.rating_combo.setCurrentIndex(5)  # "★ 5"
    window.refresh_photos()

    assert window.grid_model.rowCount() == 1
    assert window.grid_model.photo_at(0).id == keeper.id


def test_filtering_by_pick_flag_narrows_the_grid(window):
    keeper = window.grid_model.photo_at(1)
    window._on_flag_requested([keeper], "pick")

    window.filter_panel.flag_combo.setCurrentIndex(1)  # "Picked"
    window.refresh_photos()

    assert window.grid_model.rowCount() == 1
    assert window.grid_model.photo_at(0).id == keeper.id


def test_ratings_survive_a_rescan(window, shoot):
    photo = window.grid_model.photo_at(0)
    window._on_rating_requested([photo], 3)

    scan_folder(window.catalog, shoot)

    assert window.catalog.get_photo(photo.id).rating == 3


# ---------- regressions ----------


def test_opening_a_single_file_directly_lands_in_develop(window, tmp_path):
    """`main.py photo.CR3` must actually open the photo.

    Regression: this routed through the (now asynchronous) folder scan, which returns
    before the photo exists in the catalog, so the lookup found nothing and nothing
    opened. The file therefore has to live in a folder the catalog has NOT seen —
    using an already-scanned photo would pass even with the bug present.
    """
    fresh_folder = tmp_path / "unscanned"
    fresh_folder.mkdir()
    target = fresh_folder / "IMG_NEW.jpg"
    Image.new("RGB", (40, 30), (10, 90, 160)).save(target, format="JPEG")
    assert window.catalog.get_photo_by_path(target) is None  # genuinely uncatalogued

    window.load_raw_file(str(target))

    assert window.pages.currentIndex() == DEVELOP_PAGE
    assert window.develop_view.has_photo()
    assert Path(window.develop_view.current_path) == target
    assert window.catalog.get_photo_by_path(target) is not None  # and now catalogued


def test_opening_a_missing_file_directly_is_reported_not_crashed(window, tmp_path, monkeypatch):
    warned = []
    monkeypatch.setattr("ui.main_window.QMessageBox.warning", lambda *a, **k: warned.append(a))

    window.load_raw_file(str(tmp_path / "not_here.CR3"))

    assert warned
    assert not window.develop_view.has_photo()


def test_removing_a_folder_while_its_photo_is_open_does_not_crash(window, monkeypatch):
    """Regression: the Develop module kept a reference to a photo whose catalog row had
    been cascade-deleted, so the next edit flush raised KeyError out of a timer slot."""
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)

    window._on_remove_folder(window.catalog.list_folders()[0].id)

    # Previously raised KeyError("no photo with id ...").
    window.develop_view._on_tone_settings_changed(ToneSettings(exposure=1.0))
    window.flush_pending_edits()

    assert window.catalog.count_photos() == 0
    assert window.grid_model.rowCount() == 0


def test_removing_a_folder_evicts_its_cached_thumbnails(window, monkeypatch):
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    photo = window.grid_model.photo_at(0)
    assert window.thumbnail_cache.get(photo.path) is not None
    assert window.thumbnail_cache.is_cached(photo.path)

    window._on_remove_folder(window.catalog.list_folders()[0].id)

    assert not window.thumbnail_cache.is_cached(photo.path)


def test_bulk_rating_applies_to_the_whole_selection(window):
    photos = [window.grid_model.photo_at(i) for i in range(3)]

    window._on_rating_requested(photos, 5)

    assert all(window.catalog.get_photo(p.id).rating == 5 for p in photos)
    assert all(window.grid_model.photo_at(i).rating == 5 for i in range(3))


def test_rating_an_empty_selection_is_harmless(window):
    window._on_rating_requested([], 5)  # must not raise
    assert window.grid_model.rowCount() == 3


def test_returning_to_the_library_keeps_the_edited_photo_selected(window):
    """Coming back from Develop should land on the photo you were working on,
    not the top of the grid."""
    photo = window.grid_model.photo_at(2)
    window.open_in_develop(photo)

    window.show_library()

    assert window.pages.currentIndex() == LIBRARY_PAGE
    assert window.library_view.current_photo().id == photo.id


def test_selection_is_skipped_when_the_photo_is_filtered_out(window):
    """Selecting must not crash or pick the wrong photo when the edited one no
    longer matches the active filter."""
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)
    window.filter_panel.rating_combo.setCurrentIndex(5)  # 5 stars; nothing qualifies

    window.show_library()

    assert window.grid_model.rowCount() == 0
    assert window.library_view.current_photo() is None


def test_denoise_amount_persists_per_photo(window):
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)

    window.develop_view._on_denoise_amount_changed(0.25)
    window.flush_pending_edits()

    assert window.catalog.load_edits(photo.id).denoise_amount == 0.25


def test_denoise_amount_is_restored_into_the_panel(window):
    photo = window.grid_model.photo_at(0)
    window.catalog.save_edits(photo.id, EditState(denoise_amount=0.5))

    window.open_in_develop(photo)

    assert window.develop_view.denoise_panel.amount() == 0.5


def test_histogram_updates_when_a_photo_is_opened(window):
    photo = window.grid_model.photo_at(0)

    window.open_in_develop(photo)

    assert window.develop_view.histogram._histogram is not None


# ---------- presets ----------


def test_saving_a_preset_captures_the_current_adjustments(window):
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)
    window.develop_view._on_tone_settings_changed(ToneSettings(contrast=40.0, clarity=25.0))

    window._on_preset_save("Punchy")

    stored = window.catalog.get_preset_by_name("Punchy")
    assert stored is not None
    assert stored.edits.tone.contrast == 40.0
    assert stored.edits.tone.clarity == 25.0


def test_applying_a_preset_changes_the_photo(window):
    first = window.grid_model.photo_at(0)
    second = window.grid_model.photo_at(1)

    window.open_in_develop(first)
    window.develop_view._on_tone_settings_changed(ToneSettings(contrast=40.0))
    window._on_preset_save("Punchy")
    preset_id = window.catalog.get_preset_by_name("Punchy").id

    window.open_in_develop(second)
    assert window.develop_view.edit_state().tone.contrast == 0.0

    window._on_preset_apply(preset_id)

    assert window.develop_view.edit_state().tone.contrast == 40.0
    assert window.develop_view.exposure_panel.settings().contrast == 40.0


def test_applying_a_preset_persists_to_the_photo(window):
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)
    window.develop_view._on_tone_settings_changed(ToneSettings(vibrance=35.0))
    window._on_preset_save("Vivid")
    preset_id = window.catalog.get_preset_by_name("Vivid").id

    other = window.grid_model.photo_at(1)
    window.open_in_develop(other)
    window._on_preset_apply(preset_id)

    assert window.catalog.load_edits(other.id).tone.vibrance == 35.0


def test_presets_appear_in_the_panel(window):
    window.open_in_develop(window.grid_model.photo_at(0))
    window._on_preset_save("One")
    window._on_preset_save("Two")

    combo = window.develop_view.preset_panel.preset_combo
    names = [combo.itemText(i) for i in range(combo.count())]
    assert "One" in names and "Two" in names


def test_deleting_a_preset_removes_it_from_the_panel(window):
    window.open_in_develop(window.grid_model.photo_at(0))
    window._on_preset_save("Doomed")
    preset_id = window.catalog.get_preset_by_name("Doomed").id

    window._on_preset_delete(preset_id)

    assert window.catalog.get_preset(preset_id) is None
    combo = window.develop_view.preset_panel.preset_combo
    assert "Doomed" not in [combo.itemText(i) for i in range(combo.count())]


def test_applying_a_deleted_preset_is_handled(window):
    """The list can go stale; applying a vanished preset must not crash."""
    window.open_in_develop(window.grid_model.photo_at(0))
    window._on_preset_save("Ghost")
    preset_id = window.catalog.get_preset_by_name("Ghost").id
    window.catalog.delete_preset(preset_id)

    window._on_preset_apply(preset_id)  # must not raise


def test_saved_presets_do_not_capture_denoise(window):
    """Denoise is per-photo — it costs a GPU pass and depends on that frame's ISO."""
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)
    window.develop_view._on_denoise_amount_changed(0.25)
    window.develop_view.pipeline.denoise_enabled = True

    window._on_preset_save("Look Only")

    stored = window.catalog.get_preset_by_name("Look Only").edits
    assert stored.denoise_enabled is False


def test_applying_a_preset_leaves_the_photos_own_denoise_alone(window):
    first = window.grid_model.photo_at(0)
    window.open_in_develop(first)
    window.develop_view._on_tone_settings_changed(ToneSettings(contrast=40.0))
    window._on_preset_save("Punchy Look")
    preset_id = window.catalog.get_preset_by_name("Punchy Look").id

    second = window.grid_model.photo_at(1)
    window.open_in_develop(second)
    window.develop_view._on_denoise_amount_changed(0.25)

    window._on_preset_apply(preset_id)

    state = window.develop_view.edit_state()
    assert state.tone.contrast == 40.0  # the preset's look arrived
    assert state.denoise_amount == 0.25  # the photo's denoise survived


def test_skittles_is_available_out_of_the_box(window):
    preset = window.catalog.get_preset_by_name("Skittles")

    assert preset is not None
    assert preset.edits.tone.temperature == 5850.0
    assert preset.edits.tone.tint == -8.0


def test_applying_skittles_sets_the_white_balance_sliders(window):
    photo = window.grid_model.photo_at(0)
    window.open_in_develop(photo)
    preset_id = window.catalog.get_preset_by_name("Skittles").id

    window._on_preset_apply(preset_id)

    settings = window.develop_view.exposure_panel.settings()
    assert settings.temperature == 5850.0
    assert settings.tint == -8.0
    assert settings.shadows == 74.0
    assert settings.saturation == -5.0


def test_saving_a_preset_without_a_photo_is_refused(window):
    window._on_preset_save("Nothing")
    assert window.catalog.get_preset_by_name("Nothing") is None


# ---------- module tabs ----------


def test_module_tabs_follow_the_active_module(window):
    photo = window.grid_model.photo_at(0)

    window.open_in_develop(photo)
    assert window.module_tabs._buttons[DEVELOP_PAGE].isChecked()

    window.show_library()
    assert window.module_tabs._buttons[LIBRARY_PAGE].isChecked()


def test_clicking_the_develop_tab_switches_module(window):
    photo = window.grid_model.photo_at(0)
    window.library_view.setCurrentIndex(window.grid_model.index(0, 0))

    window.module_tabs._buttons[DEVELOP_PAGE].click()

    assert window.pages.currentIndex() == DEVELOP_PAGE
    assert window.develop_view.current_path == photo.path


def test_develop_tab_without_a_selection_stays_on_library(window):
    window.library_view.clearSelection()
    window.library_view.setCurrentIndex(window.grid_model.index(-1, -1))

    window.module_tabs._buttons[DEVELOP_PAGE].click()

    assert window.pages.currentIndex() == LIBRARY_PAGE
    assert window.module_tabs._buttons[LIBRARY_PAGE].isChecked()


# ---------- folder tree ----------


@pytest.fixture
def nested_shoot(tmp_path):
    """A root with photos plus nested date subfolders, mirroring the real library."""
    root = tmp_path / "RAW"
    (root / "macro").mkdir(parents=True)
    (root / "2026 July" / "2026_07_20").mkdir(parents=True)
    (root / "2026 July" / "2026_07_21").mkdir(parents=True)
    for path in [
        root / "top.jpg",
        root / "macro" / "a.jpg",
        root / "2026 July" / "2026_07_20" / "x.jpg",
        root / "2026 July" / "2026_07_21" / "y.jpg",
    ]:
        Image.new("RGB", (32, 24), (90, 90, 90)).save(path, format="JPEG")
    return root


@pytest.fixture
def tree_window(qt_app, tmp_path, nested_shoot):
    win = MainWindow(catalog_dir=tmp_path / "tree_catalog")
    scan_folder(win.catalog, nested_shoot)
    win.refresh_folders()
    win.refresh_photos()
    yield win
    _shutdown(win)


def _tree_labels(window):
    tree = window.filter_panel.folder_tree
    labels = []

    def walk(item, depth):
        labels.append("  " * depth + item.text(0))
        for row in range(item.childCount()):
            walk(item.child(row), depth + 1)

    for row in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(row), 0)
    return labels


def test_folder_tree_nests_subfolders_under_their_root(tree_window):
    labels = _tree_labels(tree_window)

    assert labels[0] == "All folders"
    assert "RAW" in labels
    assert "  2026 July" in labels  # child of RAW
    assert "    2026_07_20" in labels  # grandchild, properly nested
    assert "  macro" in labels


def test_selecting_a_subfolder_narrows_the_grid(tree_window):
    assert tree_window.grid_model.rowCount() == 4  # everything, by default

    _select_directory(tree_window, "macro")

    assert tree_window.grid_model.rowCount() == 1
    assert tree_window.grid_model.photo_at(0).filename == "a.jpg"


def test_selecting_a_parent_includes_its_subfolders(tree_window):
    _select_directory(tree_window, "2026 July")

    # Both date subfolders, even though neither was selected directly.
    assert tree_window.grid_model.rowCount() == 2
    assert sorted(tree_window.grid_model.photo_at(i).filename for i in range(2)) == ["x.jpg", "y.jpg"]


def test_selecting_a_leaf_date_folder_shows_only_that_day(tree_window):
    _select_directory(tree_window, "2026_07_20")

    assert tree_window.grid_model.rowCount() == 1
    assert tree_window.grid_model.photo_at(0).filename == "x.jpg"


def test_tree_is_alphabetical_even_for_folders_holding_only_subfolders(qt_app, tmp_path):
    """'2026 July' contains no photos directly — only date subfolders — so it is created
    as an intermediate node after its siblings and must still sort into place."""
    root = tmp_path / "RAW"
    (root / "2026 July" / "2026_07_20").mkdir(parents=True)
    (root / "AAA").mkdir()
    (root / "ZZZ").mkdir()
    Image.new("RGB", (16, 16)).save(root / "2026 July" / "2026_07_20" / "x.jpg")
    Image.new("RGB", (16, 16)).save(root / "AAA" / "a.jpg")
    Image.new("RGB", (16, 16)).save(root / "ZZZ" / "z.jpg")

    win = MainWindow(catalog_dir=tmp_path / "cat")
    try:
        scan_folder(win.catalog, root)
        win.refresh_folders()

        root_item = win.filter_panel.folder_tree.topLevelItem(1)
        children = [root_item.child(i).text(0) for i in range(root_item.childCount())]
        assert children == ["2026 July", "AAA", "ZZZ"]
    finally:
        _shutdown(win)


def test_all_folders_shows_the_whole_library_again(tree_window):
    _select_directory(tree_window, "macro")
    assert tree_window.grid_model.rowCount() == 1

    tree = tree_window.filter_panel.folder_tree
    tree.setCurrentItem(tree.topLevelItem(0))  # "All folders"
    tree_window.refresh_photos()

    assert tree_window.grid_model.rowCount() == 4


def _select_directory(window, label: str) -> None:
    tree = window.filter_panel.folder_tree
    matches = tree.findItems(label, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
    assert matches, f"no tree node labelled {label!r}"
    tree.setCurrentItem(matches[0])
    window.refresh_photos()
