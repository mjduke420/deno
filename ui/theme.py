"""Dark application theme.

Photo editors run dark for a practical reason: a bright interface around an image
biases how you judge its exposure and colour. Everything here stays neutral grey so
nothing competes with the photograph.
"""
from __future__ import annotations

BACKGROUND = "#1e1e1e"
PANEL = "#2a2a2a"
PANEL_RAISED = "#323232"
BORDER = "#3c3c3c"
TEXT = "#d8d8d8"
TEXT_DIM = "#9a9a9a"
ACCENT = "#4a90d9"
CANVAS = "#141414"

STYLESHEET = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT};
    font-size: 12px;
}}

QMainWindow, QDialog {{ background-color: {BACKGROUND}; }}

/* The image canvas sits darker than the chrome so the photo reads as the subject. */
QGraphicsView {{
    background-color: {CANVAS};
    border: 1px solid {BORDER};
}}

/* Collapsible panels: the title is a header row inside the frame, not a label
   floating on the border the way QGroupBox draws it. */
QFrame#collapsiblePanel {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
QWidget#panelHeader {{
    background-color: {PANEL_RAISED};
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    border-bottom: 1px solid {BORDER};
}}
QWidget#panelHeader:hover {{ background-color: #3a3a3a; }}
QLabel#panelTitle {{
    color: {TEXT};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QLabel#panelArrow {{ color: {TEXT_DIM}; font-size: 10px; }}
QWidget#panelContent {{ background-color: {PANEL}; border: none; }}

/* Module switcher in the menu bar corner */
QWidget#moduleTabs {{ background: transparent; }}
QPushButton#moduleTab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 5px 14px;
    color: {TEXT_DIM};
    font-weight: 600;
}}
QPushButton#moduleTab:hover {{ color: {TEXT}; }}
QPushButton#moduleTab:checked {{
    color: #ffffff;
    border-bottom: 2px solid {ACCENT};
}}

QLabel {{ background: transparent; }}

QPushButton {{
    background-color: {PANEL_RAISED};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 5px 10px;
    min-height: 16px;
}}
QPushButton:hover  {{ background-color: #3c3c3c; border-color: #4a4a4a; }}
QPushButton:pressed {{ background-color: {ACCENT}; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #5a5a5a; background-color: #262626; }}

QComboBox {{
    background-color: {PANEL_RAISED};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 4px 8px;
    min-height: 16px;
}}
QComboBox:hover {{ border-color: #4a4a4a; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {PANEL_RAISED};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    outline: none;
}}

/* Sliders: thin neutral groove, clear handle, obvious hover target. */
QSlider::groove:horizontal {{
    height: 3px;
    background: #454545;
    border-radius: 1px;
}}
QSlider::sub-page:horizontal {{ background: #6a6a6a; border-radius: 1px; }}
QSlider::handle:horizontal {{
    background: #d0d0d0;
    border: none;
    width: 11px;
    height: 11px;
    margin: -4px 0;
    border-radius: 5px;
}}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider::handle:horizontal:disabled {{ background: #555555; }}

QCheckBox {{ spacing: 6px; background: transparent; }}
QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid #555555;
    border-radius: 2px;
    background: {PANEL_RAISED};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QProgressBar {{
    background-color: #262626;
    border: 1px solid {BORDER};
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 2px; }}

/* Grid and trees */
QListView {{
    background-color: {CANVAS};
    border: 1px solid {BORDER};
    outline: none;
}}
QTreeWidget, QListWidget {{
    background-color: #252525;
    border: 1px solid {BORDER};
    outline: none;
}}
QTreeWidget::item, QListWidget::item {{ padding: 3px 2px; border-radius: 2px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background-color: #313131; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background-color: {ACCENT}; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #4a4a4a;
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #5c5c5c; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: #4a4a4a;
    border-radius: 5px;
    min-width: 30px;
}}

QMenuBar {{ background-color: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ background-color: {PANEL_RAISED}; }}
QMenu {{ background-color: {PANEL_RAISED}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px; border-radius: 3px; }}
QMenu::item:selected {{ background-color: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QStatusBar {{ background-color: {PANEL}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QStatusBar::item {{ border: none; }}

QSplitter::handle {{ background-color: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

QToolTip {{
    background-color: #f0f0f0;
    color: #202020;
    border: none;
    padding: 4px 6px;
}}
"""


def apply(app) -> None:
    """Apply the theme to a QApplication."""
    app.setStyle("Fusion")  # consistent widget metrics across platforms before styling
    app.setStyleSheet(STYLESHEET)
