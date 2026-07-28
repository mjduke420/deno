"""Library filter panel: pick a folder and narrow by rating, flag and colour label."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.catalog import COLOR_LABELS, Folder, PhotoFilter

_ALL_FOLDERS = "All folders"
_ANY = "Any"
_RATING_CHOICES = [("Any", 0), ("★ 1+", 1), ("★ 2+", 2), ("★ 3+", 3), ("★ 4+", 4), ("★ 5", 5)]
_FLAG_CHOICES = [(_ANY, None), ("Picked", "pick"), ("Rejected", "reject"), ("Unflagged", "none")]


class FilterPanel(QWidget):
    filter_changed = Signal(object)  # PhotoFilter
    add_folder_requested = Signal()
    remove_folder_requested = Signal(int)  # folder id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_folders_group())
        layout.addWidget(self._build_filters_group())
        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)
        layout.addStretch()

    # ---------- construction ----------

    def _build_folders_group(self) -> QGroupBox:
        group = QGroupBox("Folders")
        box = QVBoxLayout(group)

        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.currentItemChanged.connect(lambda *_: self._emit_filter())
        box.addWidget(self.folder_tree)

        add_button = QPushButton("Add Folder…")
        add_button.clicked.connect(self.add_folder_requested)
        box.addWidget(add_button)

        self.remove_button = QPushButton("Remove From Catalog")
        self.remove_button.setToolTip("Removes the folder from the catalog. Files on disk are untouched.")
        self.remove_button.clicked.connect(self._request_remove_folder)
        box.addWidget(self.remove_button)

        return group

    def _build_filters_group(self) -> QGroupBox:
        group = QGroupBox("Filter")
        form = QFormLayout(group)

        self.rating_combo = QComboBox()
        for label, value in _RATING_CHOICES:
            self.rating_combo.addItem(label, value)
        self.rating_combo.currentIndexChanged.connect(lambda *_: self._emit_filter())
        form.addRow("Rating", self.rating_combo)

        self.flag_combo = QComboBox()
        for label, value in _FLAG_CHOICES:
            self.flag_combo.addItem(label, value)
        self.flag_combo.currentIndexChanged.connect(lambda *_: self._emit_filter())
        form.addRow("Flag", self.flag_combo)

        self.label_combo = QComboBox()
        self.label_combo.addItem(_ANY, None)
        for color in COLOR_LABELS:
            self.label_combo.addItem(color.capitalize(), color)
        self.label_combo.currentIndexChanged.connect(lambda *_: self._emit_filter())
        form.addRow("Colour", self.label_combo)

        return group

    # ---------- state ----------

    def set_folders(self, folders: list[Folder], directories: list[str] | None = None) -> None:
        """Rebuild the folder tree, restoring the previous selection where possible.

        `directories` are the directories that actually contain photos; the tree shows
        each catalogued folder as a root with its subfolders nested beneath.
        """
        previously_selected = self.current_directory()
        previous_folder_id = self.current_folder_id()

        self.folder_tree.blockSignals(True)
        self.folder_tree.clear()

        everything = QTreeWidgetItem([_ALL_FOLDERS])
        everything.setData(0, Qt.ItemDataRole.UserRole, (None, None))
        self.folder_tree.addTopLevelItem(everything)

        for folder in folders:
            root = QTreeWidgetItem([Path(folder.path).name or folder.path])
            root.setData(0, Qt.ItemDataRole.UserRole, (folder.id, folder.path))
            root.setToolTip(0, folder.path)
            self.folder_tree.addTopLevelItem(root)
            _build_subtree(root, folder, directories or [])
            # Nodes are created parent-before-child, so a folder that holds only
            # subfolders (no photos of its own) is appended after its siblings.
            # Sort every level so the tree reads alphabetically regardless.
            _sort_recursively(root)
            root.setExpanded(True)

        self.folder_tree.setCurrentItem(everything)
        restored = self._find_item(previously_selected, previous_folder_id)
        if restored is not None:
            self.folder_tree.setCurrentItem(restored)
        self.folder_tree.blockSignals(False)

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(text)

    def _current_selection(self) -> tuple[int | None, str | None]:
        item = self.folder_tree.currentItem()
        if item is None:
            return (None, None)
        return item.data(0, Qt.ItemDataRole.UserRole) or (None, None)

    def current_folder_id(self) -> int | None:
        return self._current_selection()[0]

    def current_directory(self) -> str | None:
        return self._current_selection()[1]

    def current_filter(self) -> PhotoFilter:
        folder_id, directory = self._current_selection()
        return PhotoFilter(
            folder_id=folder_id,
            # A directory already implies its folder, and it narrows further, so the
            # directory alone drives the query once a subfolder is picked.
            directory=directory,
            min_rating=self.rating_combo.currentData(),
            flag=self.flag_combo.currentData(),
            color_label=self.label_combo.currentData(),
        )

    def _find_item(self, directory: str | None, folder_id: int | None) -> QTreeWidgetItem | None:
        if directory is None and folder_id is None:
            return None
        for item in self.folder_tree.findItems("", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive):
            item_folder_id, item_directory = item.data(0, Qt.ItemDataRole.UserRole) or (None, None)
            if directory is not None and item_directory == directory:
                return item
            if directory is None and item_folder_id == folder_id:
                return item
        return None

    # ---------- internals ----------

    def _emit_filter(self) -> None:
        self.filter_changed.emit(self.current_filter())

    def _request_remove_folder(self) -> None:
        folder_id = self.current_folder_id()
        if folder_id is not None:
            self.remove_folder_requested.emit(folder_id)


def _sort_recursively(item: QTreeWidgetItem) -> None:
    item.sortChildren(0, Qt.SortOrder.AscendingOrder)
    for row in range(item.childCount()):
        _sort_recursively(item.child(row))


def _build_subtree(root_item: QTreeWidgetItem, folder: Folder, directories: list[str]) -> None:
    """Nest each directory under its catalogued root, creating intermediate nodes."""
    root_path = Path(folder.path)
    nodes: dict[Path, QTreeWidgetItem] = {root_path: root_item}

    relevant = []
    for directory in directories:
        candidate = Path(directory)
        if candidate == root_path:
            continue
        try:
            candidate.relative_to(root_path)
        except ValueError:
            continue  # belongs to a different catalogued folder
        relevant.append(candidate)

    # Shallowest first, so a parent node always exists before its children.
    for directory in sorted(relevant, key=lambda p: (len(p.parts), str(p).lower())):
        for ancestor in list(reversed(directory.parents)) + [directory]:
            if ancestor in nodes or root_path not in ancestor.parents:
                continue
            parent_item = nodes.get(ancestor.parent, root_item)
            node = QTreeWidgetItem([ancestor.name])
            node.setData(0, Qt.ItemDataRole.UserRole, (folder.id, str(ancestor)))
            node.setToolTip(0, str(ancestor))
            parent_item.addChild(node)
            nodes[ancestor] = node
