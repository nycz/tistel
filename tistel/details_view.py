from typing import Optional

from PyQt5 import QtGui, QtWidgets
from PyQt5.QtCore import Qt

from . import jfti
from .shared import (DIMENSIONS, FILEFORMAT, FILESIZE, PATH, TAGS, IconWidget,
                     clear_layout, human_filesize)


class DetailsBox(QtWidgets.QScrollArea):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWidgetResizable(True)
        content = QtWidgets.QFrame(self)
        content.setObjectName('info_box')
        self.setWidget(content)
        layout = QtWidgets.QVBoxLayout(content)
        self.directory = QtWidgets.QLabel(self)
        self.directory.setWordWrap(True)
        layout.addWidget(self.directory)
        self.filename = QtWidgets.QLabel(self)
        self.filename.setWordWrap(True)
        layout.addWidget(self.filename)
        self.filesize = QtWidgets.QLabel(self)
        layout.addWidget(self.filesize)
        self.dimensions = QtWidgets.QLabel(self)
        layout.addWidget(self.dimensions)
        self.tag_box = QtWidgets.QGridLayout()
        layout.addLayout(self.tag_box)
        self.fileformat = QtWidgets.QLabel(self)
        self.fileformat.setWordWrap(True)
        self.fileformat.setStyleSheet('color: red')
        layout.addWidget(self.fileformat)
        layout.addStretch()

    def set_info(self, item: Optional[QtGui.QStandardItem]) -> None:
        if item is None:
            self.directory.clear()
            self.filename.clear()
            self.filesize.clear()
            self.dimensions.clear()
            clear_layout(self.tag_box)
        else:
            path = item.data(PATH)
            self.directory.setText(f'<b>Directory:</b> {path.parent}')
            self.filename.setText(f'<b>Name:</b> {path.name}')
            fmt = item.data(FILEFORMAT)
            if jfti.image_format_mismatch(path, fmt):
                self.fileformat.setText(f'<b>Mismatching format:</b> '
                                        f'{fmt.name}')
            else:
                self.fileformat.clear()
            width, height = item.data(DIMENSIONS)
            self.dimensions.setText(f'<b>Dimensions:</b> {width} x {height}')
            size = item.data(FILESIZE)
            self.filesize.setText(f'<b>Size:</b> {human_filesize(size)}')
            tags = item.data(TAGS)
            clear_layout(self.tag_box)
            for n, tag in enumerate(tags):
                tag_icon = IconWidget('tag', 16, self)
                tag_icon.setObjectName('tag_icon')
                self.tag_box.addWidget(tag_icon, n, 0)
                label = QtWidgets.QLabel(tag, self)
                label.setObjectName('tag')
                self.tag_box.addWidget(label, n, 1)
            self.update()
