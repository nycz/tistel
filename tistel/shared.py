import itertools
from pathlib import Path
from typing import (Any, Callable, cast, Iterator, Optional,
                    Type, TypeVar, Union)
from typing_extensions import Protocol

from PyQt5 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt5.QtCore import Qt


_data_ids = itertools.count(start=Qt.UserRole)

PATH = next(_data_ids)
DIMENSIONS = next(_data_ids)
FILESIZE = next(_data_ids)
TAGS = next(_data_ids)
TAGSTATE = next(_data_ids)
TAG_COUNT = next(_data_ids)
VISIBLE_TAGS = next(_data_ids)
DEFAULT_COLOR = next(_data_ids)
HOVERING = next(_data_ids)
FILEFORMAT = next(_data_ids)

CONFIG = Path.home() / '.config' / 'tistel' / 'config.json'
CACHE = Path.home() / '.cache' / 'tistel' / 'cache.json'
THUMBNAILS = Path.home() / '.thumbnails' / 'normal'
LOCAL_PATH = Path(__file__).resolve().parent
CSS_FILE = LOCAL_PATH / 'qt.css'


class ListWidget(QtWidgets.QListWidget):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sort_func: Optional[Callable[['ListWidgetItem',
                                           'ListWidgetItem'], bool]] = None

    def __iter__(self) -> Iterator[QtWidgets.QListWidgetItem]:
        for i in range(self.count()):
            yield self.item(i)


class ListWidgetItem(QtWidgets.QListWidgetItem):
    def __lt__(self, other: QtWidgets.QListWidgetItem) -> bool:
        result: bool
        sort_func = cast(ListWidget, self.listWidget()).sort_func
        if sort_func is not None:
            result = sort_func(self, cast(ListWidgetItem, other))
        else:
            result = super().__lt__(other)
        return result


class IconWidget(QtSvg.QSvgWidget):
    def __init__(self, name: str, resolution: int,
                 parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(QtCore.QSize(resolution, resolution))
        path = LOCAL_PATH / 'icons' / f'{name}.svg'
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
    path = LOCAL_PATH / 'icons' / f'{name}.svg'
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


_T1 = TypeVar('_T1')
_T2 = TypeVar('_T2')
_T3 = TypeVar('_T3')


class Signal0(Protocol):
    def __init__(self) -> None: ...

    def emit(self) -> None: ...

    def connect(self, slot: Callable[[], None]) -> None: ...


class Signal1(Protocol[_T1]):
    def __init__(self, arg_type: Type[_T1]) -> None: ...

    def emit(self, arg: _T1) -> None: ...

    def connect(self, slot: Callable[[_T1], None]) -> None: ...


class Signal2(Protocol[_T1, _T2]):
    def __init__(self, arg1_type: Type[_T1], arg2_type: Type[_T2]) -> None: ...

    def emit(self, arg1: _T1, arg2: _T2) -> None: ...

    def connect(self, slot: Callable[[_T1, _T2], None]) -> None: ...


class Signal3(Protocol[_T1, _T2, _T3]):
    def __init__(self, arg1_type: Type[_T1], arg2_type: Type[_T2],
                 arg3_type: Type[_T3]) -> None: ...

    def emit(self, arg1: _T1, arg2: _T2, arg3: _T3) -> None: ...

    def connect(self, slot: Callable[[_T1, _T2, _T3], None]) -> None: ...
