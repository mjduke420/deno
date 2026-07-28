"""Entry point for the RAW AI Denoise desktop app."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ui import theme
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    theme.apply(app)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.load_raw_file(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
