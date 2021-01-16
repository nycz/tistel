import enum
import json
from pathlib import Path
from typing import Any, Counter, List, Optional, Set, Tuple, cast

from libsyntyche.widgets import Signal0, Signal2, mk_signal1, mk_signal2
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtProperty  # type: ignore

from . import jfti
from .image_loading import THUMB_SIZE, ImageLoader
from .settings import Settings
from .shared import (CACHE, DIMENSIONS, FILEFORMAT, FILENAME, FILESIZE, PATH,
                     PATH_STRING, TAGS, ListWidget2)
from .tag_list import TagState


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


class FilterProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.tag_whitelist: Set[str] = set()
        self.tag_blacklist: Set[str] = set()
        self.untagged_state: TagState = TagState.DEFAULT

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        tags = self.sourceModel().index(source_row, 0, source_parent).data(TAGS)
        if (self.untagged_state == TagState.WHITELISTED and tags) \
                or (self.untagged_state == TagState.BLACKLISTED and not tags) \
                or (self.tag_whitelist and not self.tag_whitelist.issubset(tags)) \
                or (self.tag_blacklist and not self.tag_blacklist.isdisjoint(tags)):
            return False
        return True

    def set_tag_filter(self, untagged_state: TagState,
                       whitelist: Set[str], blacklist: Set[str]) -> None:
        self.tag_whitelist = whitelist
        self.tag_blacklist = blacklist
        self.untagged_state = untagged_state
        self.invalidateFilter()


class ThumbView(ListWidget2):
    image_queued: Signal2[int, List[Tuple[int, bool, Path]]] = mk_signal2(int, list)
    mode_changed = mk_signal1(Mode)

    def __init__(self, progress: ProgressBar, status_bar: StatusBar,
                 config: Settings, parent: QtWidgets.QWidget) -> None:
        self._filter_model = FilterProxyModel()
        super().__init__(parent, self._filter_model)
        self._mode = Mode.normal
        self.config = config
        self.progress = progress
        self.status_bar = status_bar
        self.status_bar.column_count_label.setValue(self.config.thumb_view_columns)
        self.batch = 0
        self.thumbnails_done = 0
        self.scroll_ratio: Optional[float] = None
        self.selected_indexes: List[QtCore.QPersistentModelIndex] = []

        self.set_mode(Mode.normal, force=True)

        self.setUniformItemSizes(True)
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setMovement(QtWidgets.QListView.Static)
        self.setResizeMode(QtWidgets.QListView.Adjust)
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

        def update_sorting(action: QtWidgets.QAction) -> None:
            order = self.model().sortOrder()
            if action == self.status_bar.sort_by_path:
                self.model().setSortRole(PATH_STRING)
            elif action == self.status_bar.sort_by_name:
                self.model().setSortRole(FILENAME)
            elif action == self.status_bar.sort_by_size:
                self.model().setSortRole(FILESIZE)
            elif action == self.status_bar.sort_ascending:
                order = Qt.AscendingOrder
            elif action == self.status_bar.sort_descending:
                order = Qt.DescendingOrder
            self.model().sort(0, order)

        self.status_bar.sort_key_group.triggered.connect(update_sorting)
        self.status_bar.sort_order_group.triggered.connect(update_sorting)
        update_sorting(self.status_bar.sort_by_path)

    def set_tag_filter(self, *args: Any) -> None:
        # Disconnect the selection changed signal to stop it from overwriting
        # the old data when filtering
        self.selectionModel().selectionChanged.disconnect(self.update_selection_info)
        self._filter_model.set_tag_filter(*args)
        for sel_index in self.selected_indexes:
            index = self._filter_model.mapFromSource(QtCore.QModelIndex(sel_index))
            if index.isValid():
                self.selectionModel().select(index, QtCore.QItemSelectionModel.Select)
        self.selectionModel().selectionChanged.connect(self.update_selection_info)

    def update_selection_info(self, selected: Optional[QtCore.QItemSelection] = None,
                              deselected: Optional[QtCore.QItemSelection] = None) -> None:
        if deselected is not None:
            indexes = deselected.indexes()
            for rel_index in indexes:
                index = self._filter_model.mapToSource(rel_index)
                for n, sel_index in enumerate(self.selected_indexes):
                    if index == QtCore.QModelIndex(sel_index):
                        del self.selected_indexes[n]
                        break
                else:
                    print('ERROR: failed to remove selection index!')
        if selected is not None:
            self.selected_indexes.extend(
                QtCore.QPersistentModelIndex(self._filter_model.mapToSource(i))
                for i in selected.indexes()
            )
        self.status_bar.selection_label.setText(
            f'{len(self.selected_indexes)}/{self.count()} selected'
        )

    def available_space_updated(self, width: int) -> None:
        self.status_bar.column_count_label.setRange(
            1, (width - self.margin_size) // self.gridSize().width()
        )

    def allow_fullscreen(self) -> bool:
        return self._mode == Mode.normal

    def get_tag_count(self) -> Counter[str]:
        untagged = 0
        tag_count: Counter[str] = Counter()
        for row in range(self.visibleCount()):
            index = self.model().index(row, 0)
            tags = index.data(TAGS)
            if not tags:
                untagged += 1
            else:
                tag_count.update(tags)
        tag_count[''] = untagged
        return tag_count

    def set_mode(self, mode: Mode, force: bool = False) -> None:
        if mode != self._mode or force:
            self._mode = mode
            if mode == Mode.normal:
                self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
            elif mode == Mode.select:
                self.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
            self.status_bar.mode = mode.name  # type: ignore
            vs = self.verticalScrollBar()
            if vs.maximum() > 0:
                self.scroll_ratio = vs.value() / vs.maximum()
            self.mode_changed.emit(mode)

    def update_thumb_size(self) -> None:
        if self.config.show_names:
            text_height = int(QtGui.QFontMetricsF(self.font()).height() * 1.5)
        else:
            text_height = 0
        self.setIconSize(THUMB_SIZE + QtCore.QSize(0, text_height))  # type: ignore
        margin = (10 + 3) * 2
        self.setGridSize(THUMB_SIZE + QtCore.QSize(margin, margin + text_height))  # type: ignore

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
            if int(event.modifiers()) == Qt.ControlModifier:
                first = self.model().index(0, 0)
                last = self.model().index(self.model().rowCount() - 1, 0)
                sel = QtCore.QItemSelection(first, last)
                self.selectionModel().select(sel, QtCore.QItemSelectionModel.Select)
                return
            elif event.modifiers() == cast(Qt.KeyboardModifiers,
                                           Qt.ShiftModifier | Qt.ControlModifier):
                self.selectionModel().clearSelection()
                return
        if event.key() in {Qt.Key_Right, Qt.Key_Left, Qt.Key_Up, Qt.Key_Down,
                           Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End,
                           Qt.Key_Space}:
            p1 = self.selectionModel().currentIndex()
            super().keyPressEvent(event)
            p2 = self.selectionModel().currentIndex()
            if self._mode == Mode.select and int(event.modifiers()) & Qt.ShiftModifier:
                s = self.selectionModel().selection()
                s.select(p1, p2)
                self.selectionModel().select(s, QtCore.QItemSelectionModel.Select)
        else:
            event.ignore()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        current = self.selectionModel().currentIndex()
        if current.isValid():
            painter = QtGui.QPainter(self.viewport())
            rect = self.visualRect(current).adjusted(6, 6, -7, -7)
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
            item_text = path.name if self.config.show_names else ''
            item = QtGui.QStandardItem(self.default_icon, item_text)
            item.setEditable(False)
            self.appendRow(item)
            item.setData(path, PATH)
            item.setData(str(path), PATH_STRING)
            item.setData(path.name, FILENAME)
            item.setData(data['size'], FILESIZE)
            item.setData(set(data['tags']), TAGS)
            item.setData((data['w'], data['h']), DIMENSIONS)
            item.setData(jfti.identify_image_format(path), FILEFORMAT)
            imgs.append((n, skip_thumb_cache, path))
            n += 1
            tag_count.update(data['tags'])
            if not data['tags']:
                untagged += 1
        if not self.selectionModel().currentIndex().isValid():
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
