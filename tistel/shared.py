from pathlib import Path
from typing import Callable, Iterator, Type, TypeVar
from typing_extensions import Protocol

from PyQt5 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt5.QtCore import Qt


PATH = Qt.UserRole
DIMENSIONS = Qt.UserRole + 1
FILESIZE = Qt.UserRole + 2
TAGS = Qt.UserRole + 3
TAGSTATE = Qt.UserRole + 4
VISIBLE_TAGS = Qt.UserRole + 5
DEFAULT_COLOR = Qt.UserRole + 6
HOVERING = Qt.UserRole + 7

CONFIG = Path.home() / '.config' / 'tistel' / 'config.json'
CACHE = Path.home() / '.cache' / 'tistel' / 'cache.json'
THUMBNAILS = Path.home() / '.thumbnails' / 'normal'
LOCAL_PATH = Path(__file__).resolve().parent
CSS_FILE = LOCAL_PATH / 'qt.css'


class ListWidget(QtWidgets.QListWidget):
    def __iter__(self) -> Iterator[QtWidgets.QListWidgetItem]:
        for i in range(self.count()):
            yield self.item(i)


class Icon(QtSvg.QSvgWidget):
    def __init__(self, path: str, resolution: int,
                 parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(QtCore.QSize(resolution, resolution))
        with open(path, 'rb') as f:
            data = f.read()
        data = data.replace(b'stroke="currentColor"', b'stroke="#eee"')
        self.load(data)


def clear_layout(layout: QtWidgets.QLayout) -> None:
    while layout.count() > 0:
        item = layout.takeAt(0)
        item.widget().deleteLater()
        del item


def human_filesize(bytenum: int) -> str:
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
