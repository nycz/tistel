from pathlib import Path
from typing import Set

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidgetItem

from .shared import make_svg_icon


class DirectoryTree(QtWidgets.QTreeWidget):
    def __init__(self, directories: Set[Path],
                 parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.icon = make_svg_icon('folder', 14, Qt.white)
        self.setHeaderHidden(True)
        self.update_paths(directories)

    def update_paths(self, directories: Set[Path]) -> None:
        max_depth = 10
        while self.topLevelItemCount() > 0:
            self.takeTopLevelItem(0)

        def recurse(parent: Path, parent_item: QTreeWidgetItem,
                    depth: int) -> None:
            if depth > max_depth:
                return
            for child in parent.iterdir():
                if child.is_dir():
                    item = QTreeWidgetItem([child.name])
                    item.setIcon(0, self.icon)
                    parent_item.addChild(item)
                    recurse(child, item, depth + 1)

        for directory in directories:
            if not directory.exists():
                continue
            item = QtWidgets.QTreeWidgetItem([directory.name])
            item.setIcon(0, self.icon)
            recurse(directory, item, 0)
            self.addTopLevelItem(item)
        self.sortItems(0, Qt.AscendingOrder)
