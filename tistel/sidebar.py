from typing import Dict, List, Tuple, cast

from libsyntyche.widgets import Signal0, Signal2, mk_signal1
from PyQt5 import QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QPushButton

from .file_tree_view import DirectoryTree
from .settings import Settings
from .shared import (PATH, TAG_COUNT, TAG_NAME, TAG_STATE, VISIBLE_TAG_COUNT,
                     TagState, make_svg_icon)
from .tag_list import TagListContainer


class SideBar(QtWidgets.QWidget):
    def __init__(self, config: Settings, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Tab bar
        tab_bar_grid = QtWidgets.QGridLayout()
        layout.addLayout(tab_bar_grid)
        self.tab_bar_buttons = QtWidgets.QButtonGroup()
        self.tab_bar_buttons.setExclusive(True)

        # Tab content stack
        stack = QtWidgets.QStackedLayout()
        layout.addLayout(stack)

        def select_tab(tab_id: int, checked: bool) -> None:
            if checked:
                stack.setCurrentIndex(tab_id)
        cast(Signal2[int, bool], self.tab_bar_buttons.idToggled).connect(select_tab)

        # Tag list box
        self.tag_list = TagListContainer(self)
        tag_list_button = QtWidgets.QPushButton()
        tag_list_button.setIcon(make_svg_icon('tag', 18, Qt.black))
        tag_list_button.setCheckable(True)
        tag_list_button.setChecked(True)
        tag_list_button.setToolTip('Tags')
        tag_list_button.setFocusPolicy(Qt.NoFocus)
        tab_bar_grid.addWidget(tag_list_button, 0, 0)
        self.tab_bar_buttons.addButton(tag_list_button, 0)
        stack.addWidget(self.tag_list)

        # Files tab
        self.dir_tree = DirectoryTree(config.active_paths, self)
        files_button = QtWidgets.QPushButton()
        files_button.setIcon(make_svg_icon('folder', 18, Qt.black))
        files_button.setCheckable(True)
        files_button.setToolTip('Files')
        files_button.setFocusPolicy(Qt.NoFocus)
        tab_bar_grid.addWidget(files_button, 0, 1)
        self.tab_bar_buttons.addButton(files_button, 1)
        stack.addWidget(self.dir_tree)

        # Buttons at the bottom
        bottom_row = QtWidgets.QHBoxLayout()
        self.settings_button = QtWidgets.QPushButton('Settings', self)
        bottom_row.addWidget(self.settings_button)
        self.reload_button = QtWidgets.QPushButton('Reload', self)
        bottom_row.addWidget(self.reload_button)
        layout.addLayout(bottom_row)
