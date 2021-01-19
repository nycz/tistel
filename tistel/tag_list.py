import enum
from typing import Optional, Set, cast

from libsyntyche.widgets import mk_signal0, mk_signal1
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtProperty  # type: ignore
from PyQt5.QtGui import QColor

from . import shared
from .shared import (HOVERING, PATH, TAGS, TAG_COUNT, TAG_NAME, TAG_STATE,
                     VISIBLE_TAG_COUNT, ListWidget2, TagState)
from .thumb_view import ThumbViewItem


class TagListDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter: QtGui.QPainter,
              option: QtWidgets.QStyleOptionViewItem,
              index: QtCore.QModelIndex) -> None:
        parent = cast(TagListWidget, option.styleObject)
        item = parent.itemFromIndex(index)
        tag = item.get_tag_name()
        painter.setRenderHints(QtGui.QPainter.Antialiasing)
        dot_width = 10
        padding = (option.rect.height() - option.fontMetrics.height()) // 2
        rect = option.rect.adjusted(padding + dot_width, padding, -padding, -padding)
        if tag in parent.selected_item_tags:
            painter.fillRect(option.rect, QColor(255, 255, 150, 10))
        state = item.get_tag_state()
        colors = {TagState.WHITELISTED: cast(QColor, parent.whitelisted_color),
                  TagState.DEFAULT: cast(QColor, parent.default_color),
                  TagState.BLACKLISTED: cast(QColor, parent.blacklisted_color)}
        color = colors[state]
        font = option.font
        font.setBold(False)
        font.setItalic(False)
        count = item.get_tag_count()
        visible_count = item.get_visible_tag_count()
        hovering = item.is_hovering()
        if hovering:
            painter.fillRect(option.rect, QColor(255, 255, 255, 20))
        if (count == 0 or visible_count == 0) and state != TagState.BLACKLISTED:
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


class TagListItem(QtGui.QStandardItem):
    def get_tag_count(self) -> int:
        return cast(int, self.data(shared.TAG_COUNT))

    def get_tag_name(self) -> str:
        return cast(str, self.data(shared.TAG_NAME))

    def get_tag_state(self) -> TagState:
        return cast(TagState, self.data(shared.TAG_STATE))

    def get_visible_tag_count(self) -> int:
        return cast(int, self.data(shared.VISIBLE_TAG_COUNT))

    def is_hovering(self) -> bool:
        return cast(bool, self.data(shared.HOVERING))

    def set_hovering(self, hovering: bool) -> None:
        self.setData(hovering, shared.HOVERING)

    def set_tag_count(self, tag_count: int) -> None:
        self.setData(tag_count, shared.TAG_COUNT)

    def set_tag_name(self, tag_name: str) -> None:
        self.setData(tag_name, shared.TAG_NAME)

    def set_tag_state(self, tag_state: TagState) -> None:
        self.setData(tag_state, shared.TAG_STATE)

    def set_visible_tag_count(self, visible_tag_count: int) -> None:
        self.setData(visible_tag_count, shared.VISIBLE_TAG_COUNT)


class TagListWidget(ListWidget2[TagListItem]):
    tag_state_updated = mk_signal0()

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.selected_item_tags: Set[str] = set()
        self._default_color = QColor(Qt.white)
        self._whitelisted_color = QColor(Qt.green)
        self._blacklisted_color = QColor(Qt.red)
        # self.sort_func = sort_tag_list_by_alpha
        self.setItemDelegate(TagListDelegate(self))
        self.setMouseTracking(True)
        self.last_item: Optional[TagListItem] = None

    def set_current_thumb(self, current: Optional[ThumbViewItem],
                          previous: Optional[ThumbViewItem]) -> None:
        if current is not None:
            self.selected_item_tags = current.get_tags()
            self.update()

    def clear(self) -> None:
        self.last_item = None
        super().clear()

    @pyqtProperty(QColor)
    def default_color(self) -> QColor:
        return QColor(self._default_color)

    @default_color.setter  # type: ignore
    def default_color(self, color: QColor) -> None:
        self._default_color = color

    @pyqtProperty(QColor)
    def whitelisted_color(self) -> QColor:
        return QColor(self._whitelisted_color)

    @whitelisted_color.setter  # type: ignore
    def whitelisted_color(self, color: QColor) -> None:
        self._whitelisted_color = color

    @pyqtProperty(QColor)
    def blacklisted_color(self) -> QColor:
        return QColor(self._blacklisted_color)

    @blacklisted_color.setter  # type: ignore
    def blacklisted_color(self, color: QColor) -> None:
        self._blacklisted_color = color

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.pos())
        if self.last_item != item:
            if item is not None:
                self.setCursor(Qt.PointingHandCursor)
                item.set_hovering(True)
            else:
                self.setCursor(Qt.ArrowCursor)
            if self.last_item is not None:
                self.last_item.set_hovering(False)
            self.last_item = item

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        if self.last_item is not None:
            self.last_item.set_hovering(False)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        super().enterEvent(event)
        if self.last_item is not None:
            self.last_item.set_hovering(False)
        item = self.itemAt(cast(QtGui.QEnterEvent, event).pos())
        if item is not None:
            self.setCursor(Qt.PointingHandCursor)
            item.set_hovering(True)
        self.last_item = item

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.pos())
        if item is not None:
            new_state: Optional[TagState] = None
            state = item.get_tag_state()
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
                item.set_tag_state(new_state)
                self.tag_state_updated.emit()
