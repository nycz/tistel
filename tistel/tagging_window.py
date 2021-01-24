from typing import (Any, Counter, FrozenSet, List, NamedTuple, Optional, Tuple,
                    cast)

from libsyntyche.widgets import Signal0, Signal1, mk_signal0, mk_signal1
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialogButtonBox

from . import shared
from .shared import CustomDrawListItem, CustomDrawListWidget, ImageData, ListWidget2


class SortProxyModel(QtCore.QSortFilterProxyModel):
    def lessThan(self, left: QtCore.QModelIndex, right: QtCore.QModelIndex) -> bool:
        model = cast(QtGui.QStandardItemModel, self.sourceModel())

        def get_data(x: QtCore.QModelIndex) -> Tuple[bool, Any]:
            item = cast(TaggingListItem, model.itemFromIndex(x))
            checked = item.checkState() == Qt.Unchecked
            if self.sortOrder() == Qt.DescendingOrder:
                checked = not checked
            return (checked, x.data(self.sortRole()))
        return get_data(left) < get_data(right)


class TagInput(QtWidgets.QLineEdit):
    tab_pressed = mk_signal1(bool)
    do_accept = mk_signal0()

    def event(self, raw_ev: QtCore.QEvent) -> bool:
        if raw_ev.type() == QtCore.QEvent.KeyPress:
            ev = cast(QtGui.QKeyEvent, raw_ev)
            modifiers = int(ev.modifiers())
            if ev.key() == Qt.Key_Backtab and modifiers == Qt.ShiftModifier:
                comp = self.completer()
                if not comp.popup().isVisible():
                    return False
                if comp.currentRow() == 0:
                    if self.text() != comp.currentCompletion():
                        # We're at the prefix and wrapping to the end
                        comp.setCurrentRow(comp.completionCount() - 1)
                        comp.popup().setCurrentIndex(comp.currentIndex())
                    else:
                        # At the first post and showing the prefix
                        comp.popup().setCurrentIndex(QtCore.QModelIndex())
                else:
                    comp.setCurrentRow(comp.currentRow() - 1)
                    comp.popup().setCurrentIndex(comp.currentIndex())
                return True
            elif ev.key() == Qt.Key_Tab and modifiers == Qt.NoModifier:
                comp = self.completer()
                if not comp.popup().isVisible():
                    return False
                if self.text() != comp.currentCompletion():
                    # At the prefix and moving forward
                    comp.popup().setCurrentIndex(comp.currentIndex())
                else:
                    success = comp.setCurrentRow(comp.currentRow() + 1)
                    if success:
                        comp.popup().setCurrentIndex(comp.currentIndex())
                    else:
                        # Wrapping around and showing the prefix
                        comp.setCurrentRow(0)
                        comp.popup().setCurrentIndex(QtCore.QModelIndex())
                return True
            elif ev.key() == Qt.Key_Return and modifiers == Qt.NoModifier:
                self.completer().popup().hide()
                cast(Signal0, self.returnPressed).emit()
                return True
            elif ev.key() == Qt.Key_Return and modifiers == Qt.ControlModifier:
                self.do_accept.emit()
                return True
        return super().event(raw_ev)


class TagListDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter: QtGui.QPainter,
              option: QtWidgets.QStyleOptionViewItem,
              index: QtCore.QModelIndex) -> None:
        parent = cast(CustomDrawListWidget[TaggingListItem], option.styleObject)
        item = parent.itemFromIndex(index)
        tag = item.tag_name
        painter.setRenderHints(QtGui.QPainter.Antialiasing)
        padding = (option.rect.height() - option.fontMetrics.height()) // 2
        rect = option.rect.adjusted(padding, padding, -padding, -padding)
        cb_rect = QtCore.QRect(rect.topLeft(), QtCore.QSize(rect.height(), rect.height()))
        rect.adjust(cb_rect.width() + padding, 0, 0, 0)
        painter.fillRect(cb_rect, Qt.white)
        # TODO: de-hardcode this?
        check_color = QtGui.QColor('#06a')
        if item.checkState() == Qt.PartiallyChecked:
            bw = 2
            painter.fillRect(cb_rect.adjusted(bw, bw, -bw, -bw), check_color)
        elif item.checkState() == Qt.Checked:
            old_pen = painter.pen()
            new_pen = QtGui.QPen(check_color)
            new_pen.setWidth(3)
            painter.setPen(new_pen)
            w = cb_rect.width()
            painter.drawPolyline(cb_rect.topLeft() + QtCore.QPoint(int(w * 0.2), int(w * 0.55)),
                                 cb_rect.center() + QtCore.QPoint(0, int(w * 0.45)),
                                 cb_rect.topRight() + QtCore.QPoint(-int(w * 0.2), int(w * 0.25)))
            painter.setPen(old_pen)
        count = item.tag_count
        visible_count = item.visible_tag_count
        if item.hovering:
            painter.fillRect(option.rect, QtGui.QColor(255, 255, 255, 0x33))
        painter.drawText(rect, Qt.TextSingleLine, tag + (' (NEW)' if item.is_new else ''))
        painter.drawText(rect, Qt.AlignRight | Qt.TextSingleLine, f'{visible_count} / {count}')


class TaggingListItem(CustomDrawListItem):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setCheckable(True)
        self.setEditable(False)

    @property
    def is_new(self) -> bool:
        return cast(bool, self.data(shared.IS_NEW))

    @is_new.setter
    def is_new(self, is_new: bool) -> None:
        self.setData(is_new, shared.IS_NEW)

    @property
    def tag_count(self) -> int:
        return cast(int, self.data(shared.TAG_COUNT))

    @tag_count.setter
    def tag_count(self, total_count: int) -> None:
        self.setData(total_count, shared.TAG_COUNT)

    @property
    def tag_name(self) -> str:
        return cast(str, self.data(shared.TAG_NAME))

    @tag_name.setter
    def tag_name(self, tag_name: str) -> None:
        self.setData(tag_name, shared.TAG_NAME)

    @property
    def visible_tag_count(self) -> int:
        return cast(int, self.data(shared.VISIBLE_TAG_COUNT))

    @visible_tag_count.setter
    def visible_tag_count(self, visible_count: int) -> None:
        self.setData(visible_count, shared.VISIBLE_TAG_COUNT)


class TagListWidget(CustomDrawListWidget[TaggingListItem]):
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.pos())
        if item is not None:
            if event.button() == Qt.LeftButton:
                if item.checkState() == Qt.Checked:
                    item.setCheckState(Qt.Unchecked)
                else:
                    item.setCheckState(Qt.Checked)


class TagChanges(NamedTuple):
    tags_to_add: FrozenSet[str]
    tags_to_remove: FrozenSet[str]


class TaggingWindow(QtWidgets.QDialog):
    def __init__(self, images: List[ImageData], total_tags: Counter[str],
                 parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName('tagging_window')
        self.original_tags: Counter[str] = total_tags
        self.resize(400, int(parent.height() * 0.7))

        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        self.heading_label = QtWidgets.QLabel('Change tags')
        self.heading_label.setObjectName('dialog_heading')
        layout.addWidget(self.heading_label)

        # Input
        input_box = QtWidgets.QHBoxLayout()
        self.tag_input = TagInput(self)
        self.completer = QtWidgets.QCompleter(self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.tag_input.setCompleter(self.completer)
        self.completer.setModel(QtCore.QStringListModel(total_tags.keys()))
        input_box.addWidget(self.tag_input)
        self.add_tag_button = QtWidgets.QPushButton('Add tag', self)
        input_box.addWidget(self.add_tag_button)
        layout.addLayout(input_box)

        def update_add_button(text: str) -> None:
            self.add_tag_button.setEnabled(bool(text.strip()))

        cast(Signal1[str], self.tag_input.textChanged).connect(update_add_button)
        cast(Signal0, self.tag_input.returnPressed).connect(self._add_tag)
        cast(Signal0, self.add_tag_button.clicked).connect(self._add_tag)
        self.tag_input.do_accept.connect(self.accept)

        # Tag list
        tag_header_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(tag_header_layout)
        tag_header_layout.addWidget(QtWidgets.QLabel('All tags'))
        tag_header_layout.addStretch()
        self._sort_model = SortProxyModel()
        self.tag_list = TagListWidget(self, TagListDelegate, self._sort_model)
        self.tag_list.setObjectName('tagging_window_tag_list')
        tag_counter: Counter[str] = Counter()
        for img in images:
            tag_counter.update(img.tags)
        for tag, total in total_tags.items():
            count = tag_counter.get(tag, 0)
            item = TaggingListItem(f'{tag} ({count}/{total})')
            item.is_new = False
            item.tag_name = tag
            item.tag_count = total
            item.visible_tag_count = count
            item.setCheckState(Qt.Checked if count == len(images)
                               else Qt.Unchecked if count == 0
                               else Qt.PartiallyChecked)
            self.tag_list.addItem(item)
        layout.addWidget(self.tag_list)
        self.tag_input.setFocus()

        # Sorting
        self.sort_button = shared.make_sort_menu(
            self, self._sort_model,
            {'Name': shared.TAG_NAME,
             'Selected count': shared.VISIBLE_TAG_COUNT,
             'Total count': shared.TAG_COUNT},
        )
        tag_header_layout.addWidget(self.sort_button)

        # Buttons
        button_box = QDialogButtonBox(self)
        button_box.addButton(QDialogButtonBox.Cancel)
        self.accept_button = button_box.addButton(f'Apply to {len(images)} images',
                                                  QDialogButtonBox.AcceptRole)
        cast(Signal0, button_box.accepted).connect(self.accept)
        cast(Signal0, button_box.rejected).connect(self.reject)
        layout.addWidget(button_box)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key_Return:
            if int(event.modifiers()) & Qt.ControlModifier:
                self.accept()
        else:
            super().keyPressEvent(event)

    def _add_tag(self) -> None:
        if not self.add_tag_button.isEnabled():
            return
        tag = self.tag_input.text().strip()
        if tag:
            tags = {item.tag_name: item for item in self.tag_list.items()}
            if tag in tags:
                item = tags[tag]
                item.setCheckState(Qt.Checked)
            else:
                item = TaggingListItem(f'{tag} (NEW)')
                item.is_new = True
                item.tag_name = tag
                item.tag_count = 0
                item.visible_tag_count = 0
                item.setCheckState(Qt.Checked)
                self.tag_list.insertRow(0, item)
            self.tag_input.clear()
            self.tag_list.model().sort(0)

    @classmethod
    def get_tag_changes(cls, images: List[ImageData], total_tags: Counter[str],
                        parent: QtWidgets.QWidget) -> Optional[TagChanges]:
        dialog = cls(images, total_tags, parent)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            tags_to_add = frozenset(item.tag_name
                                    for item in dialog.tag_list.items()
                                    if item.checkState() == Qt.Checked)
            tags_to_remove = frozenset(item.tag_name
                                       for item in dialog.tag_list.items()
                                       if item.checkState() == Qt.Unchecked)
            return TagChanges(
                tags_to_add=tags_to_add,
                tags_to_remove=tags_to_remove,
            )
        else:
            return None
