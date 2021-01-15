import enum
import json
from pathlib import Path
from typing import Any, Counter, List, Optional, Tuple, cast

from libsyntyche.widgets import Signal0, Signal2, mk_signal1, mk_signal2
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtProperty

from . import jfti
from .image_loading import THUMB_SIZE, ImageLoader
from .settings import Settings
from .shared import (CACHE, DIMENSIONS, FILEFORMAT, FILESIZE, PATH, TAGS,
                     IconWidget, ListWidget)


class Mode(enum.Enum):
    normal = enum.auto()
    select = enum.auto()


mode_colors = {
    Mode.normal: '#334',
    Mode.select: '#364',
}

mode_texts = {
    Mode.normal: 'NORMAL',
    Mode.select: 'SELECT',
}


class Container(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.thumb_view: 'ThumbView'

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self.thumb_view.gridSize().width() + self.thumb_view.margin_size, 1)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.thumb_view.adjust_size(self.width())

    @property
    def mode(self) -> Mode:
        return self.thumb_view._mode


class StatusBar(QtWidgets.QFrame):

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName('thumb_view_status_bar')
        self._mode = Mode.normal
        # Colors
        layout = QtWidgets.QHBoxLayout(self)
        # Mode label
        layout.setContentsMargins(0, 0, 0, 0)
        self.mode_label = QtWidgets.QLabel(self)
        self.mode_label.setObjectName('thumb_view_mode_label')
        layout.addWidget(self.mode_label)
        # Selection info
        self.selection_label = QtWidgets.QLabel(self)
        self.selection_label.setObjectName('thumb_view_selection_label')
        layout.addWidget(self.selection_label)
        self.selection_label.hide()
        # Column count
        self.column_count_label = QtWidgets.QSpinBox(self)
        self.column_count_label.setToolTip('Change how many columns are visible')
        self.column_count_label.setObjectName('thumb_view_column_count')
        layout.addWidget(self.column_count_label)
        layout.addStretch()
        # Sort options
        self.sort_menu_button = QtWidgets.QPushButton('Sort...', self)
        self.sort_menu_button.setObjectName('thumb_view_sort_button')
        self.sort_menu = QtWidgets.QMenu(self)
        self.sort_menu.setObjectName('thumb_view_sort_menu')

        def mkopt(name: str, group: QtWidgets.QActionGroup, checked: bool = False
                  ) -> QtWidgets.QAction:
            opt = self.sort_menu.addAction(name)
            opt.setCheckable(True)
            opt.setChecked(checked)
            opt.setActionGroup(group)
            return opt
        self.sort_key_group = QtWidgets.QActionGroup(self)
        self.sort_by_path = mkopt('Path', self.sort_key_group, checked=True)
        self.sort_by_name = mkopt('File name', self.sort_key_group)
        self.sort_by_size = mkopt('File size', self.sort_key_group)
        self.sort_menu.addSeparator()
        self.sort_order_group = QtWidgets.QActionGroup(self)
        self.sort_ascending = mkopt('Ascending', self.sort_order_group, checked=True)
        self.sort_descending = mkopt('Descending', self.sort_order_group)
        layout.addWidget(self.sort_menu_button)

        def show_menu() -> None:
            self.sort_menu.popup(self.sort_menu_button.mapToGlobal(
                self.sort_menu_button.rect().bottomLeft()))

        self.sort_menu_button.clicked.connect(show_menu)

    def update_max_column_count(self, max_cols: int) -> None:
        self.column_count_label.setRange(1, max_cols)

    def update_column_count(self, cols: int) -> None:
        self.column_count_label.setValue(cols)

    @pyqtProperty(str)
    def mode(self) -> str:
        return self._mode.name

    @mode.setter  # type: ignore
    def mode(self, new_mode: str) -> None:
        self._mode = Mode[new_mode]
        self.column_count_label.setVisible(self._mode == Mode.normal)
        self.selection_label.setVisible(self._mode == Mode.select)
        self.mode_label.setText(mode_texts[self._mode])
        self.style().polish(self)


class ProgressBar(QtWidgets.QProgressBar):
    def text(self) -> str:
        value = self.value()
        total = self.maximum()
        return (f'Reloading thumbnails: {value}/{total}'
                f' ({value/max(total, 1):.0%})')


class ThumbView(ListWidget):
    image_queued: Signal2[int, List[Tuple[int, bool, Path]]] = mk_signal2(int, list)
    mode_changed = mk_signal1(Mode)

    def __init__(self, progress: ProgressBar, status_bar: StatusBar,
                 config: Settings, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self._mode = Mode.normal
        self.config = config
        self.progress = progress
        self.status_bar = status_bar
        self.status_bar.column_count_label.setValue(self.config.thumb_view_columns)
        self.batch = 0
        self.thumbnails_done = 0
        self.scroll_ratio: Optional[int] = None

        self.set_mode(Mode.normal, force=True)

        self.setUniformItemSizes(True)
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setMovement(QtWidgets.QListWidget.Static)
        self.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.setObjectName('thumb_view')
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

        default_thumb = QtGui.QPixmap(THUMB_SIZE)
        default_thumb.fill(QtGui.QColor(QtCore.Qt.gray))
        self.default_icon = QtGui.QIcon(default_thumb)
        self.default_icon.addPixmap(default_thumb, QtGui.QIcon.Selected)

        self.thumb_loader_thread = QtCore.QThread()
        cast(Signal0, QtWidgets.QApplication.instance().aboutToQuit  # type: ignore
             ).connect(self.thumb_loader_thread.quit)
        self.thumb_loader = ImageLoader()
        self.thumb_loader.moveToThread(self.thumb_loader_thread)
        self.image_queued.connect(self.thumb_loader.load_image)
        self.thumb_loader.thumbnail_ready.connect(self.add_thumbnail)
        self.thumb_loader_thread.start()
        self.update_thumb_size()

        def update_scroll_ratio(new_min: int, new_max: int) -> None:
            if self.scroll_ratio is not None:
                self.verticalScrollBar().setValue(int(new_max * self.scroll_ratio))
                self.scroll_ratio = None

        self.verticalScrollBar().rangeChanged.connect(update_scroll_ratio)

        def update_column_count(new_count: int) -> None:
            self.config.thumb_view_columns = new_count
            self.config.save()
            self.adjust_size(self.parent().width())

        self.status_bar.column_count_label.valueChanged.connect(update_column_count)
        self.selectionModel().selectionChanged.connect(self.update_selection_info)
        self.update_selection_info()

    def update_selection_info(self, arg1: Any = None, arg2: Any = None) -> None:
        self.status_bar.selection_label.setText(
            f'{len(self.selectedItems())}/{self.count()} selected'
        )

    def available_space_updated(self, width: int) -> None:
        self.status_bar.column_count_label.setRange(
            1, (width - self.margin_size) // self.gridSize().width()
        )

    def allow_fullscreen(self) -> bool:
        return self._mode == Mode.normal

    def set_mode(self, mode: Mode, force: bool = False) -> None:
        if mode != self._mode or force:
            self._mode = mode
            if mode == Mode.normal:
                self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
            elif mode == Mode.select:
                self.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
            self.status_bar.mode = mode.name
            vs = self.verticalScrollBar()
            if vs.maximum() > 0:
                self.scroll_ratio = vs.value() / vs.maximum()
            self.mode_changed.emit(mode)

    def update_thumb_size(self) -> None:
        if self.config.show_names:
            text_height = int(QtGui.QFontMetricsF(self.font()).height() * 1.5)
        else:
            text_height = 0
        self.setIconSize(THUMB_SIZE + QtCore.QSize(0, text_height))
        margin = (10 + 3) * 2
        self.setGridSize(THUMB_SIZE + QtCore.QSize(margin, margin + text_height))

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

    @property
    def margin_size(self) -> int:
        return (
            (self.contentsMargins().left() + self.contentsMargins().right()) * 2
            + self.verticalScrollBar().width()
        )

    def adjust_size(self, max_width: int) -> None:
        if self._mode == Mode.select:
            max_cols = (max_width - self.margin_size) // self.gridSize().width()
            new_width = self.margin_size + max_cols * self.gridSize().width()
        elif self._mode == Mode.normal:
            new_width = self.margin_size + self.gridSize().width() * self.config.thumb_view_columns
        if new_width != self.width():
            vs = self.verticalScrollBar()
            if vs.maximum() > 0:
                self.scroll_ratio = vs.value() / vs.maximum()
            self.setFixedWidth(new_width)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._mode != Mode.select:
            self.setFixedWidth(
                self.margin_size + self.gridSize().width() * self.config.thumb_view_columns
            )

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if self._mode == Mode.select and event.key() == Qt.Key_A:
            if event.modifiers() == Qt.ControlModifier:
                self.selectAll()
                return
            elif event.modifiers() == Qt.ShiftModifier | Qt.ControlModifier:
                self.clearSelection()
                return
        if event.key() in {Qt.Key_Right, Qt.Key_Left, Qt.Key_Up, Qt.Key_Down,
                           Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End,
                           Qt.Key_Space}:
            p1 = self.currentIndex()
            super().keyPressEvent(event)
            p2 = self.currentIndex()
            if self._mode == Mode.select and event.modifiers() & Qt.ShiftModifier:
                s = self.selectionModel().selection()
                s.select(p1, p2)
                self.selectionModel().select(s, QtCore.QItemSelectionModel.SelectCurrent)
        else:
            event.ignore()

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
        self.update_selection_info()
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
