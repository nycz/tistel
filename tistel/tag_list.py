import enum
from typing import Optional

from PyQt5 import QtGui, QtCore, QtWidgets
from PyQt5.QtCore import pyqtProperty, Qt
from PyQt5.QtGui import QColor

from .shared import ListWidget, TAGS, TAGSTATE, VISIBLE_TAGS


class TagState(enum.Enum):
    WHITELISTED = enum.auto()
    BLACKLISTED = enum.auto()
    DEFAULT = enum.auto()


class TagListWidget(ListWidget):
    tag_state_updated = QtCore.pyqtSignal()
    tag_blacklisted = QtCore.pyqtSignal(str)
    tag_whitelisted = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self._default_color = QColor(Qt.white)
        self._whitelisted_color = QColor(Qt.green)
        self._blacklisted_color = QColor(Qt.red)

    @pyqtProperty(QColor)
    def default_color(self) -> QColor:
        return self._default_color

    @default_color.setter  # type: ignore
    def default_color(self, color: QColor) -> None:
        self._default_color = color

    @pyqtProperty(QColor)
    def whitelisted_color(self) -> QColor:
        return self._whitelisted_color

    @whitelisted_color.setter  # type: ignore
    def whitelisted_color(self, color: QColor) -> None:
        self._whitelisted_color = color

    @pyqtProperty(QColor)
    def blacklisted_color(self) -> QColor:
        return self._blacklisted_color

    @blacklisted_color.setter  # type: ignore
    def blacklisted_color(self, color: QColor) -> None:
        self._blacklisted_color = color

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        return

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.pos())
        if item is not None:
            new_state: Optional[TagState] = None
            state = item.data(TAGSTATE)
            if event.button() == Qt.LeftButton:
                if state == TagState.DEFAULT:
                    new_state = TagState.WHITELISTED
                else:
                    new_state = TagState.DEFAULT
            elif event.button() == Qt.RightButton:
                if state == TagState.DEFAULT:
                    new_state = TagState.BLACKLISTED
                else:
                    new_state = TagState.DEFAULT
            if new_state is not None:
                item.setData(TAGSTATE, new_state)
                update_looks(item)
                self.tag_state_updated.emit()


class TagListWidgetItem(QtWidgets.QListWidgetItem):
    def __lt__(self, other: QtWidgets.QListWidgetItem) -> bool:
        result: bool = self.data(TAGS) < other.data(TAGS)
        return result


def update_looks(tag_item: QtWidgets.QListWidgetItem) -> None:
    count = tag_item.data(TAGS)
    visible_count = tag_item.data(VISIBLE_TAGS)
    state = tag_item.data(TAGSTATE)
    parent = tag_item.listWidget()
    colors = {TagState.WHITELISTED: parent.property('whitelisted_color'),
              TagState.DEFAULT: parent.property('default_color'),
              TagState.BLACKLISTED: parent.property('blacklisted_color')}
    color = colors[state]
    font = tag_item.font()
    if (count == 0 or visible_count == 0) \
            and state != TagState.BLACKLISTED:
        color.setAlphaF(0.4)
        if not tag_item.font().italic():
            font.setItalic(True)
    elif tag_item.font().italic():
        font.setItalic(False)
    if state != TagState.DEFAULT:
        font.setBold(True)
    elif font.bold():
        font.setBold(False)
    tag_item.setFont(font)
    tag_item.setForeground(color)
