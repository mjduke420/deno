import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from core.catalog import Photo
from ui.library_view import PhotoGridModel


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


class _StubLoader:
    """Stands in for ThumbnailLoader: records requests, never starts a thread."""

    def __init__(self):
        self.requested: list[str] = []
        self._slots = []

    # mimics the `thumbnail_ready` Signal surface the model connects to
    @property
    def thumbnail_ready(self):
        return self

    def connect(self, slot):
        self._slots.append(slot)

    def request(self, photo_path: str) -> None:
        self.requested.append(photo_path)

    def deliver(self, photo_path: str, thumbnail_path: str) -> None:
        for slot in self._slots:
            slot(photo_path, thumbnail_path)


def _photo(photo_id: int, name: str, **overrides) -> Photo:
    defaults = dict(
        id=photo_id,
        folder_id=1,
        path=f"/lib/{name}",
        filename=name,
        rating=0,
        flag="none",
        color_label=None,
        is_missing=False,
    )
    defaults.update(overrides)
    return Photo(**defaults)


@pytest.fixture
def model(qt_app):
    return PhotoGridModel(_StubLoader(), thumb_size=64)


def test_row_count_tracks_photos(model):
    assert model.rowCount() == 0
    model.set_photos([_photo(1, "a.CR3"), _photo(2, "b.CR3")])
    assert model.rowCount() == 2


def test_display_role_is_the_filename(model):
    model.set_photos([_photo(1, "a.CR3")])
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "a.CR3"


def test_photo_role_returns_the_record(model):
    model.set_photos([_photo(7, "a.CR3")])
    photo = model.data(model.index(0, 0), PhotoGridModel.PhotoRole)
    assert photo.id == 7


def test_out_of_range_index_returns_none(model):
    model.set_photos([_photo(1, "a.CR3")])
    assert model.data(model.index(5, 0), Qt.ItemDataRole.DisplayRole) is None


def test_uncached_thumbnail_requests_generation_and_shows_a_placeholder(qt_app):
    loader = _StubLoader()
    model = PhotoGridModel(loader, thumb_size=64)
    model.set_photos([_photo(1, "a.CR3")])

    pixmap = model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)

    assert isinstance(pixmap, QPixmap)
    assert not pixmap.isNull()
    assert loader.requested == ["/lib/a.CR3"]


def test_tooltip_includes_metadata_when_present(model):
    model.set_photos(
        [_photo(1, "a.CR3", captured_at="2026-01-15 09:30:00", camera_model="Canon EOS R8", iso=800.0)]
    )
    tooltip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)

    assert "a.CR3" in tooltip
    assert "Canon EOS R8" in tooltip
    assert "ISO 800" in tooltip


def test_tooltip_marks_missing_files(model):
    model.set_photos([_photo(1, "gone.CR3", is_missing=True)])
    assert "missing" in model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)


def test_update_photo_replaces_the_row_in_place(model):
    model.set_photos([_photo(1, "a.CR3"), _photo(2, "b.CR3")])

    model.update_photo(_photo(2, "b.CR3", rating=5))

    assert model.photo_at(1).rating == 5
    assert model.rowCount() == 2  # no rebuild


def test_update_photo_ignores_photos_not_in_the_current_view(model):
    model.set_photos([_photo(1, "a.CR3")])
    model.update_photo(_photo(99, "elsewhere.CR3", rating=5))
    assert model.rowCount() == 1


def test_row_lookup_by_photo_id(model):
    model.set_photos([_photo(1, "a.CR3"), _photo(2, "b.CR3")])
    assert model.row_for_photo_id(2) == 1
    assert model.row_for_photo_id(999) is None


def test_pixmap_cache_is_bounded(qt_app, tmp_path, monkeypatch):
    import ui.library_view as library_view

    monkeypatch.setattr(library_view, "PIXMAP_CACHE_LIMIT", 3)
    loader = _StubLoader()
    model = library_view.PhotoGridModel(loader, thumb_size=16)

    thumbnail = tmp_path / "thumb.jpg"
    QPixmap(16, 16).save(str(thumbnail), "JPEG")

    photos = [_photo(i, f"{i}.CR3") for i in range(10)]
    model.set_photos(photos)
    for photo in photos:
        loader.deliver(photo.path, str(thumbnail))

    assert len(model._pixmaps) <= 3
