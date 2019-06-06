from pathlib import Path
from typing import cast, Dict, List, Set, Tuple

from PyQt5 import QtGui, QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import QPushButton

from .details_view import DetailsBox
from .file_tree_view import DirectoryTree
from .shared import PATH, TAGS, TAGSTATE, VISIBLE_TAGS
from .tag_list import TagListWidget, TagListWidgetItem, TagState


class SortButton(QtWidgets.QPushButton):
    def __init__(self, text: str, parent: QtWidgets.QWidget) -> None:
        super().__init__(text, parent)
        self.reversed = False

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.RightButton:
            self.reversed = not self.reversed
            self.setText(self.text()[::-1])
        elif event.button() == Qt.LeftButton:
            self.setChecked(True)
        cast(pyqtSignal, self.pressed).emit()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        return


class SideBar(QtWidgets.QWidget):
    tag_selected = QtCore.pyqtSignal(str)

    def __init__(self, paths: Set[Path], parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter between tabs and info
        self.splitter = QtWidgets.QSplitter(Qt.Vertical, self)
        layout.addWidget(self.splitter)

        # Tab widget
        self.tab_widget = QtWidgets.QTabWidget(self)
        self.tab_widget.setFocusPolicy(Qt.NoFocus)
        self.splitter.addWidget(self.tab_widget)
        self.splitter.setStretchFactor(0, 1)

        # Tag list box
        tag_list_box = QtWidgets.QWidget(self.tab_widget)
        tag_list_box.setObjectName('tag_list_box')
        tag_list_box_layout = QtWidgets.QVBoxLayout(tag_list_box)
        tag_list_box_layout.setContentsMargins(0, 0, 0, 0)
        tag_list_box_layout.setSpacing(0)
        self.tab_widget.addTab(tag_list_box, 'Tags')

        # Tag list buttons
        tag_buttons_hbox = QtWidgets.QHBoxLayout()
        tag_buttons_hbox.setContentsMargins(0, 0, 0, 0)
        tag_list_box_layout.addLayout(tag_buttons_hbox)
        clear_button = QPushButton('Clear tags', tag_list_box)
        clear_button.setObjectName('clear_button')
        sort_buttons = QtWidgets.QButtonGroup(tag_list_box)
        sort_buttons.setExclusive(True)
        sort_alpha_button = SortButton('a-z', tag_list_box)
        sort_alpha_button.setObjectName('sort_button')
        sort_alpha_button.setCheckable(True)
        sort_alpha_button.setChecked(True)
        sort_count_button = SortButton('0-9', tag_list_box)
        sort_count_button.setObjectName('sort_button')
        sort_count_button.setCheckable(True)
        sort_buttons.addButton(sort_alpha_button)
        sort_buttons.addButton(sort_count_button)

        tag_buttons_hbox.addWidget(clear_button)
        tag_buttons_hbox.addStretch()
        tag_buttons_hbox.addWidget(sort_alpha_button)
        tag_buttons_hbox.addWidget(sort_count_button)

        # Tag list
        self.tag_list = TagListWidget(tag_list_box)
        self.tag_list.setObjectName('tag_list')
        self.tag_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.tag_list.setFocusPolicy(Qt.NoFocus)
        tag_list_box_layout.addWidget(self.tag_list)

        def sort_button_pressed(button: SortButton) -> None:
            if not button.isChecked():
                return
            self.tag_list.sort_by_alpha = (button == sort_alpha_button)
            self.tag_list.sortItems(Qt.DescendingOrder
                                    if button.reversed else Qt.AscendingOrder)

        cast(pyqtSignal, sort_alpha_button.pressed).connect(
            lambda: sort_button_pressed(sort_alpha_button))
        cast(pyqtSignal, sort_count_button.pressed).connect(
            lambda: sort_button_pressed(sort_count_button))
        self.sort_alpha_button = sort_alpha_button
        self.sort_count_button = sort_count_button

        def clear_tag_filters() -> None:
            for tag in self.tag_list:
                tag.setData(TAGSTATE, TagState.DEFAULT)
            self.tag_list.tag_state_updated.emit()

        cast(pyqtSignal, clear_button.clicked).connect(clear_tag_filters)

        # Files tab
        self.dir_tree = DirectoryTree(paths, self)
        self.tab_widget.addTab(self.dir_tree, 'Files')

        # Dates tab
        self.tab_widget.addTab(QtWidgets.QLabel('todo'), 'Dates')

        # Info widget
        self.info_box = DetailsBox(self)
        self.splitter.addWidget(self.info_box)
        self.splitter.setStretchFactor(1, 0)

        # Buttons at the bottom
        bottom_row = QtWidgets.QHBoxLayout()
        self.settings_button = QtWidgets.QPushButton('Settings', self)
        bottom_row.addWidget(self.settings_button)
        self.reload_button = QtWidgets.QPushButton('Reload', self)
        bottom_row.addWidget(self.reload_button)
        layout.addLayout(bottom_row)

    @staticmethod
    def _tag_format(tag: str, visible: int, total: int) -> str:
        return f'{tag or "<Untagged>"}   ({visible}/{total})'

    def create_tag(self, tag: str, count: int) -> None:
        item = TagListWidgetItem(self._tag_format(tag, count, count))
        item.setData(PATH, tag)
        item.setData(TAGS, count)
        item.setData(VISIBLE_TAGS, count)
        item.setData(TAGSTATE, TagState.DEFAULT)
        self.tag_list.addItem(item)

    def set_tags(self, tags: List[Tuple[str, int]]) -> None:
        self.tag_list.clear()
        for tag, count in tags:
            self.create_tag(tag, count)
        untagged = self.tag_list.takeItem(0)
        self.tag_list.insertItem(0, untagged)
        self.sort_tags()

    def sort_tags(self) -> None:
        if self.sort_alpha_button.isChecked():
            button = self.sort_alpha_button
        else:
            button = self.sort_count_button
        self.tag_list.sortItems(Qt.DescendingOrder
                                if button.reversed else Qt.AscendingOrder)

    def update_tags(self, tag_count: Dict[str, int]) -> None:
        for item in self.tag_list:
            tag = item.data(PATH)
            new_count = tag_count[tag]
            item.setData(VISIBLE_TAGS, new_count)
            item.setText(self._tag_format(tag, new_count, item.data(TAGS)))
