from pathlib import Path
from typing import cast, Iterable, Set

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QDialogButtonBox

from .shared import CACHE


class SettingsWindow(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget,
                 paths: Iterable[Path]) -> None:
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.reset_thumbnails = False

        # Layout
        layout = QtWidgets.QVBoxLayout(self)
        self.heading_label = QtWidgets.QLabel('Image directories')
        self.heading_label.setObjectName('dialog_heading')
        layout.addWidget(self.heading_label)

        # Directory buttons
        hbox = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton('Add directory...', self)
        cast(pyqtSignal, self.add_button.clicked).connect(self.add_directory)
        hbox.addWidget(self.add_button)
        self.remove_button = QtWidgets.QPushButton('Remove directory', self)
        self.remove_button.setEnabled(False)
        cast(pyqtSignal, self.remove_button.clicked
             ).connect(self.remove_directories)
        hbox.addWidget(self.remove_button)
        layout.addLayout(hbox)

        # Path list
        self.path_list = QtWidgets.QListWidget(self)
        self.path_list.setSortingEnabled(True)
        self.path_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.paths = paths
        layout.addWidget(self.path_list)

        # Clear cache (not thumbnails)
        def clear_cache() -> None:
            msg = ('Are you sure you want to remove the cache? This will not '
                   'reset any thumbnails, only the file information.')
            reply = QtWidgets.QMessageBox.question(self, 'Clear cache', msg)
            if reply:
                CACHE.unlink()

        self.clear_cache_button = QtWidgets.QPushButton('Clear cache', self)
        cast(pyqtSignal, self.clear_cache_button.clicked).connect(clear_cache)
        layout.addWidget(self.clear_cache_button)

        # Regenerate thumbnails
        def regenerate_thumbnails() -> None:
            msg = ('Are you sure you want to regenerate the thumbnails? '
                   'Only the ones loaded right now will be affected.')
            reply = QtWidgets.QMessageBox.question(
                self, 'Regenerate thumbnails', msg)
            if reply:
                self.reset_thumbnails = True

        self.regen_thumbnails_button = QtWidgets.QPushButton(
            'Regenerate thumbnails', self)
        cast(pyqtSignal, self.regen_thumbnails_button.clicked
             ).connect(regenerate_thumbnails)
        layout.addWidget(self.regen_thumbnails_button)

        # Action buttons
        layout.addSpacing(10)
        btm_buttons = QDialogButtonBox(QDialogButtonBox.Cancel
                                       | QDialogButtonBox.Save)
        layout.addWidget(btm_buttons)
        cast(pyqtSignal, btm_buttons.accepted).connect(self.accept)
        cast(pyqtSignal, btm_buttons.rejected).connect(self.reject)

        def on_selection_change() -> None:
            self.remove_button.setEnabled(
                bool(self.path_list.selectedItems()))
        cast(pyqtSignal, self.path_list.itemSelectionChanged
             ).connect(on_selection_change)

    @property
    def paths(self) -> Set[Path]:
        out = set()
        for i in range(self.path_list.count()):
            out.add(Path(self.path_list.item(i).text()))
        return out

    @paths.setter
    def paths(self, paths: Iterable[Path]) -> None:
        self.path_list.clear()
        self.path_list.addItems(sorted(str(p) for p in paths))

    def add_directory(self) -> None:
        roots = QtCore.QStandardPaths.standardLocations(
            QtCore.QStandardPaths.PicturesLocation)
        root = roots[0] if roots else str(Path.home())
        new_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Choose a directory', root)
        if new_dir:
            self.path_list.addItem(new_dir)

    def remove_directories(self) -> None:
        for item in self.path_list.selectedItems():
            self.path_list.takeItem(self.path_list.row(item))
