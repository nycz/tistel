import enum
from typing import Optional, Set, cast

from libsyntyche.widgets import mk_signal0, mk_signal1
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtProperty  # type: ignore
from PyQt5.QtGui import QColor

from .shared import HOVERING, PATH, TAGS, TAGSTATE, VISIBLE_TAGS, ListWidget


class TagState(enum.Enum):
    WHITELISTED = enum.auto()
    BLACKLISTED = enum.auto()
    DEFAULT = enum.auto()


class TagListDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter: QtGui.QPainter,
              option: QtWidgets.QStyleOptionViewItem,
              index: QtCore.QModelIndex) -> None:
        parent: 'TagListWidget' = option.styleObject
        tag = index.data(PATH)
        painter.setRenderHints(QtGui.QPainter.Antialiasing)
        dot_width = 10
        padding = (option.rect.height() - option.fontMetrics.height()) // 2
        rect = option.rect.adjusted(padding + dot_width, padding,
                                    -padding, -padding)
        if tag in parent.selected_item_tags:
            painter.fillRect(option.rect, QtGui.QColor(255, 255, 150, 10))
        state = index.data(TAGSTATE)
        colors = {TagState.WHITELISTED: parent.property('whitelisted_color'),
                  TagState.DEFAULT: parent.property('default_color'),
                  TagState.BLACKLISTED: parent.property('blacklisted_color')}
        color = colors[state]
        font = option.font
        font.setBold(False)
        font.setItalic(False)
        count = index.data(TAGS)
        visible_count = index.data(VISIBLE_TAGS)
        hovering = index.data(HOVERING)
        if hovering:
            painter.fillRect(option.rect, QColor(255, 255, 255, 20))
        if (count == 0 or visible_count == 0) \
                and state != TagState.BLACKLISTED:
            color.setAlphaF(0.4)
            font.setItalic(True)
        if state != TagState.DEFAULT:
            font.setBold(True)
        elif font.bold():
            font.setBold(False)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(rect, Qt.TextSingleLine, tag or '<Untagged>')
        painter.drawText(rect, Qt.AlignRight | Qt.TextSingleLine,
                         f'{visible_count} / {count}')
        if tag in parent.selected_item_tags:
            pen = QtGui.QPen()
            pen.setWidth(0)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor('#ffffcc'))
            painter.drawEllipse(
                QtCore.QPoint(padding + dot_width // 2,
                              option.rect.top() + option.rect.height() // 2),
                3, 3)


class TagListWidget(ListWidget):
    tag_state_updated = mk_signal0()

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.selected_item_tags: Set[str] = set()
        self._default_color = QColor(Qt.white)
        self._whitelisted_color = QColor(Qt.green)
        self._blacklisted_color = QColor(Qt.red)
        self.sort_func = sort_tag_list_by_alpha
        self.setItemDelegate(TagListDelegate(self))
        self.setMouseTracking(True)
        self.last_item: Optional[QtWidgets.QListWidgetItem] = None

    def set_current_thumb(self, current: Optional[QtGui.QStandardItem],
                          previous: Optional[QtGui.QStandardItem]) -> None:
        if current is not None:
            self.selected_item_tags = current.data(TAGS)
            self.update()

    def clear(self) -> None:
        self.last_item = None
        super().clear()

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
        item = self.itemAt(event.pos())
        if self.last_item != item:
            if item is not None:
                self.setCursor(Qt.PointingHandCursor)
                item.setData(HOVERING, True)
            else:
                self.setCursor(Qt.ArrowCursor)
            if self.last_item is not None:
                self.last_item.setData(HOVERING, False)
            self.last_item = item

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        if self.last_item is not None:
            self.last_item.setData(HOVERING, False)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        super().enterEvent(event)
        if self.last_item is not None:
            self.last_item.setData(HOVERING, False)
        item = self.itemAt(cast(QtGui.QEnterEvent, event).pos())
        if item is not None:
            self.setCursor(Qt.PointingHandCursor)
            item.setData(HOVERING, True)
        self.last_item = item

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
                self.tag_state_updated.emit()


def sort_tag_list_by_alpha(a: QtWidgets.QListWidgetItem,
                           b: QtWidgets.QListWidgetItem) -> bool:
    a_data = (a.data(PATH).lower(), a.data(TAGS))
    b_data = (b.data(PATH).lower(), b.data(TAGS))
    return a_data < b_data


def sort_tag_list_by_tags(a: QtWidgets.QListWidgetItem,
                          b: QtWidgets.QListWidgetItem) -> bool:
    a_data = (a.data(TAGS), a.data(PATH).lower())
    b_data = (b.data(TAGS), b.data(PATH).lower())
    return a_data < b_data
