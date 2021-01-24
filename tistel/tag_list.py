import enum
from typing import Counter, FrozenSet, List, Optional, cast

from libsyntyche.widgets import Signal0, kill_theming, mk_signal0
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtProperty  # type: ignore
from PyQt5.QtGui import QColor

from . import shared
from .shared import ImageData, ListWidget2, TagState, TagStates


class UntaggedToggle(QtWidgets.QCheckBox):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.current_is_untagged = False
        self.selected_has_untagged = False
        self.setCursor(Qt.PointingHandCursor)
        self.total_count = 0
        self.setMouseTracking(True)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        parent = cast(TagListContainer, self.parent())
        if self.current_is_untagged:
            painter.fillRect(event.rect(),
                             cast(QColor, parent.list_widget.current_image_tags_color))
        elif self.selected_has_untagged:
            painter.fillRect(event.rect(),
                             cast(QColor, parent.list_widget.selected_images_tags_color))
        if self.underMouse():
            painter.fillRect(event.rect(), QColor(255, 255, 255, 0x33))
        painter.setRenderHints(QtGui.QPainter.Antialiasing)
        indicator_width = 12
        indicator_radius = int(indicator_width * 0.8 / 2)
        fm = QtGui.QFontMetrics(painter.font(), self)
        padding = (self.height() - fm.height()) // 2
        rect = event.rect().adjusted(padding + indicator_width, padding, -padding, -padding)
        if self.checkState() == Qt.Checked:
            pen = painter.pen()
            pen.setWidth(2)
            painter.setPen(pen)
            x = (padding + indicator_width) // 2
            y = rect.center().y()
            painter.drawLine(x - indicator_radius, y, x + indicator_radius, y)
            painter.drawLine(x, y - indicator_radius, x, y + indicator_radius)
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
        painter.drawText(rect, Qt.TextSingleLine, 'Show untagged')
        painter.drawText(rect, Qt.AlignRight | Qt.TextSingleLine, str(self.total_count))

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.toggle()


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
        buttons_hbox.addWidget(clear_button)
        buttons_hbox.addStretch()

        # Filter untagged buttons
        self.show_untagged_toggle = UntaggedToggle(self)
        self.show_untagged_toggle.setObjectName('show_untagged_toggle')
        layout.addWidget(self.show_untagged_toggle, stretch=1)

        # Tag list
        self.list_widget = TagListWidget(self)
        self.list_widget.setObjectName('tag_list')
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.list_widget)

        self.tag_state_updated = self.list_widget.tag_state_updated
        self.show_untagged_toggle.toggled.connect(self.tag_state_updated.emit)

        self.sort_button = shared.make_sort_menu(
            self,
            cast(QtCore.QSortFilterProxyModel, self.list_widget.model()),
            {'Name': shared.TAG_NAME,
             'Count': shared.TAG_COUNT},
        )
        buttons_hbox.addWidget(self.sort_button)

        def clear_tag_filters() -> None:
            for item in self.list_widget.items():
                item.tag_state = TagState.DEFAULT
            self.show_untagged_toggle.setChecked(False)
            self.list_widget.tag_state_updated.emit()

        cast(Signal0, clear_button.clicked).connect(clear_tag_filters)

    def set_current_image_data(self, image: Optional[ImageData]) -> None:
        self.list_widget.current_image_tags = (
            frozenset() if image is None else frozenset(image.tags)
        )
        self.show_untagged_toggle.current_is_untagged = (image is not None
                                                         and len(image.tags) == 0)

    def set_selection_image_data(self, images: List[ImageData]) -> None:
        self.list_widget.selected_images_tags = frozenset(
            tag for image in images for tag in image.tags
        )
        self.show_untagged_toggle.selected_has_untagged = any(not image.tags for image in images)

    def get_tag_states(self) -> TagStates:
        whitelist = set()
        blacklist = set()
        untagged_state = (TagState.WHITELISTED
                          if self.show_untagged_toggle.isChecked()
                          else TagState.DEFAULT)
        for tag_item in self.list_widget.items():
            state = tag_item.tag_state
            tag = tag_item.tag_name
            if state == TagState.WHITELISTED:
                whitelist.add(tag)
            elif state == TagState.BLACKLISTED:
                blacklist.add(tag)
        return TagStates(whitelist=frozenset(whitelist),
                         blacklist=frozenset(blacklist),
                         untagged_state=untagged_state)

    def set_tags(self, untagged: int, tags: Counter[str]) -> None:
        self.list_widget.clear()
        for tag, count in tags.most_common():
            self.list_widget.create_tag(tag, count)
        self.show_untagged_toggle.total_count = untagged
        self.show_untagged_toggle.update()
        model = cast(QtCore.QSortFilterProxyModel, self.list_widget.model())
        model.sort(0, model.sortOrder())

    def update_tags(self, untagged: int, tag_count_diff: Counter[str],
                    created_tags: FrozenSet[str]) -> None:
        tag_items_to_delete: List[int] = []
        for i, tag_item in enumerate(self.list_widget.items()):
            tag = tag_item.tag_name
            diff = tag_count_diff.get(tag, 0)
            if diff != 0:
                new_count = tag_item.tag_count + diff
                if new_count <= 0:
                    tag_items_to_delete.append(i)
                tag_item.tag_count = new_count
        # Get rid of the items in reverse order to not mess up the numbers
        for i in reversed(tag_items_to_delete):
            self.list_widget.takeRow(i)
        for tag in created_tags:
            count = tag_count_diff.get(tag, 0)
            if count > 0:
                self.list_widget.create_tag(tag, count)
        self.show_untagged_toggle.total_count = untagged
        self.show_untagged_toggle.update()

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
        indicator_width = 12
        indicator_radius = int(indicator_width * 0.8 / 2)
        padding = (option.rect.height() - option.fontMetrics.height()) // 2
        rect = option.rect.adjusted(padding + indicator_width, padding, -padding, -padding)
        if parent.current_image_tags and tag in parent.current_image_tags:
            painter.fillRect(option.rect, cast(QColor, parent.current_image_tags_color))
        elif tag in parent.selected_images_tags:
            painter.fillRect(option.rect, cast(QColor, parent.selected_images_tags_color))
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
            painter.fillRect(option.rect, QColor(255, 255, 255, 0x33))
        if (count == 0 or visible_count == 0) and state != TagState.BLACKLISTED:
            color.setAlphaF(0.4)
            font.setItalic(True)
        font.setBold(state != TagState.DEFAULT)
        painter.setFont(font)
        pen = QtGui.QPen(color)
        pen.setWidth(2)
        painter.setPen(pen)
        if state in {TagState.WHITELISTED, TagState.BLACKLISTED}:
            x = (padding + indicator_width) // 2
            y = rect.center().y()
            painter.drawLine(x - indicator_radius, y, x + indicator_radius, y)
            if state == TagState.WHITELISTED:
                painter.drawLine(x, y - indicator_radius, x, y + indicator_radius)
        painter.drawText(rect, Qt.TextSingleLine, tag)
        painter.drawText(rect, Qt.AlignRight | Qt.TextSingleLine, f'{visible_count} / {count}')


class TagListItem(shared.CustomDrawListItem):
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


class TagListWidget(shared.CustomDrawListWidget[TagListItem]):
    tag_state_updated = mk_signal0()

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent, TagListDelegate)
        self._selected_images_tags: FrozenSet[str] = frozenset()
        self._current_image_tags: FrozenSet[str] = frozenset()
        self._default_color = QColor(Qt.white)
        self._whitelisted_color = QColor(Qt.green)
        self._blacklisted_color = QColor(Qt.red)
        self._current_image_tags_color = QColor(Qt.yellow)
        self._selected_images_tags_color = QColor(Qt.blue)

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
    def selected_images_tags(self) -> FrozenSet[str]:
        return self._selected_images_tags

    @selected_images_tags.setter
    def selected_images_tags(self, tags: FrozenSet[str]) -> None:
        self._selected_images_tags = tags
        self.update()

    @property
    def current_image_tags(self) -> FrozenSet[str]:
        return self._current_image_tags

    @current_image_tags.setter
    def current_image_tags(self, tags: FrozenSet[str]) -> None:
        self._current_image_tags = tags
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

    @pyqtProperty(QColor)
    def selected_images_tags_color(self) -> QColor:
        return QColor(self._selected_images_tags_color)

    @selected_images_tags_color.setter  # type: ignore
    def selected_images_tags_color(self, color: QColor) -> None:
        self._selected_images_tags_color = color

    @pyqtProperty(QColor)
    def current_image_tags_color(self) -> QColor:
        return QColor(self._current_image_tags_color)

    @current_image_tags_color.setter  # type: ignore
    def current_image_tags_color(self, color: QColor) -> None:
        self._current_image_tags_color = color

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
