from pathlib import Path
import typing
from typing import Any, cast, Counter, Dict, List, Set, Tuple

from jfti import jfti
from libsyntyche.widgets import Signal0, Signal1, mk_signal1
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialogButtonBox

from .shared import ListWidget, ListWidgetItem, PATH, TAGS, TAG_COUNT


def sort_tag_list_by_num_and_alpha(a: QtWidgets.QListWidgetItem,
                                   b: QtWidgets.QListWidgetItem) -> bool:
    def get_data(x: QtWidgets.QListWidgetItem) -> Tuple[Any, ...]:
        # visible = x.data(TAG_COUNT)[0]
        checked = x.checkState() == Qt.Unchecked
        return (checked, x.data(PATH).lower(), *x.data(TAG_COUNT))

    return get_data(a) < get_data(b)


class TagInput(QtWidgets.QLineEdit):
    tab_pressed = mk_signal1(bool)

    def event(self, raw_ev: QtCore.QEvent) -> bool:
        if raw_ev.type() == QtCore.QEvent.KeyPress:
            ev = cast(QtGui.QKeyEvent, raw_ev)
            if ev.key() == Qt.Key_Backtab and ev.modifiers() == Qt.ShiftModifier:
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
            elif ev.key() == Qt.Key_Tab and ev.modifiers() == Qt.NoModifier:
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


class TaggingWindow(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.original_tags: Counter[str] = Counter()
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
        input_box.addWidget(self.tag_input)
        self.add_tag_button = QtWidgets.QPushButton('Add tag', self)
        input_box.addWidget(self.add_tag_button)
        layout.addLayout(input_box)

        def update_add_button(text: str) -> None:
            self.add_tag_button.setEnabled(bool(text.strip()))

        cast(Signal1[str], self.tag_input.textChanged).connect(update_add_button)
        cast(Signal0, self.tag_input.returnPressed).connect(self.add_tag)
        cast(Signal0, self.add_tag_button.clicked).connect(self.add_tag)

        # Tag list
        layout.addWidget(QtWidgets.QLabel('All tags'))
        self.tag_list = ListWidget(self)
        self.tag_list.sort_func = sort_tag_list_by_num_and_alpha
        layout.addWidget(self.tag_list)

        def just_sort(x: QtWidgets.QListWidgetItem) -> None:
            self.tag_list.sortItems()
        cast(Signal1[QtWidgets.QListWidgetItem], self.tag_list.itemChanged).connect(just_sort)

        # Buttons
        button_box = QDialogButtonBox(self)
        button_box.addButton(QDialogButtonBox.Cancel)
        self.accept_button = button_box.addButton('Apply to images',
                                                  QDialogButtonBox.AcceptRole)
        cast(Signal0, button_box.accepted).connect(self.accept)
        cast(Signal0, button_box.rejected).connect(self.reject)
        layout.addWidget(button_box)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key_Return:
            if event.modifiers() & Qt.ControlModifier:
                self.accept()
        else:
            super().keyPressEvent(event)

    def get_tags_to_add(self) -> Set[str]:
        out = set()
        for item in self.tag_list:
            if item.checkState() == Qt.Checked:
                out.add(item.data(PATH))
        return out

    def get_tags_to_remove(self) -> Set[str]:
        out = set()
        for item in self.tag_list:
            if item.checkState() == Qt.Unchecked:
                out.add(item.data(PATH))
        return out

    def add_tag(self) -> None:
        if not self.add_tag_button.isEnabled():
            return
        tag = self.tag_input.text().strip()
        if tag:
            tags = {item.data(PATH): item for item in self.tag_list}
            if tag in tags:
                item = tags[tag]
                item.setCheckState(Qt.Checked)
            else:
                item = ListWidgetItem(f'{tag} (NEW)')
                item.setData(PATH, tag)
                item.setData(TAG_COUNT, (0, 0))
                item.setCheckState(Qt.Checked)
                self.tag_list.insertItem(0, item)
            self.tag_input.clear()
            self.tag_list.sortItems()

    def set_up(self, tags: typing.Counter[str],
               images: List[QtWidgets.QListWidgetItem]) -> None:
        self.original_tags = tags
        self.accept_button.setText(f'Apply to {len(images)} images')
        self.tag_input.clear()
        self.tag_list.clear()
        tag_counter: typing.Counter[str] = Counter()
        for img in images:
            img_tags = img.data(TAGS)
            tag_counter.update(img_tags)
        model = QtCore.QStringListModel(tags.keys())
        self.completer.setModel(model)
        for tag, total in tags.items():
            count = tag_counter.get(tag, 0)
            item = ListWidgetItem(f'{tag} ({count}/{total})')
            item.setData(PATH, tag)
            item.setData(TAG_COUNT, (count, total))
            if count == len(images):
                item.setCheckState(Qt.Checked)
            elif count == 0:
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.PartiallyChecked)
            self.tag_list.addItem(item)
        self.tag_list.sortItems()
        self.tag_input.setFocus()

    def tag_images(self, items: List[QtWidgets.QListWidgetItem]
                   ) -> Tuple[int, Dict[Path, Set[str]],
                              Counter[str], Set[str]]:
        # Progress dialog
        progress_dialog = QtWidgets.QProgressDialog(
            'Tagging images...', 'Cancel', 0, len(items))
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        # Info about the data we're working with
        total = len(items)
        tags_to_add = self.get_tags_to_add()
        tags_to_remove = self.get_tags_to_remove()
        created_tags = tags_to_add - set(self.original_tags.keys())
        # Info about the changes
        new_tag_count: Counter[str] = Counter()
        untagged_diff = 0
        updated_files = {}
        # Tag the files
        for n, item in enumerate(items):
            progress_dialog.setLabelText(f'Tagging images... '
                                         f'({n}/{total})')
            progress_dialog.setValue(n)
            old_tags = item.data(TAGS)
            new_tags = (old_tags | tags_to_add) - tags_to_remove
            if old_tags != new_tags:
                added_tags = new_tags - old_tags
                removed_tags = old_tags - new_tags
                new_tag_count.update({t: 1 for t in added_tags})
                new_tag_count.update({t: -1 for t in removed_tags})
                path = item.data(PATH)
                try:
                    jfti.set_tags(path, new_tags)
                except Exception:
                    print('FAIL', path)
                    raise
                item.setData(TAGS, new_tags)
                updated_files[item.data(PATH)] = new_tags
                if not old_tags and new_tags:
                    untagged_diff -= 1
                elif old_tags and not new_tags:
                    untagged_diff += 1
            if progress_dialog.wasCanceled():
                break
        progress_dialog.setValue(total)
        return untagged_diff, updated_files, new_tag_count, created_tags
