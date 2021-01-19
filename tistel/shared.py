from __future__ import annotations
import enum
import itertools
import json
from dataclasses import dataclass
from pathlib import PosixPath, Path
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional, TypeVar, Union, cast

from libsyntyche.widgets import Signal2, mk_signal2
from PyQt5 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt5.QtCore import Qt

# mypy: disallow-any-expr

_data_ids = itertools.count(start=Qt.UserRole)

PATH = next(_data_ids)
DIMENSIONS = next(_data_ids)
FILE_SIZE = next(_data_ids)
TAGS = next(_data_ids)
TAG_STATE = next(_data_ids)
TAG_NAME = next(_data_ids)
TAG_COUNT = next(_data_ids)
VISIBLE_TAG_COUNT = next(_data_ids)
DEFAULT_COLOR = next(_data_ids)
HOVERING = next(_data_ids)
FILE_FORMAT = next(_data_ids)
PATH_STRING = next(_data_ids)
FILE_NAME = next(_data_ids)

_home = Path.home()  # type: ignore
CONFIG = _home / '.config' / 'tistel' / 'config.json'
CACHE = _home / '.cache' / 'tistel' / 'cache.json'
THUMBNAILS = _home / '.thumbnails' / 'normal'
DATA_PATH = Path(__file__).resolve().parent / 'data'
CSS_FILE = DATA_PATH / 'qt.css'


class TagState(enum.Enum):
    WHITELISTED = enum.auto()
    BLACKLISTED = enum.auto()
    DEFAULT = enum.auto()


@dataclass
class CachedImageData:
    tags: List[str]
    size: int
    w: int
    h: int
    mtime: float
    ctime: float


@dataclass
class Cache:
    updated: float
    images: Dict[Path, CachedImageData]

    @classmethod
    def load(cls) -> Cache:
        data: Dict[str, Union[float, Dict[str, Union[List[str], int, float]]]] = \
            json.loads(CACHE.read_text())
        return Cache(
            updated=cast(float, data['updated']),
            images={
                Path(k): CachedImageData(
                    tags=v['tags'],
                    size=v['size'],
                    w=v['w'],
                    h=v['h'],
                    mtime=v['mtime'],
                    ctime=v['ctime'],
                )  # **cast(Dict[str, Union[List[str], int, float]], v))
                for k, v in data['images'].items()
            }
        )

    def save(self) -> None:
        if not CACHE.parent.exists():
            CACHE.parent.mkdir(parents=True)
        CACHE.write_text(json.dumps({
            'updated': self.updated,
            'images': {
                str(path): {
                    'tags': img_data.tags,
                    'size': img_data.size,
                    'w': img_data.w,
                    'h': img_data.h,
                    'mtime': img_data.mtime,
                    'ctime': img_data.ctime,
                }
                for path, img_data in self.images.items()
            }
        }))


T = TypeVar('T', bound=QtGui.QStandardItem)

class ListWidget2(QtWidgets.QListView, Generic[T]):
    currentItemChanged: Signal2[Optional[T], Optional[T]] = \
        mk_signal2(object, object)  # type: ignore

    def __init__(self, parent: QtWidgets.QWidget,
                 filter_model: Optional[QtCore.QSortFilterProxyModel] = None) -> None:
        super().__init__(parent)
        self._model = QtGui.QStandardItemModel()
        if filter_model is None:
            self._proxy_model = QtCore.QSortFilterProxyModel()
        else:
            self._proxy_model = filter_model
        self._proxy_model.setDynamicSortFilter(True)
        self._proxy_model.setSourceModel(self._model)
        self.setModel(self._proxy_model)

        def current_item_changed(current: QtCore.QModelIndex,
                                 previous: QtCore.QModelIndex) -> None:
            self.currentItemChanged.emit(
                cast(T, self._model.itemFromIndex(self._proxy_model.mapToSource(current))),
                cast(T, self._model.itemFromIndex(self._proxy_model.mapToSource(previous))),
            )

        cast(Signal2[QtCore.QModelIndex, QtCore.QModelIndex],
             self.selectionModel().currentChanged).connect(current_item_changed)

    def clear(self) -> None:
        self._model.clear()

    def visibleCount(self) -> int:
        return self.model().rowCount()

    def count(self) -> int:
        return self._model.rowCount()

    def visibleItem(self, pos: int) -> T:
        return cast(T, self._model.itemFromIndex(
            self._proxy_model.mapToSource(self.model().index(pos, 0))))

    def item(self, pos: int) -> T:
        return cast(T, self._model.item(pos))

    def itemFromIndex(self, index: QtCore.QModelIndex) -> T:
        return cast(T, self._model.itemFromIndex(self._proxy_model.mapToSource(index)))

    def appendRow(self, item: T) -> None:
        self._model.appendRow(item)

    def insertRow(self, row: int, item: T) -> None:
        self._model.insertRow(row, item)

    def currentRow(self) -> int:
        return self.selectionModel().currentIndex().row()

    def setCurrentRow(self, row: int) -> None:
        self.selectionModel().setCurrentIndex(self.model().index(row, 0),
                                              QtCore.QItemSelectionModel.NoUpdate)

    def items(self) -> Iterable[T]:
        for i in range(self._model.rowCount()):
            yield cast(T, self._model.item(i))

    def visibleItems(self) -> Iterable[T]:
        for i in range(self.model().rowCount()):
            yield self.visibleItem(i)

    def addItem(self, item: T) -> None:
        self._model.appendRow(item)

    def itemAt(self, p: QtCore.QPoint) -> Optional[T]:
        index = self.indexAt(p)
        if index.isValid():
            return cast(T, self._model.itemFromIndex(self._proxy_model.mapToSource(index)))
        return None

    def takeRow(self, pos: int) -> T:
        return cast(T, self._model.takeRow(pos)[0])


class IconWidget(QtSvg.QSvgWidget):
    def __init__(self, name: str, resolution: int,
                 parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(QtCore.QSize(resolution, resolution))
        path = DATA_PATH / 'icons' / f'{name}.svg'
        with open(path, 'rb') as f:
            data = f.read()
        data = data.replace(b'stroke="currentColor"', b'stroke="#eee"')
        self.load(data)


def make_svg_icon(name: str, resolution: int,
                  color: Union[QtGui.QColor, Qt.GlobalColor] = Qt.white
                  ) -> QtGui.QIcon:
    if not isinstance(color, QtGui.QColor):
        color = QtGui.QColor(color)
    color_str = f'{color.red():0>2x}{color.green():0>2x}{color.blue():0>2x}'
    path = DATA_PATH / 'icons' / f'{name}.svg'
    with open(path, 'rb') as f:
        data = f.read()
    data = data.replace(b'stroke="currentColor"',
                        b'stroke="#' + color_str.encode() + b'"')
    renderer = QtSvg.QSvgRenderer(data)
    pixmap = QtGui.QPixmap(resolution, resolution)
    pixmap.fill(Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    icon = QtGui.QIcon(pixmap)
    return icon


def clear_layout(layout: QtWidgets.QLayout) -> None:
    while layout.count() > 0:
        item = layout.takeAt(0)
        if item is not None:
            item.widget().deleteLater()
        del item


def human_filesize(bytenum_int: int) -> str:
    bytenum = float(bytenum_int)
    for t in ['', 'K', 'M', 'G', 'T']:
        if bytenum < 1000:
            break
        bytenum /= 1000
    return f'{bytenum:.1f}{t}'
