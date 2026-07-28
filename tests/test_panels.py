"""Panels must be able to *load* a photo's saved edits, not just emit user changes.

The subtle failure this guards against: writing values into a slider re-emits its
valueChanged signal, which the app would treat as a fresh user edit and immediately
write back — clobbering the settings being restored.
"""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from core.lens_correction import LensSettings
from core.tone_pipeline import ToneSettings
from ui.panels.exposure_panel import ExposurePanel
from ui.panels.lens_panel import LensPanel


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_exposure_panel_round_trips_settings(qt_app):
    panel = ExposurePanel()
    settings = ToneSettings(exposure=1.5, contrast=20.0, highlights=-30.0, shadows=40.0, whites=10.0, blacks=-5.0)

    panel.set_settings(settings)

    assert panel.settings() == settings


def test_exposure_panel_does_not_emit_while_loading(qt_app):
    panel = ExposurePanel()
    emissions = []
    panel.settings_changed.connect(emissions.append)

    panel.set_settings(ToneSettings(exposure=2.0, contrast=50.0))

    assert emissions == []


def test_exposure_panel_still_emits_on_real_user_changes(qt_app):
    panel = ExposurePanel()
    emissions = []
    panel.settings_changed.connect(emissions.append)

    panel._sliders["exposure"].setValue(100)  # as if dragged

    assert len(emissions) == 1
    assert emissions[0].exposure == pytest.approx(1.0)


def test_exposure_panel_resets_back_to_defaults(qt_app):
    panel = ExposurePanel()
    panel.set_settings(ToneSettings(exposure=3.0, shadows=80.0))
    panel.set_settings(ToneSettings())

    assert panel.settings() == ToneSettings()
    assert panel._sliders["exposure"].value() == 0


def test_lens_panel_round_trips_settings(qt_app):
    panel = LensPanel()
    settings = LensSettings(distortion=30.0, vignetting=-45.0, remove_chromatic_aberration=True)

    panel.set_settings(settings)

    assert panel.settings() == settings
    assert panel._ca_checkbox.isChecked() is True


def test_lens_panel_does_not_emit_while_loading(qt_app):
    panel = LensPanel()
    emissions = []
    panel.settings_changed.connect(emissions.append)

    panel.set_settings(LensSettings(distortion=50.0, remove_chromatic_aberration=True))

    assert emissions == []


def test_lens_panel_still_emits_on_real_user_changes(qt_app):
    panel = LensPanel()
    emissions = []
    panel.settings_changed.connect(emissions.append)

    panel._ca_checkbox.setChecked(True)

    assert len(emissions) == 1
    assert emissions[0].remove_chromatic_aberration is True


def _double_click(slider) -> None:
    slider.mouseDoubleClickEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            QPointF(0, 0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def test_exposure_panel_has_the_full_basic_slider_set(qt_app):
    panel = ExposurePanel()
    for name in (
        "exposure", "contrast", "highlights", "shadows", "whites", "blacks",
        "clarity", "vibrance", "dehaze",
    ):
        assert name in panel._sliders, f"missing {name} slider"


def test_double_click_resets_a_slider_to_zero(qt_app):
    panel = ExposurePanel()
    slider = panel._sliders["clarity"]
    slider.setValue(70)
    assert panel.settings().clarity == 70.0

    _double_click(slider)

    assert slider.value() == 0
    assert panel.settings().clarity == 0.0


def test_double_click_reset_notifies_listeners(qt_app):
    """Resetting must re-render, so it has to emit like any other user change."""
    panel = ExposurePanel()
    panel._sliders["exposure"].setValue(200)
    emissions = []
    panel.settings_changed.connect(emissions.append)

    _double_click(panel._sliders["exposure"])

    assert emissions and emissions[-1].exposure == 0.0


def test_lens_panel_sliders_also_reset_on_double_click(qt_app):
    panel = LensPanel()
    slider = panel._sliders["distortion"]
    slider.setValue(60)

    _double_click(slider)

    assert slider.value() == 0
    assert panel.settings().distortion == 0.0


def test_new_sliders_round_trip(qt_app):
    panel = ExposurePanel()
    settings = ToneSettings(clarity=40.0, vibrance=-25.0, dehaze=60.0)

    panel.set_settings(settings)

    assert panel.settings() == settings


def test_loading_a_second_photo_fully_replaces_the_first(qt_app):
    """Switching photos must not leave the previous photo's edits behind."""
    panel = ExposurePanel()
    panel.set_settings(ToneSettings(exposure=2.0, contrast=40.0, shadows=60.0))

    panel.set_settings(ToneSettings(exposure=-1.0))

    loaded = panel.settings()
    assert loaded.exposure == -1.0
    assert loaded.contrast == 0.0
    assert loaded.shadows == 0.0
