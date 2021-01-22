from typing import (Any, Counter, FrozenSet, List, NamedTuple, Optional, Tuple,
                    cast)

from libsyntyche.widgets import Signal0, Signal1, mk_signal1
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialogButtonBox

from . import shared
from .shared import ImageData, ListWidget2


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

    def event(self, raw_ev: QtCore.QEvent) -> bool:
        if raw_ev.type() == QtCore.QEvent.KeyPress:
            ev = cast(QtGui.QKeyEvent, raw_ev)
            if ev.key() == Qt.Key_Backtab and int(ev.modifiers()) == Qt.ShiftModifier:
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
            elif ev.key() == Qt.Key_Tab and int(ev.modifiers()) == Qt.NoModifier:
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
            elif ev.key() == Qt.Key_Return:
                self.completer().popup().hide()
                cast(Signal0, self.returnPressed).emit()
                return True
        return super().event(raw_ev)


class TaggingListItem(QtGui.QStandardItem):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setCheckable(True)
        self.setEditable(False)

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


class TagChanges(NamedTuple):
    tags_to_add: FrozenSet[str]
    tags_to_remove: FrozenSet[str]


class TaggingWindow(QtWidgets.QDialog):
    def __init__(self, images: List[ImageData], total_tags: Counter[str],
                 parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.original_tags: Counter[str] = total_tags
        self.resize(300, 500)

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

        # Tag list
        layout.addWidget(QtWidgets.QLabel('All tags'))
        self._sort_model = SortProxyModel()
        self.tag_list: ListWidget2[TaggingListItem] = ListWidget2(self, self._sort_model)
        tag_counter: Counter[str] = Counter()
        for img in images:
            tag_counter.update(img.tags)
        for tag, total in total_tags.items():
            count = tag_counter.get(tag, 0)
            item = TaggingListItem(f'{tag} ({count}/{total})')
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
        layout.addWidget(self.sort_button)

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
