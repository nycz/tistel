from typing import Counter, FrozenSet, List, Optional, cast

from libsyntyche.widgets import Signal0, kill_theming, mk_signal0
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtProperty  # type: ignore
from PyQt5.QtGui import QColor

from . import shared
from .shared import ImageData, ListWidget2, TagState, TagStates


class SortButton(QtWidgets.QPushButton):
    def __init__(self, text: str, object_name: str, group: QtWidgets.QButtonGroup,
                 parent: QtWidgets.QWidget, checked: bool = False) -> None:
        super().__init__(text, parent)
        self.reversed = False
        self.setObjectName(object_name)
        self.setCheckable(True)
        self.setChecked(checked)
        group.addButton(self)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.RightButton:
            self.reversed = not self.reversed
            self.setText(self.text()[::-1])
        elif event.button() == Qt.LeftButton:
            self.setChecked(True)
        cast(Signal0, self.pressed).emit()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        return


class TagListContainer(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName('tag_list_box')
        layout = QtWidgets.QVBoxLayout(self)
        kill_theming(layout)

        # Tag list buttons
        buttons_hbox = QtWidgets.QHBoxLayout()
        kill_theming(buttons_hbox)
        layout.addLayout(buttons_hbox)
        clear_button = QtWidgets.QPushButton('Clear tags', self)
        clear_button.setObjectName('clear_button')
        sort_buttons = QtWidgets.QButtonGroup(self)
        sort_buttons.setExclusive(True)
        self.sort_alpha_button = SortButton('a-z', 'sort_alpha_button', sort_buttons,
                                            self, checked=True)
        self.sort_count_button = SortButton('0-9', 'sort_count_button', sort_buttons, self)
        buttons_hbox.addWidget(clear_button)
        buttons_hbox.addStretch()
        buttons_hbox.addWidget(self.sort_alpha_button)
        buttons_hbox.addWidget(self.sort_count_button)

        # Tag list
        self.list_widget = TagListWidget(self)
        self.list_widget.setObjectName('tag_list')
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.tag_state_updated = self.list_widget.tag_state_updated
        layout.addWidget(self.list_widget)

        def sort_button_pressed(button: SortButton) -> None:
            if not button.isChecked():
                return
            cast(QtCore.QSortFilterProxyModel, self.list_widget.model()).setSortRole(
                shared.TAG_NAME if button == self.sort_alpha_button else shared.TAG_COUNT
            )
            self.list_widget.model().sort(0, Qt.DescendingOrder
                                          if button.reversed else Qt.AscendingOrder)

        def alpha_sort_button_pressed() -> None:
            sort_button_pressed(self.sort_alpha_button)

        def count_sort_button_pressed() -> None:
            sort_button_pressed(self.sort_count_button)

        cast(Signal0, self.sort_alpha_button.pressed).connect(alpha_sort_button_pressed)
        cast(Signal0, self.sort_count_button.pressed).connect(count_sort_button_pressed)

        def clear_tag_filters() -> None:
            for item in self.list_widget.items():
                item.tag_state = TagState.DEFAULT
            self.list_widget.tag_state_updated.emit()

        cast(Signal0, clear_button.clicked).connect(clear_tag_filters)

    def set_current_image_data(self, image: Optional[ImageData]) -> None:
        self.list_widget.selected_item_tags = (
            frozenset() if image is None else frozenset(image.tags)
        )

    def get_tag_states(self) -> TagStates:
        whitelist = set()
        blacklist = set()
        untagged_state = TagState.DEFAULT
        for tag_item in self.list_widget.items():
            state = tag_item.tag_state
            tag = tag_item.tag_name
            if tag == '':
                untagged_state = state
            elif state == TagState.WHITELISTED:
                whitelist.add(tag)
            elif state == TagState.BLACKLISTED:
                blacklist.add(tag)
        return TagStates(whitelist=frozenset(whitelist),
                         blacklist=frozenset(blacklist),
                         untagged_state=untagged_state)

    def sort_tags(self) -> None:
        button = (self.sort_alpha_button if self.sort_alpha_button.isChecked()
                  else self.sort_count_button)
        self.list_widget.model().sort(0, Qt.DescendingOrder
                                      if button.reversed else Qt.AscendingOrder)

    def set_tags(self, tags: Counter[str]) -> None:
        self.list_widget.clear()
        for tag, count in tags.most_common():
            self.list_widget.create_tag(tag, count)
        self.sort_tags()

    def update_tags(self, untagged_diff: int, tag_count_diff: Counter[str],
                    created_tags: FrozenSet[str]) -> None:
        tag_items_to_delete: List[int] = []
        for i, tag_item in enumerate(self.list_widget.items()):
            tag = tag_item.tag_name
            diff = tag_count_diff.get(tag, 0)
            if diff != 0:
                new_count = tag_item.tag_count + diff
                if new_count <= 0:
                    # del self.tag_count[tag]
                    tag_items_to_delete.append(i)
                tag_item.tag_count = new_count
        # Get rid of the items in reverse order to not mess up the numbers
        for i in reversed(tag_items_to_delete):
            self.list_widget.takeRow(i)
        for tag in created_tags:
            count = tag_count_diff.get(tag, 0)
            if count > 0:
                self.list_widget.create_tag(tag, count)

    def update_visible_tags(self, tag_count: Counter[str]) -> None:
        for item in self.list_widget.items():
            tag = item.tag_name
            new_count = tag_count[tag]
            item.visible_tag_count = new_count
            item.setText(self.list_widget._tag_format(tag, new_count, item.tag_count))


class TagListDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter: QtGui.QPainter,
              option: QtWidgets.QStyleOptionViewItem,
              index: QtCore.QModelIndex) -> None:
        parent = cast(TagListWidget, option.styleObject)
        item = parent.itemFromIndex(index)
        tag = item.tag_name
        painter.setRenderHints(QtGui.QPainter.Antialiasing)
        dot_width = 10
        padding = (option.rect.height() - option.fontMetrics.height()) // 2
        rect = option.rect.adjusted(padding + dot_width, padding, -padding, -padding)
        if tag in parent._selected_item_tags:
            painter.fillRect(option.rect, QColor(255, 255, 150, 10))
        state = item.tag_state
        colors = {TagState.WHITELISTED: cast(QColor, parent.whitelisted_color),
                  TagState.DEFAULT: cast(QColor, parent.default_color),
                  TagState.BLACKLISTED: cast(QColor, parent.blacklisted_color)}
        color = colors[state]
        font = option.font
        font.setBold(False)
        font.setItalic(False)
        count = item.tag_count
        visible_count = item.visible_tag_count
        if item.hovering:
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
        if tag in parent._selected_item_tags:
            pen = QtGui.QPen()
            pen.setWidth(0)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor('#ffffcc'))
            painter.drawEllipse(
                QtCore.QPoint(padding + dot_width // 2,
                              option.rect.top() + option.rect.height() // 2),
                3, 3)


class TagListItem(QtGui.QStandardItem):
    @property
    def hovering(self) -> bool:
        return cast(bool, self.data(shared.HOVERING))

    @hovering.setter
    def hovering(self, hovering: bool) -> None:
        self.setData(hovering, shared.HOVERING)

    @property
    def tag_count(self) -> int:
        return cast(int, self.data(shared.TAG_COUNT))

    @tag_count.setter
    def tag_count(self, tag_count: int) -> None:
        self.setData(tag_count, shared.TAG_COUNT)

    @property
    def tag_name(self) -> str:
        return cast(str, self.data(shared.TAG_NAME))

    @tag_name.setter
    def tag_name(self, tag_name: str) -> None:
        self.setData(tag_name, shared.TAG_NAME)

    @property
    def tag_state(self) -> TagState:
        return cast(TagState, self.data(shared.TAG_STATE))

    @tag_state.setter
    def tag_state(self, tag_state: TagState) -> None:
        self.setData(tag_state, shared.TAG_STATE)

    @property
    def visible_tag_count(self) -> int:
        return cast(int, self.data(shared.VISIBLE_TAG_COUNT))

    @visible_tag_count.setter
    def visible_tag_count(self, visible_tag_count: int) -> None:
        self.setData(visible_tag_count, shared.VISIBLE_TAG_COUNT)


class TagListWidget(ListWidget2[TagListItem]):
    tag_state_updated = mk_signal0()

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self._selected_item_tags: FrozenSet[str] = frozenset()
        self._default_color = QColor(Qt.white)
        self._whitelisted_color = QColor(Qt.green)
        self._blacklisted_color = QColor(Qt.red)
        self.setItemDelegate(TagListDelegate(self))
        self.setMouseTracking(True)
        self.last_item: Optional[TagListItem] = None

    @staticmethod
    def _tag_format(tag: str, visible: int, total: int) -> str:
        return f'{tag}   ({visible}/{total})'

    def create_tag(self, tag: str, count: int) -> None:
        item = TagListItem(self._tag_format(tag, count, count))
        item.tag_name = tag
        item.tag_count = count
        item.visible_tag_count = count
        item.tag_state = TagState.DEFAULT
        self.addItem(item)

    @property
    def selected_item_tags(self) -> FrozenSet[str]:
        return self._selected_item_tags

    @selected_item_tags.setter
    def selected_item_tags(self, tags: FrozenSet[str]) -> None:
        self._selected_item_tags = tags
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
                item.hovering = True
            else:
                self.setCursor(Qt.ArrowCursor)
            if self.last_item is not None:
                self.last_item.hovering = False
            self.last_item = item

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        if self.last_item is not None:
            self.last_item.hovering = False

    def enterEvent(self, event: QtCore.QEvent) -> None:
        super().enterEvent(event)
        if self.last_item is not None:
            self.last_item.hovering = False
        item = self.itemAt(cast(QtGui.QEnterEvent, event).pos())
        if item is not None:
            self.setCursor(Qt.PointingHandCursor)
            item.hovering = True
        self.last_item = item

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.pos())
        if item is not None:
            new_state: Optional[TagState] = None
            state = item.tag_state
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
                item.tag_state = new_state
                self.tag_state_updated.emit()
