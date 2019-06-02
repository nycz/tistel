import json
from pathlib import Path
from typing import Any, cast, Dict, Iterable, List, Set, Type, TypeVar

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import QDialogButtonBox

from .shared import CACHE, CONFIG


T = TypeVar('T', bound='Settings')


class Settings:
    _PATHS_KEY = 'directories'
    _SHOW_NAMES_KEY = 'show_names'

    def __init__(self) -> None:
        self.paths: Set[Path] = set()
        self.show_names = True

    def copy(self: T) -> T:
        clone = self.__class__()
        clone.paths = self.paths.copy()
        clone.show_names = self.show_names
        return clone

    def save(self) -> None:
        data = {
            self._PATHS_KEY: sorted(str(p) for p in self.paths),
            self._SHOW_NAMES_KEY: self.show_names,
        }
        json_data = json.dumps(data, indent=2)
        CONFIG.write_text(json_data)

    @classmethod
    def load(cls: Type[T]) -> T:
        if not CONFIG.exists():
            if not CONFIG.parent.exists():
                CONFIG.parent.mkdir(parents=True)
            default_config = cls()
            default_config.save()
            return default_config
        else:
            config_data = json.loads(CONFIG.read_text())
            config = cls()
            if cls._PATHS_KEY in config_data:
                config.paths = {Path(p).expanduser()
                                for p in config_data[cls._PATHS_KEY]}
            if cls._SHOW_NAMES_KEY in config_data:
                config.show_names = config_data[cls._SHOW_NAMES_KEY]
            return config


class SettingsWindow(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.config: Settings
        self.setWindowTitle('Settings')

        # Layout
        layout = QtWidgets.QVBoxLayout(self)
        directories_box = QtWidgets.QGroupBox('Image directories', self)
        dirbox_layout = QtWidgets.QVBoxLayout(directories_box)
        layout.addWidget(directories_box)

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
        dirbox_layout.addLayout(hbox)

        # Path list
        self.path_list = QtWidgets.QListWidget(self)
        self.path_list.setSortingEnabled(True)
        self.path_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        dirbox_layout.addWidget(self.path_list)

        # Cache box
        cache_box = QtWidgets.QGroupBox('Cached data', self)
        cachebox_layout = QtWidgets.QVBoxLayout(cache_box)
        cachebox_layout.addWidget(QtWidgets.QLabel(
            'Note: no changes will take effect if you close the settings '
            'window without saving.'))
        layout.addWidget(cache_box)

        # Clear cache (not thumbnails)
        self.clear_cache_checkbox = QtWidgets.QCheckBox('Clear cache', self)

        def clear_cache(new_state: int) -> None:
            if new_state == Qt.Checked:
                msg = ('Are you sure you want to remove the cache? This will '
                       'not reset any thumbnails, only the file information.')
                reply = QtWidgets.QMessageBox.question(self, 'Clear cache',
                                                       msg)
                if reply != QtWidgets.QMessageBox.Yes:
                    self.clear_cache_checkbox.setCheckState(Qt.Unchecked)

        cast(pyqtSignal, self.clear_cache_checkbox.stateChanged
             ).connect(clear_cache)
        cachebox_layout.addWidget(self.clear_cache_checkbox)

        # Regenerate thumbnails
        self.regen_thumbnails_checkbox = QtWidgets.QCheckBox(
            'Regenerate thumbnails', self)

        def regenerate_thumbnails(new_state: int) -> None:
            if new_state == Qt.Checked:
                msg = ('Are you sure you want to regenerate the thumbnails? '
                       'Only the ones loaded right now will be affected.')
                reply = QtWidgets.QMessageBox.question(
                    self, 'Regenerate thumbnails', msg)
                if reply != QtWidgets.QMessageBox.Yes:
                    self.regen_thumbnails_checkbox.setCheckState(Qt.Unchecked)

        cast(pyqtSignal, self.regen_thumbnails_checkbox.stateChanged
             ).connect(regenerate_thumbnails)
        cachebox_layout.addWidget(self.regen_thumbnails_checkbox)

        # Misc settings
        misc_box = QtWidgets.QGroupBox('Miscellaneous settings', self)
        miscbox_layout = QtWidgets.QVBoxLayout(misc_box)
        layout.addWidget(misc_box)

        # Show names
        def update_show_names(new_state: int) -> None:
            if new_state == Qt.Checked:
                self.config.show_names = True
            elif new_state == Qt.Unchecked:
                self.config.show_names = False
        self.show_names_checkbox = QtWidgets.QCheckBox(
            'Show names in thumbnail view', self)
        cast(pyqtSignal, self.show_names_checkbox.stateChanged
             ).connect(update_show_names)
        miscbox_layout.addWidget(self.show_names_checkbox)

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
    def clear_cache(self) -> bool:
        return self.clear_cache_checkbox.checkState() == Qt.Checked

    @property
    def reset_thumbnails(self) -> bool:
        return self.regen_thumbnails_checkbox.checkState() == Qt.Checked

    def set_up(self, config: Settings) -> None:
        self.config = config.copy()
        self.show_names_checkbox.setCheckState(
            Qt.Checked if self.config.show_names else Qt.Unchecked)
        self.path_list.clear()
        self.path_list.addItems(sorted(str(p) for p in config.paths))
        # Reset action flags
        self.clear_cache_checkbox.setCheckState(Qt.Unchecked)
        self.regen_thumbnails_checkbox.setCheckState(Qt.Unchecked)

    def add_directory(self) -> None:
        roots = QtCore.QStandardPaths.standardLocations(
            QtCore.QStandardPaths.PicturesLocation)
        root = roots[0] if roots else str(Path.home())
        new_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Choose a directory', root)
        if new_dir:
            self.path_list.addItem(new_dir)
            self.config.paths.add(Path(new_dir))

    def remove_directories(self) -> None:
        for item in self.path_list.selectedItems():
            self.path_list.takeItem(self.path_list.row(item))
            self.config.paths.remove(Path(item.text()))
