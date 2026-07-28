"""Main window: coordinates the Library and Develop modules over a shared catalog."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from core.builtin_presets import seed_builtin_presets
from core.catalog import Catalog, Photo, PhotoFilter, default_catalog_dir
from core.scanner import read_metadata
from core.thumbnails import ThumbnailCache
from ui.develop_view import DevelopView
from ui.library_view import LibraryView, PhotoGridModel
from ui.module_tabs import ModuleTabs
from ui.panels.filter_panel import FilterPanel
from ui.panels.library_export_panel import SCOPE_SELECTED, LibraryExportPanel
from ui.workers import BatchExportWorker, ScanWorker, ThumbnailLoader

LIBRARY_PAGE = 0
DEVELOP_PAGE = 1
_EDIT_FLUSH_DELAY_MS = 400  # debounce: don't write to SQLite on every slider tick


class MainWindow(QMainWindow):
    def __init__(self, catalog_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle("RAW Library")
        self.resize(1500, 950)

        catalog_dir = Path(catalog_dir or default_catalog_dir())
        self.catalog = Catalog(catalog_dir / "catalog.db")
        self.thumbnail_cache = ThumbnailCache(catalog_dir / "thumbs")
        self.thumbnail_loader = ThumbnailLoader(self.thumbnail_cache, self)
        self.thumbnail_loader.start()

        self._scan_worker: ScanWorker | None = None
        self._export_worker: BatchExportWorker | None = None
        self._current_photo: Photo | None = None

        # Edits are flushed on a short delay, plus on photo switch and on close, so a
        # slider drag doesn't hammer the database but nothing is ever lost.
        self._edit_flush_timer = QTimer(self)
        self._edit_flush_timer.setSingleShot(True)
        self._edit_flush_timer.setInterval(_EDIT_FLUSH_DELAY_MS)
        self._edit_flush_timer.timeout.connect(self.flush_pending_edits)

        self._build_ui()
        self._build_menu()
        seed_builtin_presets(self.catalog)
        self.refresh_folders()
        self.refresh_photos()
        self.refresh_presets()

    # ---------- construction ----------

    def _build_ui(self) -> None:
        self.grid_model = PhotoGridModel(self.thumbnail_loader, parent=self)
        self.library_view = LibraryView(self.grid_model)
        self.library_view.photo_activated.connect(self.open_in_develop)
        self.library_view.rating_requested.connect(self._on_rating_requested)
        self.library_view.flag_requested.connect(self._on_flag_requested)
        self.library_view.color_label_requested.connect(self._on_color_label_requested)

        self.filter_panel = FilterPanel(self)
        self.filter_panel.filter_changed.connect(lambda *_: self.refresh_photos())
        self.filter_panel.add_folder_requested.connect(self.add_folder_dialog)
        self.filter_panel.remove_folder_requested.connect(self._on_remove_folder)

        self.library_export_panel = LibraryExportPanel(self)
        self.library_export_panel.export_requested.connect(self._on_batch_export_requested)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(self.filter_panel, 1)
        sidebar_layout.addWidget(self.library_export_panel, 0)

        library_page = QSplitter(Qt.Orientation.Horizontal)
        library_page.addWidget(sidebar)
        library_page.addWidget(self.library_view)
        library_page.setStretchFactor(0, 0)
        library_page.setStretchFactor(1, 1)
        library_page.setSizes([280, 1200])

        self.develop_view = DevelopView(self)
        self.develop_view.edits_changed.connect(self._on_edits_changed)
        self.develop_view.status_message.connect(self._show_status)
        self.develop_view.preset_panel.apply_requested.connect(self._on_preset_apply)
        self.develop_view.preset_panel.save_requested.connect(self._on_preset_save)
        self.develop_view.preset_panel.delete_requested.connect(self._on_preset_delete)

        self.pages = QStackedWidget(self)
        self.pages.addWidget(library_page)
        self.pages.addWidget(self.develop_view)
        self.setCentralWidget(self.pages)

        # Module switcher lives in the menu bar's right corner, always reachable.
        self.module_tabs = ModuleTabs(["Library", "Develop"], self)
        self.module_tabs.module_selected.connect(self._on_module_selected)
        self.menuBar().setCornerWidget(self.module_tabs, Qt.Corner.TopRightCorner)

        self.setStatusBar(QStatusBar(self))
        self.scan_progress = QProgressBar()
        self.scan_progress.setMaximumWidth(220)
        self.scan_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.scan_progress)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.add_folder_action = file_menu.addAction("&Add Folder…")
        self.add_folder_action.setShortcut(QKeySequence("Ctrl+O"))
        self.add_folder_action.triggered.connect(self.add_folder_dialog)

        view_menu = self.menuBar().addMenu("&View")
        library_action = view_menu.addAction("&Library")
        library_action.setShortcut(QKeySequence("G"))
        library_action.triggered.connect(self.show_library)

        develop_action = view_menu.addAction("&Develop")
        develop_action.setShortcut(QKeySequence("D"))
        develop_action.triggered.connect(self.show_develop)

        view_menu.addSeparator()
        self.before_after_action = view_menu.addAction("Show &Before (Original)")
        self.before_after_action.setCheckable(True)
        self.before_after_action.setShortcut(QKeySequence("\\"))
        self.before_after_action.toggled.connect(self.develop_view.set_showing_before)

    # ---------- catalog views ----------

    def refresh_folders(self) -> None:
        self.filter_panel.set_folders(self.catalog.list_folders(), self.catalog.list_directories())

    def refresh_photos(self) -> None:
        photos = self.catalog.query_photos(self.filter_panel.current_filter())
        self.grid_model.set_photos(photos)
        total = self.catalog.count_photos(PhotoFilter())
        self.filter_panel.set_summary(f"{len(photos)} of {total} photos")

    # ---------- folders ----------

    def add_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder to catalog")
        if folder:
            self.add_folder(folder)

    def add_folder(self, folder: str) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            QMessageBox.information(self, "Scan in progress", "Please wait for the current scan to finish.")
            return

        self.add_folder_action.setEnabled(False)
        self.scan_progress.setVisible(True)
        self.scan_progress.setRange(0, 0)  # indeterminate until the first progress tick
        self._show_status(f"Scanning {Path(folder).name}…")

        self._scan_worker = ScanWorker(self.catalog, folder, self)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_ok.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _on_scan_progress(self, done: int, total: int) -> None:
        self.scan_progress.setRange(0, total)
        self.scan_progress.setValue(done)

    def _on_scan_finished(self, added: int, failed: int) -> None:
        self.add_folder_action.setEnabled(True)
        self.scan_progress.setVisible(False)
        self.refresh_folders()
        self.refresh_photos()
        message = f"Added {added} photos"
        if failed:
            message += f" ({failed} could not be read)"
        self._show_status(message)

    def _on_scan_failed(self, message: str) -> None:
        self.add_folder_action.setEnabled(True)
        self.scan_progress.setVisible(False)
        QMessageBox.critical(self, "Scan failed", message)

    def _on_remove_folder(self, folder_id: int) -> None:
        confirm = QMessageBox.question(
            self,
            "Remove folder from catalog?",
            "This removes the folder and its ratings from the catalog.\n"
            "The photo files on disk are not touched.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Flush before deleting, so edits made to a photo in this folder are saved
        # while its catalog row still exists.
        self.flush_pending_edits()

        removed_paths = self.catalog.photo_paths_in_folder(folder_id)
        # The photo open in Develop may belong to the folder being removed; drop the
        # reference so a later flush can't write against a deleted row.
        if self._current_photo is not None and self._current_photo.folder_id == folder_id:
            self._current_photo = None

        self.catalog.remove_folder(folder_id)
        for path in removed_paths:
            self.thumbnail_cache.discard(path)

        self.refresh_folders()
        self.refresh_photos()

    # ---------- ratings ----------

    def _on_rating_requested(self, photos: list[Photo], rating: int) -> None:
        self._apply_to_photos(photos, self.catalog.set_rating_bulk, rating)

    def _on_flag_requested(self, photos: list[Photo], flag: str) -> None:
        self._apply_to_photos(photos, self.catalog.set_flag_bulk, flag)

    def _on_color_label_requested(self, photos: list[Photo], color_label: str | None) -> None:
        self._apply_to_photos(photos, self.catalog.set_color_label_bulk, color_label)

    def _apply_to_photos(self, photos: list[Photo], bulk_action, value) -> None:
        """Apply a culling action to a whole selection in one transaction — a
        select-all rating over thousands of photos must not stall the UI."""
        if not photos:
            return
        bulk_action([photo.id for photo in photos], value)
        for photo in photos:
            updated = self.catalog.get_photo(photo.id)
            if updated is not None:
                self.grid_model.update_photo(updated)
        self._show_status(f"Updated {len(photos)} photo(s)")

    # ---------- modules ----------

    def _on_module_selected(self, index: int) -> None:
        if index == DEVELOP_PAGE:
            self.show_develop()
        else:
            self.show_library()

    def show_library(self) -> None:
        self.flush_pending_edits()
        self.pages.setCurrentIndex(LIBRARY_PAGE)
        self.module_tabs.set_current(LIBRARY_PAGE)
        self.refresh_photos()
        # Return to the photo you were editing rather than the top of the grid.
        if self._current_photo is not None:
            self.select_photo_in_grid(self._current_photo.id)
        self.library_view.setFocus()

    def select_photo_in_grid(self, photo_id: int) -> None:
        """Select and scroll to a photo, if it is in the current filtered view."""
        row = self.grid_model.row_for_photo_id(photo_id)
        if row is None:
            return  # filtered out of the current view
        index = self.grid_model.index(row, 0)
        self.library_view.setCurrentIndex(index)
        self.library_view.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    def show_develop(self) -> None:
        if not self.develop_view.has_photo():
            photo = self.library_view.current_photo()
            if photo is None:
                self._show_status("Select a photo in the library first")
                self.module_tabs.set_current(LIBRARY_PAGE)  # the switch didn't happen
                return
            self.open_in_develop(photo)
            return
        self.pages.setCurrentIndex(DEVELOP_PAGE)
        self.module_tabs.set_current(DEVELOP_PAGE)

    def open_in_develop(self, photo: Photo) -> None:
        if photo.is_missing or not Path(photo.path).exists():
            QMessageBox.warning(self, "File missing", f"{photo.filename} is no longer at:\n{photo.path}")
            self.catalog.mark_missing(photo.id)
            refreshed = self.catalog.get_photo(photo.id)
            if refreshed is not None:
                self.grid_model.update_photo(refreshed)
            return

        # Persist the outgoing photo's edits *before* the pipeline is reloaded.
        self.flush_pending_edits()

        if self.develop_view.load_photo(photo.path, self.catalog.load_edits(photo.id)):
            self._current_photo = photo
            self.before_after_action.setChecked(False)
            self.pages.setCurrentIndex(DEVELOP_PAGE)
            self.module_tabs.set_current(DEVELOP_PAGE)

    # ---------- batch export ----------

    def _on_batch_export_requested(self, scope: str, quality: int) -> None:
        if self._export_worker is not None and self._export_worker.isRunning():
            QMessageBox.information(self, "Export in progress", "Please wait for the current export to finish.")
            return

        # Make sure the photo currently open in Develop exports with its latest edits.
        self.flush_pending_edits()

        if scope == SCOPE_SELECTED:
            photos = self.library_view.selected_photos()
            if not photos:
                QMessageBox.information(self, "Nothing selected", "Select photos to export, or choose 'All filtered'.")
                return
        else:
            photos = self.catalog.query_photos(self.filter_panel.current_filter())
            if not photos:
                QMessageBox.information(self, "Nothing to export", "No photos match the current filter.")
                return

        output_dir = QFileDialog.getExistingDirectory(self, "Export to folder")
        if not output_dir:
            return

        # Re-read so each photo carries its freshly-flushed edits.
        photos = [self.catalog.get_photo(photo.id) or photo for photo in photos]

        self.library_export_panel.show_progress(0, len(photos))
        self._export_worker = BatchExportWorker(photos, output_dir, quality, self)
        self._export_worker.progress.connect(self.library_export_panel.show_progress)
        self._export_worker.finished_ok.connect(self._on_export_finished)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.start()

    def _on_export_finished(self, exported: int, failed: int) -> None:
        message = f"Exported {exported} photo(s)"
        if failed:
            message += f" ({failed} failed)"
        self.library_export_panel.show_idle(message)
        self._show_status(message)

    def _on_export_failed(self, message: str) -> None:
        self.library_export_panel.show_idle("")
        QMessageBox.critical(self, "Export failed", message)

    # ---------- presets ----------

    def refresh_presets(self) -> None:
        self.develop_view.preset_panel.set_presets(self.catalog.list_presets())

    def _on_preset_apply(self, preset_id: int) -> None:
        if not self.develop_view.has_photo():
            self._show_status("Open a photo before applying a preset")
            return
        preset = self.catalog.get_preset(preset_id)
        if preset is None:
            self.refresh_presets()  # deleted in another window, or stale list
            return
        # Keep this photo's own denoise settings; a preset carries the look only.
        look = preset.edits.merged_with(self.develop_view.edit_state())
        self.develop_view.apply_edit_state(look)
        self.flush_pending_edits()
        self._show_status(f"Applied preset '{preset.name}'")

    def _on_preset_save(self, name: str) -> None:
        if not self.develop_view.has_photo():
            self._show_status("Open a photo before saving a preset")
            return
        existing = self.catalog.get_preset_by_name(name)
        if existing is not None:
            confirm = QMessageBox.question(
                self, "Replace preset?", f"'{name}' already exists. Replace it?"
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        # Denoise is deliberately excluded — it is per-photo, costs a GPU pass, and
        # depends on that frame's ISO rather than on the look being saved.
        self.catalog.save_preset(name, self.develop_view.edit_state().without_denoise())
        self.refresh_presets()
        self._show_status(f"Saved preset '{name}'")

    def _on_preset_delete(self, preset_id: int) -> None:
        self.catalog.delete_preset(preset_id)
        self.refresh_presets()
        self._show_status("Preset deleted")

    # ---------- edit persistence ----------

    def _on_edits_changed(self) -> None:
        self._edit_flush_timer.start()

    def flush_pending_edits(self) -> None:
        """Write the Develop module's current adjustments back to the catalog."""
        self._edit_flush_timer.stop()
        if self._current_photo is None or not self.develop_view.has_photo():
            return
        try:
            self.catalog.save_edits(self._current_photo.id, self.develop_view.edit_state())
        except KeyError:
            # The photo left the catalog (its folder was removed) while it was open.
            # Nothing to persist to, and this runs from a timer slot where an
            # uncaught exception would take the process down.
            self._current_photo = None
            return

        refreshed = self.catalog.get_photo(self._current_photo.id)
        if refreshed is not None:
            self.grid_model.update_photo(refreshed)

    # ---------- compatibility ----------

    def load_raw_file(self, path: str) -> None:
        """Open a single file directly (CLI argument / 'Open with').

        Catalogs just this one file synchronously — routing through `add_folder`
        would start a background scan and return before the photo exists in the
        catalog, leaving nothing to open.
        """
        photo_path = Path(path)
        if not photo_path.is_file():
            QMessageBox.warning(self, "File not found", str(photo_path))
            return

        try:
            folder_id = self.catalog.add_folder(photo_path.parent)
            metadata = read_metadata(photo_path)
            photo_id = self.catalog.upsert_photo(folder_id, photo_path, **asdict(metadata))
        except Exception as exc:
            QMessageBox.critical(self, "Could not open photo", f"{photo_path.name}\n\n{exc}")
            return

        self.refresh_folders()
        self.refresh_photos()

        photo = self.catalog.get_photo(photo_id)
        if photo is not None:
            self.open_in_develop(photo)

    # ---------- lifecycle ----------

    def _show_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Destroying a QThread while its native thread still runs is a documented
        # PySide6 crash risk, so block closing until GPU/scan work settles.
        if self.develop_view.is_denoising():
            QMessageBox.information(
                self, "AI Denoise running", "Please wait for AI Denoise to finish before closing."
            )
            event.ignore()
            return
        # Cancellation is only checked between files, so a stalled read (dead network
        # share, unreadable file) can outlive the timeout. If a worker won't stop, keep
        # the catalog open and refuse the close rather than tearing down a live thread
        # or pulling the database out from under it.
        for worker, timeout_ms, label in (
            (self._scan_worker, 5000, "folder scan"),
            (self._export_worker, 10000, "export"),
        ):
            if worker is not None and worker.isRunning():
                worker.cancel()
                if not worker.wait(timeout_ms):
                    QMessageBox.information(
                        self,
                        "Still finishing",
                        f"The {label} is still stopping. Try closing again in a moment.",
                    )
                    event.ignore()
                    return

        self.flush_pending_edits()
        self.thumbnail_loader.stop()
        if not self.thumbnail_loader.wait(5000):
            # Thumbnail work only reads image files, so it can't corrupt the catalog;
            # leave the connection open and let the process exit take the thread.
            event.accept()
            return

        self.catalog.close()
        event.accept()
