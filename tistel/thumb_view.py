import enum
import logging
from pathlib import Path
from typing import Counter, FrozenSet, List, Optional, Set, Tuple, cast

from libsyntyche.widgets import (Signal0, Signal1, Signal2, mk_signal1,
                                 mk_signal2)
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QPoint, Qt, pyqtProperty  # type: ignore

from . import jfti, shared
from .image_loading import THUMB_SIZE, ImageLoader
from .settings import Settings
from .shared import CACHE, Cache, ImageData, ListWidget2, TagState, TagStates


class Mode(enum.Enum):
    normal = enum.auto()
    select = enum.auto()


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
        self.tag_whitelist: FrozenSet[str] = frozenset()
        self.tag_blacklist: FrozenSet[str] = frozenset()
        self.untagged_state: TagState = TagState.DEFAULT

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        source_model = cast(QtGui.QStandardItemModel, self.sourceModel())
        tags = cast(ThumbViewItem, source_model.item(source_row, 0)).tags
        if (self.untagged_state == TagState.WHITELISTED and tags) \
                or (self.untagged_state == TagState.BLACKLISTED and not tags) \
                or (self.tag_whitelist and not self.tag_whitelist.issubset(tags)) \
                or (self.tag_blacklist and not self.tag_blacklist.isdisjoint(tags)):
            return False
        return True

    def set_tag_filter(self, states: TagStates) -> None:
        self.tag_whitelist = states.whitelist
        self.tag_blacklist = states.blacklist
        self.untagged_state = states.untagged_state
        self.invalidateFilter()


class ThumbViewItem(QtGui.QStandardItem):
    @property
    def dimensions(self) -> Tuple[int, int]:
        return cast(Tuple[int, int], self.data(shared.DIMENSIONS))

    @dimensions.setter
    def dimensions(self, dimensions: Tuple[int, int]) -> None:
        self.setData(dimensions, shared.DIMENSIONS)

    @property
    def file_format(self) -> str:
        return cast(str, self.data(shared.FILE_FORMAT))

    @file_format.setter
    def file_format(self, file_format: str) -> None:
        self.setData(file_format, shared.FILE_FORMAT)

    @property
    def file_name(self) -> str:
        return cast(str, self.data(shared.FILE_NAME))

    @file_name.setter
    def file_name(self, file_name: str) -> None:
        self.setData(file_name, shared.FILE_NAME)

    @property
    def file_size(self) -> int:
        return cast(int, self.data(shared.FILE_SIZE))

    @file_size.setter
    def file_size(self, file_size: int) -> None:
        self.setData(file_size, shared.FILE_SIZE)

    @property
    def path(self) -> Path:
        return cast(Path, self.data(shared.PATH))

    @path.setter
    def path(self, path: Path) -> None:
        self.setData(path, shared.PATH)

    @property
    def path_string(self) -> str:
        return cast(str, self.data(shared.PATH_STRING))

    @path_string.setter
    def path_string(self, path_string: str) -> None:
        self.setData(path_string, shared.PATH_STRING)

    @property
    def tags(self) -> Set[str]:
        return cast(Set[str], self.data(shared.TAGS))

    @tags.setter
    def tags(self, tags: Set[str]) -> None:
        self.setData(tags, shared.TAGS)


class ThumbView(ListWidget2[ThumbViewItem]):
    image_queued: Signal2[int, List[Tuple[int, bool, Path]]] = mk_signal2(int, list)
    mode_changed = mk_signal1(Mode)
    image_selected = cast(Signal1[Optional[ImageData]], mk_signal1(object))
    visible_selection_changed = cast(Signal1[List[ImageData]], mk_signal1(list))

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
        self.scroll_ratio: Optional[float] = None
        self.selected_indexes: List[QtCore.QPersistentModelIndex] = []
        self._current_image_color = QtGui.QColor(Qt.green)
        self._selected_image_overlay_color = QtGui.QColor(0, 255, 0, 40)

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
            self.adjust_size(cast(QtWidgets.QWidget, self.parent()).width())

        self.status_bar.column_count_label.valueChanged.connect(update_column_count)
        self.selectionModel().selectionChanged.connect(self.update_selection_info)
        self.update_selection_info()

        self.status_bar.layout().addWidget(shared.make_sort_menu(
            self.status_bar,
            self._filter_model,
            {'Path': shared.PATH_STRING,
             'File name': shared.FILE_NAME,
             'File size': shared.FILE_SIZE},
        ))

        def emit_image_selected(current: Optional[ThumbViewItem],
                                previous: Optional[ThumbViewItem]) -> None:
            self.image_selected.emit(current)

        self.currentItemChanged.connect(emit_image_selected)

        def emit_visible_selection_changed(selected: QtCore.QItemSelection,
                                           deselected: QtCore.QItemSelection) -> None:
            self.visible_selection_changed.emit([
                self.itemFromIndex(index)
                for index in self.selectionModel().selectedIndexes()
            ])

        self.selectionModel().selectionChanged.connect(emit_visible_selection_changed)

    @pyqtProperty(QtGui.QColor)
    def selected_image_overlay_color(self) -> QtGui.QColor:
        return QtGui.QColor(self._selected_image_overlay_color)

    @selected_image_overlay_color.setter  # type: ignore
    def selected_image_overlay_color(self, color: QtGui.QColor) -> None:
        self._selected_image_overlay_color = color

    @pyqtProperty(QtGui.QColor)
    def current_image_color(self) -> QtGui.QColor:
        return QtGui.QColor(self._current_image_color)

    @current_image_color.setter  # type: ignore
    def current_image_color(self, color: QtGui.QColor) -> None:
        self._current_image_color = color

    def set_tag_filter(self, states: TagStates) -> None:
        # Disconnect the selection changed signal to stop it from overwriting
        # the old data when filtering
        self.selectionModel().selectionChanged.disconnect(self.update_selection_info)
        self._filter_model.set_tag_filter(states)
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
                    logging.warning('failed to remove selection index')
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

    def get_tag_count(self) -> Tuple[int, Counter[str]]:
        untagged = 0
        tag_count: Counter[str] = Counter()
        for item in self.visibleItems():
            tags = item.tags
            if not tags:
                untagged += 1
            else:
                tag_count.update(tags)
        return (untagged, tag_count)

    def selectedItems(self) -> List[ImageData]:
        out: List[ImageData] = []
        for p_index in self.selected_indexes:
            out.append(cast(ThumbViewItem,
                            self._model.itemFromIndex(QtCore.QModelIndex(p_index))))
        return out

    @property
    def mode(self) -> Mode:
        return self._mode

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
        modifiers = int(event.modifiers())
        if self._mode == Mode.select:
            if event.key() == Qt.Key_A:
                # Select all
                if modifiers == Qt.ControlModifier:
                    first = self.model().index(0, 0)
                    last = self.model().index(self.model().rowCount() - 1, 0)
                    sel = QtCore.QItemSelection(first, last)
                    self.selectionModel().select(sel, QtCore.QItemSelectionModel.Select)
                    return
                # Deselect all
                elif event.modifiers() == cast(Qt.KeyboardModifiers,
                                               Qt.ShiftModifier | Qt.ControlModifier):
                    self.selectionModel().clearSelection()
                    return
            elif event.key() == Qt.Key_Space:
                super().keyPressEvent(event)
                return

        QAIV = QtWidgets.QAbstractItemView
        movement_keys = [
            ([Qt.Key_Right, Qt.Key_O], QAIV.MoveRight),
            ([Qt.Key_Left, Qt.Key_N], QAIV.MoveLeft),
            ([Qt.Key_Up, Qt.Key_H], QAIV.MoveUp),
            ([Qt.Key_Down, Qt.Key_K], QAIV.MoveDown),
            ([Qt.Key_PageUp], QAIV.MovePageUp),
            ([Qt.Key_PageDown], QAIV.MovePageDown),
            ([Qt.Key_Home], QAIV.MoveHome),
            ([Qt.Key_End], QAIV.MoveEnd),
        ]

        for keys, action in movement_keys:
            if event.key() in keys:
                start_pos = self.selectionModel().currentIndex()
                end_pos = self.moveCursor(action, Qt.NoModifier)
                self.selectionModel().setCurrentIndex(end_pos, QtCore.QItemSelectionModel.NoUpdate)
                if self._mode == Mode.select and modifiers in {Qt.ShiftModifier, Qt.AltModifier}:
                    s = QtCore.QItemSelection(start_pos, end_pos)
                    if modifiers == Qt.ShiftModifier:
                        s.merge(self.selectionModel().selection(),
                                QtCore.QItemSelectionModel.Select)
                        self.selectionModel().select(s, QtCore.QItemSelectionModel.Select)
                    else:
                        self.selectionModel().select(s, QtCore.QItemSelectionModel.Deselect)
                break
        else:
            event.ignore()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self.viewport())
        cur_margin = 5
        sel_margin = int(cur_margin * 2) + 2
        for index in self.selectionModel().selectedIndexes():
            rect = self.visualRect(index).adjusted(sel_margin, sel_margin,
                                                   -sel_margin, -sel_margin)
            painter.fillRect(rect, cast(QtGui.QColor, self.selected_image_overlay_color))

        current = self.selectionModel().currentIndex()
        if current.isValid() and current.row() >= 0:
            rect = self.visualRect(current).adjusted(cur_margin, cur_margin,
                                                     -cur_margin, -cur_margin)
            pen = QtGui.QPen(self.current_image_color)
            pen.setWidth(5)
            pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen)
            length = rect.height() // 6
            xdiff = QPoint(length, 0)
            ydiff = QPoint(0, length)
            tl = rect.topLeft()
            painter.drawPolyline(tl + xdiff, tl, tl + ydiff)
            tr = rect.topRight()
            painter.drawPolyline(tr - xdiff, tr, tr + ydiff)
            bl = rect.bottomLeft()
            painter.drawPolyline(bl + xdiff, bl, bl - ydiff)
            br = rect.bottomRight()
            painter.drawPolyline(br - xdiff, br, br - ydiff)

    def load_index(self, skip_thumb_cache: bool) -> Optional[Tuple[int, Counter[str]]]:
        if not CACHE.exists():
            return None
        self.clear()
        self.batch += 1
        imgs = []
        cache = Cache.load()
        tag_count: Counter[str] = Counter()
        root_paths = [p for p in self.config.active_paths]
        n = 0
        untagged = 0
        for path, data in sorted(cache.images.items()):
            if not path.exists():
                del cache.images[path]
                continue
            for p in root_paths:
                if path.is_relative_to(p):
                    break
            else:
                continue
            item_text = path.name if self.config.show_names else ''
            item = ThumbViewItem(self.default_icon, item_text)
            item.setEditable(False)
            self.appendRow(item)
            item.path = path
            item.path_string = str(path)
            item.file_name = path.name
            item.file_size = data.size
            item.tags = set(data.tags)
            item.dimensions = (data.w, data.h)
            item.file_format = jfti.identify_image_format(path) or ''
            imgs.append((n, skip_thumb_cache, path))
            n += 1
            tag_count.update(data.tags)
            if not data.tags:
                untagged += 1
        if not self.selectionModel().currentIndex().isValid():
            self.setCurrentRow(0)
        self.image_queued.emit(self.batch, imgs)
        total = self.count()
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(0)
            self.progress.show()
        else:
            self.progress.hide()
        self.update_selection_info()
        return (untagged, tag_count)

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
