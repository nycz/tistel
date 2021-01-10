import json
from pathlib import Path
from typing import cast, List, Optional, Set, Type, TypeVar

from libsyntyche.widgets import Signal0, Signal1
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialogButtonBox

from .shared import CONFIG


T = TypeVar('T', bound='Settings')


class Settings:
    _PATHS_KEY = 'directories'
    _SHOW_NAMES_KEY = 'show_names'
    _MAIN_SPLITTER_KEY = 'main_splitter'
    _SIDE_SPLITTER_KEY = 'side_splitter'

    def __init__(self) -> None:
        self.path_overrides: Set[Path] = set()
        self.paths: Set[Path] = set()
        self.show_names = True
        self.main_splitter: Optional[List[int]] = None
        self.side_splitter: Optional[List[int]] = None

    @property
    def active_paths(self) -> Set[Path]:
        return (self.path_overrides or self.paths).copy()

    def copy(self: T) -> T:
        clone = self.__class__()
        clone.path_overrides = self.path_overrides.copy()
        clone.paths = self.paths.copy()
        clone.show_names = self.show_names
        clone.main_splitter = self.main_splitter
        clone.side_splitter = self.side_splitter
        return clone

    def save(self) -> None:
        data = {
            self._PATHS_KEY: sorted(str(p) for p in self.paths),
            self._SHOW_NAMES_KEY: self.show_names,
            self._MAIN_SPLITTER_KEY: self.main_splitter,
            self._SIDE_SPLITTER_KEY: self.side_splitter,
        }
        json_data = json.dumps(data, indent=2)
        CONFIG.write_text(json_data)

    def update(self: T, other: T) -> None:
        self.show_names = other.show_names
        self.main_splitter = other.main_splitter
        self.side_splitter = other.side_splitter
        # Do this just in case some bozo has refs of these
        self.path_overrides.clear()
        self.path_overrides.update(other.path_overrides)
        self.paths.clear()
        self.paths.update(other.paths)

    @classmethod
    def load(cls: Type[T], path_overrides: Optional[List[Path]]) -> T:
        if not CONFIG.exists():
            if not CONFIG.parent.exists():
                CONFIG.parent.mkdir(parents=True)
            default_config = cls()
            default_config.save()
            config = default_config
        else:
            config_data = json.loads(CONFIG.read_text())
            config = cls()
            if cls._PATHS_KEY in config_data:
                config.paths = {Path(p).expanduser()
                                for p in config_data[cls._PATHS_KEY]}
            if cls._SHOW_NAMES_KEY in config_data:
                config.show_names = config_data[cls._SHOW_NAMES_KEY]
            if cls._MAIN_SPLITTER_KEY in config_data:
                config.main_splitter = config_data[cls._MAIN_SPLITTER_KEY]
            if cls._SIDE_SPLITTER_KEY in config_data:
                config.side_splitter = config_data[cls._SIDE_SPLITTER_KEY]
        if path_overrides is not None:
            config.path_overrides = {p.resolve() for p in path_overrides}
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

        # Path override notice
        self.path_override_label = QtWidgets.QLabel(
            'Tistel was loaded with custom paths! These can\'t be modified.')
        dirbox_layout.addWidget(self.path_override_label)

        # Directory buttons
        hbox = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton('Add directory...', self)
        cast(Signal0, self.add_button.clicked).connect(self.add_directory)
        hbox.addWidget(self.add_button)
        self.remove_button = QtWidgets.QPushButton('Remove directory', self)
        self.remove_button.setEnabled(False)
        cast(Signal0, self.remove_button.clicked).connect(self.remove_directories)
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
                reply = QtWidgets.QMessageBox.question(self, 'Clear cache', msg)
                if reply != QtWidgets.QMessageBox.Yes:
                    self.clear_cache_checkbox.setCheckState(Qt.Unchecked)

        cast(Signal1[int], self.clear_cache_checkbox.stateChanged).connect(clear_cache)
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

        cast(Signal1[int], self.regen_thumbnails_checkbox.stateChanged
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
        cast(Signal1[int], self.show_names_checkbox.stateChanged
             ).connect(update_show_names)
        miscbox_layout.addWidget(self.show_names_checkbox)

        # Action buttons
        layout.addSpacing(10)
        btm_buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        layout.addWidget(btm_buttons)
        cast(Signal0, btm_buttons.accepted).connect(self.accept)
        cast(Signal0, btm_buttons.rejected).connect(self.reject)

        def on_selection_change() -> None:
            self.remove_button.setEnabled(
                bool(self.path_list.selectedItems()))
        cast(Signal0, self.path_list.itemSelectionChanged
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
        self.path_list.addItems(sorted(str(p) for p in config.active_paths))
        # Reset action flags
        self.clear_cache_checkbox.setCheckState(Qt.Unchecked)
        self.regen_thumbnails_checkbox.setCheckState(Qt.Unchecked)
        # Custom paths can't be changed (for now)
        if self.config.path_overrides:
            self.add_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            self.path_list.setEnabled(False)
            self.path_override_label.show()
        else:
            self.add_button.setEnabled(True)
            self.remove_button.setEnabled(True)
            self.path_list.setEnabled(True)
            self.path_override_label.hide()

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
