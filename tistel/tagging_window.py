import typing
from typing import cast, Counter, List, Set

from PyQt5 import QtGui, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import QDialogButtonBox

from .shared import ListWidget, PATH, TAGS
from .tag_list import TagListWidgetItem


class TaggingWindow(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.original_tags: Counter[str] = Counter()
        self.tags_to_add: Set[str] = set()
        self.tags_to_remove: Set[str] = set()
        self.resize(300, 500)

        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        self.heading_label = QtWidgets.QLabel('Change tags')
        self.heading_label.setObjectName('dialog_heading')
        layout.addWidget(self.heading_label)

        # Input
        input_box = QtWidgets.QHBoxLayout()
        self.tag_input = QtWidgets.QLineEdit(self)
        input_box.addWidget(self.tag_input)
        self.add_tag_button = QtWidgets.QPushButton('Add tag', self)
        input_box.addWidget(self.add_tag_button)
        layout.addLayout(input_box)

        def update_add_button(text: str) -> None:
            tags = {item.data(PATH) for item in self.tag_list}
            tag = text.strip()
            self.add_tag_button.setEnabled(bool(tag) and tag not in tags)

        cast(pyqtSignal, self.tag_input.textChanged).connect(update_add_button)
        cast(pyqtSignal, self.tag_input.returnPressed).connect(self.add_tag)
        cast(pyqtSignal, self.add_tag_button.clicked).connect(self.add_tag)

        # Tag list
        self.tag_list = ListWidget(self)
        self.tag_list.sort_by_alpha = True
        layout.addWidget(self.tag_list)

        # Buttons
        button_box = QDialogButtonBox(self)
        button_box.addButton(QDialogButtonBox.Cancel)
        self.accept_button = button_box.addButton('Apply to images',
                                                  QDialogButtonBox.AcceptRole)
        cast(pyqtSignal, button_box.accepted).connect(self.accept)
        cast(pyqtSignal, button_box.rejected).connect(self.reject)
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
            tags = {item.data(PATH) for item in self.tag_list}
            if tag not in tags:
                item = TagListWidgetItem(f'{tag} (NEW)')
                item.setData(PATH, tag)
                item.setData(TAGS, (0, 0))
                item.setCheckState(Qt.Checked)
                self.tag_list.insertItem(0, item)
            self.tag_input.clear()

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
        for tag, total in tags.items():
            count = tag_counter.get(tag, 0)
            item = TagListWidgetItem(f'{tag} ({count}/{total})')
            item.setData(PATH, tag)
            item.setData(TAGS, (count, total))
            if count == len(images):
                item.setCheckState(Qt.Checked)
            elif count == 0:
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.PartiallyChecked)
            self.tag_list.addItem(item)
        self.tag_list.sortItems()
        self.tag_input.setFocus()
