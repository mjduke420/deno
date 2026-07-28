import pytest
from PySide6.QtWidgets import QApplication, QLabel

from ui.collapsible_panel import CollapsiblePanel
from ui.module_tabs import ModuleTabs


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


# ---------- collapsible panel ----------


def test_panel_starts_expanded_and_shows_its_content(qt_app):
    panel = CollapsiblePanel("Basic")
    panel.add_widget(QLabel("control"))

    assert panel.is_expanded()
    assert panel._content.isVisibleTo(panel)


def test_panel_can_start_collapsed(qt_app):
    panel = CollapsiblePanel("Basic", expanded=False)
    assert not panel.is_expanded()
    assert not panel._content.isVisibleTo(panel)


def test_clicking_the_header_toggles_the_panel(qt_app):
    panel = CollapsiblePanel("Basic")

    panel.header.clicked.emit()
    assert not panel.is_expanded()

    panel.header.clicked.emit()
    assert panel.is_expanded()


def test_toggling_emits_the_new_state(qt_app):
    panel = CollapsiblePanel("Basic")
    states = []
    panel.toggled.connect(states.append)

    panel.toggle()
    panel.toggle()

    assert states == [False, True]


def test_arrow_reflects_the_state(qt_app):
    panel = CollapsiblePanel("Basic")
    expanded_arrow = panel.header.arrow_label.text()

    panel.set_expanded(False)

    assert panel.header.arrow_label.text() != expanded_arrow


def test_title_is_shown_in_the_header(qt_app):
    """The title belongs to the panel, not to the gap above it."""
    panel = CollapsiblePanel("Lens Corrections")

    assert panel.header.title_label.text() == "Lens Corrections"
    assert panel.title == "Lens Corrections"


def test_content_added_survives_collapsing(qt_app):
    panel = CollapsiblePanel("Basic")
    label = QLabel("control")
    panel.add_widget(label)

    panel.set_expanded(False)
    panel.set_expanded(True)

    assert label.parent() is panel._content


# ---------- module tabs ----------


def test_tabs_start_on_the_first_module(qt_app):
    tabs = ModuleTabs(["Library", "Develop"])
    assert tabs._buttons[0].isChecked()
    assert not tabs._buttons[1].isChecked()


def test_clicking_a_tab_emits_its_index(qt_app):
    tabs = ModuleTabs(["Library", "Develop"])
    chosen = []
    tabs.module_selected.connect(chosen.append)

    tabs._buttons[1].click()

    assert chosen == [1]


def test_only_one_tab_is_active_at_a_time(qt_app):
    tabs = ModuleTabs(["Library", "Develop"])

    tabs._buttons[1].click()

    assert not tabs._buttons[0].isChecked()
    assert tabs._buttons[1].isChecked()


def test_set_current_does_not_emit(qt_app):
    """The window drives tab state when switching by keyboard or menu; that must not
    loop back and re-trigger the switch."""
    tabs = ModuleTabs(["Library", "Develop"])
    chosen = []
    tabs.module_selected.connect(chosen.append)

    tabs.set_current(1)

    assert chosen == []
    assert tabs._buttons[1].isChecked()
