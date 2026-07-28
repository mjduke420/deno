"""Background QThread workers so expensive core/ operations never block the UI."""
from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QThread, Signal

from core.catalog import Catalog
from core.denoise import NafnetDenoiser
from core.exporter import export_photos
from core.pipeline import Pipeline
from core.scanner import scan_folder
from core.thumbnails import ThumbnailCache


class DenoiseWorker(QThread):
    progress = Signal(int, int)  # done, total
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, get_or_create_denoiser: Callable[[], NafnetDenoiser], parent=None):
        super().__init__(parent)
        self._pipeline = pipeline
        self._get_or_create_denoiser = get_or_create_denoiser

    def run(self) -> None:
        try:
            denoiser = self._get_or_create_denoiser()
            self._pipeline.run_denoise(denoiser, progress_cb=lambda done, total: self.progress.emit(done, total))
        except Exception as exc:  # model load / CUDA / OOM errors, surfaced to the UI
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class ScanWorker(QThread):
    """Catalogs a folder's photos off the UI thread."""

    progress = Signal(int, int)  # done, total
    finished_ok = Signal(int, int)  # added, failed
    failed = Signal(str)

    def __init__(self, catalog: Catalog, folder: str, parent=None):
        super().__init__(parent)
        self._catalog = catalog
        self._folder = folder
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = scan_folder(
                self._catalog,
                self._folder,
                progress_cb=lambda done, total: self.progress.emit(done, total),
                should_cancel=self._cancelled.is_set,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result.added, result.failed)


class BatchExportWorker(QThread):
    """Exports a set of photos to JPEG off the UI thread, each with its own edits."""

    progress = Signal(int, int)  # done, total
    finished_ok = Signal(int, int)  # exported, failed
    failed = Signal(str)

    def __init__(self, photos: list, output_dir: str, quality: int, parent=None):
        super().__init__(parent)
        self._photos = photos
        self._output_dir = output_dir
        self._quality = quality
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = export_photos(
                self._photos,
                self._output_dir,
                self._quality,
                progress_cb=lambda done, total: self.progress.emit(done, total),
                should_cancel=self._cancelled.is_set,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result.exported, result.failed)


class ThumbnailLoader(QThread):
    """Generates grid thumbnails on demand, newest request first.

    The grid asks for thumbnails as rows scroll into view, so requests are served
    LIFO — whatever the user is looking at right now jumps ahead of the backlog.
    """

    thumbnail_ready = Signal(str, str)  # photo path, cached thumbnail path

    def __init__(self, cache: ThumbnailCache, parent=None):
        super().__init__(parent)
        self._cache = cache
        self._pending: list[str] = []
        self._queued: set[str] = set()
        self._condition = threading.Condition()
        self._stopping = False

    def request(self, photo_path: str) -> None:
        with self._condition:
            if photo_path in self._queued:
                return
            self._queued.add(photo_path)
            self._pending.append(photo_path)
            self._condition.notify()

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()

    def run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                photo_path = self._pending.pop()  # LIFO: most recently scrolled into view
                self._queued.discard(photo_path)

            thumbnail = self._cache.get(photo_path)
            if thumbnail is not None:
                self.thumbnail_ready.emit(photo_path, str(thumbnail))
