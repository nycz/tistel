import json
from pathlib import Path
from typing import cast, Counter, List, Optional, Tuple

from jfti import jfti
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt

from .image_loading import ImageLoader, THUMB_SIZE
from .settings import Settings
from .shared import (CACHE, DIMENSIONS, FILEFORMAT, FILESIZE,
                     ListWidget, PATH, Signal2, TAGS)


class ProgressBar(QtWidgets.QProgressBar):
    def text(self) -> str:
        value = self.value()
        total = self.maximum()
        return (f'Reloading thumbnails: {value}/{total}'
                f' ({value/max(total, 1):.0%})')


class ThumbView(ListWidget):
    image_queued: Signal2[int,
                          List[Tuple[int, bool, Path]]] = pyqtSignal(int, list)

    def __init__(self, progress: ProgressBar, config: Settings,
                 parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.config = config
        self.progress = progress
        self.batch = 0
        self.thumbnails_done = 0

        self.setUniformItemSizes(True)
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setMovement(QtWidgets.QListWidget.Static)
        self.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.setObjectName('thumb_view')
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)

        default_thumb = QtGui.QPixmap(THUMB_SIZE)
        default_thumb.fill(QtGui.QColor(QtCore.Qt.gray))
        self.default_icon = QtGui.QIcon(default_thumb)
        self.default_icon.addPixmap(default_thumb, QtGui.QIcon.Selected)

        self.thumb_loader_thread = QtCore.QThread()
        cast(pyqtSignal, QtWidgets.QApplication.instance().aboutToQuit
             ).connect(self.thumb_loader_thread.quit)
        self.thumb_loader = ImageLoader()
        self.thumb_loader.moveToThread(self.thumb_loader_thread)
        self.image_queued.connect(self.thumb_loader.load_image)
        self.thumb_loader.thumbnail_ready.connect(self.add_thumbnail)
        self.thumb_loader_thread.start()
        self.update_thumb_size()

    def update_thumb_size(self) -> None:
        if self.config.show_names:
            text_height = int(QtGui.QFontMetricsF(self.font()
                                                  ).height() * 1.5)
        else:
            text_height = 0
        self.setIconSize(THUMB_SIZE + QtCore.QSize(0, text_height))
        margin = (10 + 3) * 2
        self.setGridSize(THUMB_SIZE
                         + QtCore.QSize(margin, margin + text_height))

    def find_visible(self, reverse: bool = False
                     ) -> Optional[QtWidgets.QListWidgetItem]:
        diff = -1 if reverse else 1
        total = self.count()
        i = self.currentRow()
        if i < 0 or total < 0:
            return None
        for _ in range(total):
            i += diff
            i %= total
            item = self.item(i)
            if not item.isHidden():
                return item
        return None

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key_Right:
            next_widget = self.find_visible()
            if next_widget is not None:
                self.setCurrentItem(next_widget)
        elif event.key() == Qt.Key_Left:
            prev_widget = self.find_visible(reverse=True)
            if prev_widget is not None:
                self.setCurrentItem(prev_widget)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        current = self.currentItem()
        if current:
            painter = QtGui.QPainter(self.viewport())
            rect = self.visualItemRect(current).adjusted(6, 6, -7, -7)
            pen = QtGui.QPen(QtGui.QColor('#1bf986'))
            pen.setWidth(2)
            pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen)
            painter.drawRect(rect)

    def load_index(self, skip_thumb_cache: bool
                   ) -> Optional[Tuple[List[Tuple[str, int]], Counter[str]]]:
        if not CACHE.exists():
            return None
        self.clear()
        self.batch += 1
        imgs = []
        cache = json.loads(CACHE.read_text())
        tag_count: Counter[str] = Counter()
        root_paths = [str(p) for p in self.config.active_paths]
        n = 0
        untagged = 0
        for raw_path, data in sorted(cache['images'].items()):
            path = Path(raw_path)
            if not path.exists():
                del cache['images'][raw_path]
                continue
            for p in root_paths:
                if raw_path.startswith(p):
                    break
            else:
                continue
            item_text = path.name if self.config.show_names else None
            item = QtWidgets.QListWidgetItem(self.default_icon, item_text)
            self.addItem(item)
            item.setData(PATH, path)
            item.setData(FILESIZE, data['size'])
            item.setData(TAGS, set(data['tags']))
            item.setData(DIMENSIONS, (data['w'], data['h']))
            item.setData(FILEFORMAT, jfti.identify_image_format(path))
            imgs.append((n, skip_thumb_cache, path))
            n += 1
            tag_count.update(data['tags'])
            if not data['tags']:
                untagged += 1
        if self.currentItem() is None:
            self.setCurrentRow(0)
        self.image_queued.emit(self.batch, imgs)
        tags = [('', untagged)]
        for tag, count in tag_count.most_common():
            tags.append((tag, count))
        total = self.count()
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(0)
            self.progress.show()
        else:
            self.progress.hide()
        return tags, tag_count

    def add_thumbnail(self, index: int, batch: int, icon: QtGui.QIcon) -> None:
        if batch != self.batch:
            return
        item = self.item(index)
        item.setIcon(icon)
        done = self.progress.value() + 1
        total = self.count()
        self.progress.setValue(done)
        if done == total:
            self.progress.hide()
