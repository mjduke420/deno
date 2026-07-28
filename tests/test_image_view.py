"""The canvas should keep the photo fitted as the window changes, but never
silently undo a zoom the user chose."""
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from ui.image_view import ImageView


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


def _image(width=800, height=533) -> QImage:
    img = QImage(width, height, QImage.Format.Format_RGB888)
    img.fill(0x808080)
    return img


def _scale_of(view: ImageView) -> float:
    return view.transform().m11()


def _fills_viewport(view: ImageView, image: QImage) -> bool:
    """The fitted image should be as large as it can be while still fitting."""
    viewport = view.viewport().size()
    expected = min(viewport.width() / image.width(), viewport.height() / image.height())
    return _scale_of(view) == pytest.approx(expected, rel=0.05)


def test_image_is_fitted_on_first_load(qt_app):
    view = ImageView()
    view.resize(400, 300)
    image = _image()

    view.set_image(image)

    assert _fills_viewport(view, image)


def test_resizing_refits_a_photo_the_user_has_not_zoomed(qt_app):
    view = ImageView()
    view.resize(400, 300)
    image = _image()
    view.set_image(image)

    view.resize(900, 700)

    assert _fills_viewport(view, image)


def test_resizing_preserves_a_zoom_the_user_chose(qt_app):
    view = ImageView()
    view.resize(400, 300)
    view.set_image(_image())
    view.scale(3.0, 3.0)
    view._user_zoomed = True
    zoomed = _scale_of(view)

    view.resize(800, 600)

    assert _scale_of(view) == pytest.approx(zoomed)


def test_fit_to_window_clears_the_zoom_flag(qt_app):
    view = ImageView()
    view.resize(400, 300)
    view.set_image(_image())
    view._user_zoomed = True

    view.fit_to_window()

    assert view._user_zoomed is False


def test_new_image_is_refitted_when_not_zoomed(qt_app):
    """Switching photos should show the whole frame, not inherit the old scale."""
    view = ImageView()
    view.resize(400, 300)
    view.set_image(_image(800, 533))

    bigger = _image(4000, 2667)
    view.set_image(bigger)

    assert _fills_viewport(view, bigger)


def test_setting_an_image_before_any_layout_does_not_crash(qt_app):
    ImageView().set_image(_image())
