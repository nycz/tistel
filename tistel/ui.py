#!/usr/bin/env python3
from collections import Counter
import enum
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import typing
from typing import (Any, cast, Dict, Iterable, List,
                    Optional, Set, Tuple)
from urllib.parse import quote
import zlib

from PyQt5 import QtGui, QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt

import jfti

PATH = Qt.UserRole
DIMENSION = Qt.UserRole + 1
FILESIZE = Qt.UserRole + 2
TAGS = Qt.UserRole + 3
TAGSTATE = Qt.UserRole + 4
VISIBLE_TAGS = Qt.UserRole + 5

CONFIG = Path.home() / '.config' / 'tistel' / 'config.json'
CACHE = Path.home() / '.cache' / 'tistel' / 'cache.json'
CSS_FILE = 'qt.css'


IMAGE_EXTS = ('.png', '.jpg', '.gif')
IMAGE_MAGICS = ([b'\x89PNG\x0d\x0a\x1a\x0a'],
                [b'\xff\xd8'],
                [b'GIF87a', b'GIF89a'])


class TagState(enum.Enum):
    WHITELISTED = enum.auto()
    BLACKLISTED = enum.auto()
    DEFAULT = enum.auto()


class TagListWidget(QtWidgets.QListWidget):
    tag_state_updated = QtCore.pyqtSignal()
    tag_blacklisted = QtCore.pyqtSignal(str)
    tag_whitelisted = QtCore.pyqtSignal(str)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        return

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.pos())
        if item is not None:
            new_state: Optional[TagState] = None
            state = item.data(TAGSTATE)
            if event.button() == Qt.LeftButton:
                if state == TagState.DEFAULT:
                    new_state = TagState.WHITELISTED
                else:
                    new_state = TagState.DEFAULT
            elif event.button() == Qt.RightButton:
                if state == TagState.DEFAULT:
                    new_state = TagState.BLACKLISTED
                else:
                    new_state = TagState.DEFAULT
            if new_state is not None:
                item.setData(TAGSTATE, new_state)
                update_looks(item)
                self.tag_state_updated.emit()


class TagListWidgetItem(QtWidgets.QListWidgetItem):
    def __lt__(self, other: QtWidgets.QListWidgetItem) -> bool:
        result: bool = self.data(TAGS) < other.data(TAGS)
        return result


def update_looks(tag_item: QtWidgets.QListWidgetItem) -> None:
    count = tag_item.data(TAGS)
    visible_count = tag_item.data(VISIBLE_TAGS)
    state = tag_item.data(TAGSTATE)
    colors = {TagState.WHITELISTED: Qt.darkGreen,
              TagState.DEFAULT: Qt.black,
              TagState.BLACKLISTED: Qt.darkRed}
    color = QtGui.QColor(colors[state])
    if (count == 0 or visible_count == 0) \
            and state != TagState.BLACKLISTED:
        color.setAlphaF(0.3)
        if not tag_item.font().italic():
            font = tag_item.font()
            font.setItalic(True)
            tag_item.setFont(font)
    elif tag_item.font().italic():
        font = tag_item.font()
        font.setItalic(False)
        tag_item.setFont(font)
    tag_item.setForeground(QtGui.QBrush(color))


def read_config() -> Dict[str, Any]:
    if not CONFIG.exists():
        default_config: Dict[str, Any] = {'directories': []}
        if not CONFIG.parent.exists():
            CONFIG.parent.mkdir(parents=True)
        CONFIG.write_text(json.dumps(default_config, indent=2))
        return default_config
    else:
        config: Dict[str, Any] = json.loads(CONFIG.read_text())
        return config


def extract_metadata(path: Path) -> Tuple[List[str], Tuple[int, int]]:
    try:
        tags = sorted(jfti.read_tags(path))
    except Exception:
        print(path)
        raise
    size = QtGui.QImage(str(path)).size()
    # TODO: maybe get size from jfti too?
    return tags, (size.width(), size.height())


def png_text_chunk(name: bytes, text: bytes) -> bytes:
    header_and_data = b'tEXt%s\x00%s' % (name, text)
    length = struct.pack('>I', len(header_and_data) - 4)
    crc_bytes = struct.pack('>I', zlib.crc32(header_and_data))
    return length + header_and_data + crc_bytes


def try_to_load_image(path: Path
                      ) -> Tuple[Optional[QtGui.QPixmap], Optional[str]]:
    pixmap = QtGui.QPixmap(str(path))
    if not pixmap.isNull():
        return pixmap, path.suffix.lower()
    else:
        with path.open('rb') as f:
            magic_data = f.read(8)

        for img_format, magics in zip(IMAGE_EXTS, IMAGE_MAGICS):
            for magic in magics:
                if magic == magic_data[:len(magic)]:
                    pixmap = QtGui.QPixmap(str(path),
                                           format=img_format[1:].upper())
                    if not pixmap.isNull():
                        return pixmap, img_format
    return None, None


def generate_thumbnail(thumb_path: Path, image_path: Path,
                       uri_path: bytes) -> bool:
    pngbytes = QtCore.QByteArray()
    buf = QtCore.QBuffer(pngbytes)
    pixmap, img_format = try_to_load_image(image_path)
    if pixmap is None:
        return False
    scaled_pixmap = pixmap.scaled(128, 128,
                                  aspectRatioMode=QtCore.Qt.KeepAspectRatio,
                                  transformMode=QtCore.Qt.SmoothTransformation)
    scaled_pixmap.save(buf, 'PNG')
    data = pngbytes.data()
    # let's figure out where to insert our P-P-P-PAYLOAD *obnoxious air horns*
    offset = 8
    first_chunk_length = struct.unpack('>I', data[offset:offset+4])[0]
    offset += 12 + first_chunk_length
    mtime = png_text_chunk(b'Thumb::MTime',
                           str(int(image_path.stat().st_mtime)).encode())
    uri = png_text_chunk(b'Thumb::URI', uri_path)
    software = png_text_chunk(b'Software', b'imgview')
    data = data[:offset] + mtime + uri + software + data[offset:]
    thumb_path.write_bytes(data)
    thumb_path.chmod(0o600)
    return True


class ImageLoader(QtCore.QObject):
    thumbnail_ready = QtCore.pyqtSignal(int, int, QtGui.QIcon)

    def __init__(self) -> None:
        super().__init__()
        self.cache_path = Path.home() / '.thumbnails' / 'normal'
        fail_thumb = QtGui.QPixmap(192, 128)
        fail_thumb.fill(QtGui.QColor(QtCore.Qt.darkRed))
        self.fail_icon = QtGui.QIcon(fail_thumb)
        self.cached_thumbs: Dict[Path, QtGui.QIcon] = {}

    def load_image(self, batch: int, imgs: Iterable[Tuple[int, Path]]) -> None:
        for index, path in imgs:
            if path in self.cached_thumbs:
                self.thumbnail_ready.emit(index, batch,
                                          self.cached_thumbs[path])
                continue
            m = hashlib.md5()
            uri = b'file://' + quote(str(path)).encode()
            m.update(uri)
            thumb_path = self.cache_path / (m.hexdigest() + '.png')
            if not thumb_path.is_file():
                success = generate_thumbnail(thumb_path, path, uri)
                if success:
                    icon = QtGui.QIcon(str(thumb_path))
                    self.cached_thumbs[path] = icon
                else:
                    icon = self.fail_icon
                self.thumbnail_ready.emit(index, batch, icon)
            else:
                icon = QtGui.QIcon(str(thumb_path))
                self.cached_thumbs[path] = icon
                self.thumbnail_ready.emit(index, batch, icon)


class MainWindow(QtWidgets.QMainWindow):
    image_queued = QtCore.pyqtSignal(int, list)

    def __init__(self, config: Dict[str, Any],
                 activation_event: QtCore.pyqtSignal) -> None:
        super().__init__()
        # Settings
        self.setWindowTitle('tistel')
        cast(pyqtSignal, QtWidgets.QShortcut(QtGui.QKeySequence('Escape'),
                                             self).activated
             ).connect(self.close)
        self.config = config
        self.paths = {Path(p).expanduser() for p in config['directories']}

        # Main layout
        splitter = QtWidgets.QSplitter(self)
        self.setCentralWidget(splitter)

        # Left column - tags/files/dates and info
        self.left_column = LeftColumn(self)
        splitter.addWidget(self.left_column)

        # Middle column - thumbnails
        default_thumb = QtGui.QPixmap(192, 128)
        default_thumb.fill(QtGui.QColor(QtCore.Qt.gray))
        self.default_icon = QtGui.QIcon(default_thumb)

        self.thumb_loader_thread = QtCore.QThread()
        cast(QtCore.pyqtSignal, QtWidgets.QApplication.instance().aboutToQuit
             ).connect(self.thumb_loader_thread.quit)
        self.thumb_loader = ImageLoader()
        self.thumb_loader.moveToThread(self.thumb_loader_thread)
        self.image_queued.connect(self.thumb_loader.load_image)
        self.thumb_loader.thumbnail_ready.connect(self.add_thumbnail)
        self.thumb_loader_thread.start()
        self.thumb_view = QtWidgets.QListWidget(splitter)
        self.thumb_view.setViewMode(QtWidgets.QListView.IconMode)
        self.thumb_view.setIconSize(QtCore.QSize(192, 128))
        self.thumb_view.setGridSize(QtCore.QSize(256, 160))
        self.thumb_view.setSpacing(10)
        self.thumb_view.setMovement(QtWidgets.QListWidget.Static)
        self.thumb_view.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.thumb_view.setStyleSheet('background: black; color: white')

        splitter.addWidget(self.thumb_view)
        splitter.setStretchFactor(1, 2)

        self.left_column.tag_list.tag_state_updated.connect(
            self.update_tag_filter)

        # Right column - big image
        self.image_view = ImagePreview(splitter)
        self.image_view.setStyleSheet('background: black; color: white')

        def load_big_image(current: QtWidgets.QListWidgetItem,
                           prev: QtWidgets.QListWidgetItem) -> None:
            self.image_view.setPixmap(QtGui.QPixmap(str(current.data(PATH))))

        cast(QtCore.pyqtSignal, self.thumb_view.currentItemChanged
             ).connect(load_big_image)
        splitter.addWidget(self.image_view)
        splitter.setStretchFactor(2, 1)

        # Settings dialog
        self.settings_dialog = SettingsWindow(self, self.paths)

        def show_settings_window() -> None:
            self.settings_dialog.paths = self.paths.copy()
            result = self.settings_dialog.exec_()
            if result == QtWidgets.QDialog.Accepted:
                self.paths = self.settings_dialog.paths
                self.config['directories'] = [str(p) for p in self.paths]
                CONFIG.write_text(json.dumps(self.config, indent=2))

        cast(QtCore.pyqtSignal, self.left_column.settings_button.clicked
             ).connect(show_settings_window)

        # Finalize
        self.batch = 0
        self.index_images()
        self.load_index()
        self.show()

    def update_tag_filter(self) -> None:
        whitelist = set()
        blacklist = set()
        untagged_state = TagState.DEFAULT
        tag_count: typing.Counter[str] = Counter()
        for i in range(self.left_column.tag_list.count()):
            tag_item = self.left_column.tag_list.item(i)
            state = tag_item.data(TAGSTATE)
            tag = tag_item.data(PATH)
            if tag == '':
                untagged_state = state
            elif state == TagState.WHITELISTED:
                whitelist.add(tag)
            elif state == TagState.BLACKLISTED:
                blacklist.add(tag)
        untagged = 0
        for i in range(self.thumb_view.count()):
            item = self.thumb_view.item(i)
            tags = item.data(TAGS)
            if (untagged_state == TagState.WHITELISTED and tags) \
                    or (untagged_state == TagState.BLACKLISTED and not tags) \
                    or (whitelist and not whitelist.issubset(tags)) \
                    or (blacklist and not blacklist.isdisjoint(tags)):
                if not item.isHidden():
                    item.setHidden(True)
            else:
                if not tags:
                    untagged += 1
                else:
                    tag_count.update(tags)
                if item.isHidden():
                    item.setHidden(False)
        tag_count[''] = untagged
        self.left_column.update_tags(tag_count)

    def load_index(self) -> None:
        if not CACHE.exists():
            return
        self.thumb_view.clear()
        self.batch += 1
        imgs = []
        cache = json.loads(CACHE.read_text())
        tag_count: typing.Counter[str] = Counter()
        root_paths = [str(p) for p in self.paths]
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
            item = QtWidgets.QListWidgetItem(self.default_icon,
                                             path.name)
            self.thumb_view.addItem(item)
            item.setData(PATH, path)
            item.setData(TAGS, set(data['tags']))
            imgs.append((n, path))
            n += 1
            tag_count.update(data['tags'])
            if not data['tags']:
                untagged += 1
        if self.thumb_view.currentItem() is None:
            self.thumb_view.setCurrentRow(0)
        self.image_queued.emit(self.batch, imgs)
        self.tags = [('', untagged)]
        for tag, count in tag_count.most_common():
            self.tags.append((tag, count))
        self.left_column.set_tags(self.tags)

    def index_images(self) -> None:
        if CACHE.exists():
            cache = json.loads(CACHE.read_text())
        else:
            cache = {'updated': time.time(), 'images': {}}
        cached_images = cache['images']
        image_paths = []
        for root_path in self.paths:
            for path in root_path.rglob('**/*'):
                if path.suffix.lower() not in {'.png', '.jpg'}:
                    continue
                image_paths.append(path)
        for path in image_paths:
            path_str = str(path)
            stat = path.stat()
            if path_str in cached_images \
                    and stat.st_mtime == cached_images[path_str]['mtime'] \
                    and stat.st_size == cached_images[path_str]['size']:
                continue
            try:
                tags, (width, height) = extract_metadata(path)
            except OSError:
                continue
            cached_images[path_str] = {
                'tags': tags,
                'size': stat.st_size,
                'w': width,
                'h': height,
                'mtime': stat.st_mtime,
                'ctime': stat.st_ctime
            }
        if not CACHE.parent.exists():
            CACHE.parent.mkdir(parents=True)
        CACHE.write_text(json.dumps(cache))

    def add_thumbnail(self, index: int, batch: int, icon: QtGui.QIcon) -> None:
        if batch != self.batch:
            return
        item = self.thumb_view.item(index)
        item.setIcon(icon)
        item.setSizeHint(QtCore.QSize(256, 160))


class LeftColumn(QtWidgets.QWidget):
    tag_selected = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)

        # Tab bar
        self.tab_bar = QtWidgets.QTabBar(self)
        self.tab_bar.addTab('Tags')
        self.tab_bar.addTab('Files')
        self.tab_bar.addTab('Dates')
        layout.addWidget(self.tab_bar)

        # Splitter between stack and info
        splitter = QtWidgets.QSplitter(self)
        layout.addWidget(splitter)

        # Stack widget (content controlled by the tab bar)
        self.nav_stack = QtWidgets.QStackedWidget(splitter)
        splitter.addWidget(self.nav_stack)

        # Tag list
        self.tag_list = TagListWidget(self.nav_stack)
        self.tag_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.nav_stack.addWidget(self.tag_list)

        # Info widget
        self.info_box = QtWidgets.QWidget(splitter)
        splitter.addWidget(self.info_box)

        # Settings button at the bottom
        bottom_row = QtWidgets.QHBoxLayout()
        self.settings_button = QtWidgets.QPushButton('Settings', self)
        bottom_row.addWidget(self.settings_button)
        layout.addLayout(bottom_row)

    def set_tags(self, tags: List[Tuple[str, int]]) -> None:
        self.tag_list.clear()
        for tag, count in tags:
            item = TagListWidgetItem(f'{tag or "Untagged"} ({count})')
            item.setData(PATH, tag)
            item.setData(TAGS, count)
            item.setData(VISIBLE_TAGS, count)
            item.setData(TAGSTATE, TagState.DEFAULT)
            self.tag_list.addItem(item)
        self.tag_list.sortItems(Qt.DescendingOrder)

    def update_tags(self, tag_count: Dict[str, int]) -> None:
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            tag = item.data(PATH)
            new_count = tag_count[tag]
            item.setData(VISIBLE_TAGS, new_count)
            item.setText(f'{tag or "Untagged"} '
                         f'({new_count}/{item.data(TAGS)})')
            update_looks(item)


class ImagePreview(QtWidgets.QLabel):
    change_image = QtCore.pyqtSignal(int)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.fail = False
        self.image: Optional[QtGui.QPixmap] = None
        self.animation: Optional[QtGui.QMovie] = None
        self.animation_size: Optional[QtCore.QSize] = None
        self.current_frame: Optional[QtGui.QPixmap] = None

    def sizeHint(self) -> QtCore.QSize:
        # TODO: dont hardcode this
        return QtCore.QSize(300, 100)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        super().wheelEvent(event)
        if event.angleDelta().y() > 0:
            self.change_image.emit(-1)
        else:
            self.change_image.emit(1)

    def resize_keep_ratio(self, size: QtCore.QSize) -> QtCore.QSize:
        width, height = size.width(), size.height()
        total_width, total_height = self.width(), self.height()
        total_ratio = total_width / total_height
        ratio = width / height
        new_height: float
        new_width: float
        # if height is the biggest
        if ratio < total_ratio:
            new_height = total_height
            new_width = width / height * new_height
        # if width is the biggest
        else:
            new_width = total_width
            new_height = height / width * new_width
        return QtCore.QSize(int(new_width), int(new_height))

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        w, h = self.width(), self.height()
        if self.current_frame is not None:
            pw, ph = self.current_frame.width(), self.current_frame.height()
            x = (w - pw) // 2
            y = (h - ph) // 2
            painter.drawPixmap(x, y, self.current_frame)
        if self.fail:
            painter.setPen(QtGui.QPen(QtGui.QBrush(Qt.red), 10))
            painter.drawLine(0, 0, w, h)
            painter.drawLine(0, w, 0, h)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        if self.image is not None:
            self.update_image_size()
        elif self.animation is not None:
            self.update_animation_size()
        super().resizeEvent(event)

    def clear(self) -> None:
        self.image = self.animation = self.current_frame = None
        self.fail = False
        self.update()

    def set_fail(self) -> None:
        self.image = self.animation = self.current_frame = None
        self.fail = True
        self.update()

    def new_frame(self, frame: QtGui.QPixmap) -> None:
        if self.animation is not None:
            self.current_frame = self.animation.currentPixmap()
            self.update()

    def set_animation(self, animation: QtGui.QMovie) -> None:
        self.image = None
        self.fail = False
        self.animation = animation
        cast(pyqtSignal, self.animation.frameChanged).connect(self.new_frame)
        self.animation.start()
        self.animation_size = self.animation.currentImage().size()
        self.update_animation_size()

    def update_animation_size(self) -> None:
        if self.animation_size is not None and self.animation is not None:
            size = self.resize_keep_ratio(self.animation_size)
            self.animation.setScaledSize(size)
            self.update()

    def setPixmap(self, image: QtGui.QPixmap) -> None:
        self.image = image
        self.fail = False
        self.animation = None
        self.update_image_size()

    def update_image_size(self) -> None:
        if self.image is not None:
            self.current_frame = self.image.scaled(
                self.size(),
                aspectRatioMode=Qt.KeepAspectRatio,
                transformMode=QtCore.Qt.SmoothTransformation
            )
            self.update()


class SettingsWindow(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget,
                 paths: Iterable[Path]) -> None:
        super().__init__(parent)
        self.setWindowTitle('Settings')
        # Layout
        self.heading_label = QtWidgets.QLabel('Image directories')
        layout = QtWidgets.QVBoxLayout(self)
        # Directory buttons
        hbox = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton('Add directory...', self)
        cast(pyqtSignal, self.add_button.clicked).connect(self.add_directory)
        hbox.addWidget(self.add_button)
        self.remove_button = QtWidgets.QPushButton('Remove directory', self)
        self.remove_button.setEnabled(False)
        cast(pyqtSignal, self.remove_button.clicked
             ).connect(self.remove_directories)
        hbox.addWidget(self.remove_button)
        layout.addLayout(hbox)
        # Path list
        self.path_list = QtWidgets.QListWidget(self)
        self.path_list.setSortingEnabled(True)
        self.path_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.paths = paths
        layout.addWidget(self.path_list)
        # Action buttons
        layout.addSpacing(10)
        btm_hbox = QtWidgets.QHBoxLayout()
        self.cancel_button = QtWidgets.QPushButton('Cancel', self)
        cast(pyqtSignal, self.cancel_button.clicked).connect(self.reject)
        btm_hbox.addWidget(self.cancel_button)
        btm_hbox.addStretch()
        self.save_button = QtWidgets.QPushButton('Save', self)
        cast(pyqtSignal, self.save_button.clicked).connect(self.accept)
        btm_hbox.addWidget(self.save_button)
        layout.addLayout(btm_hbox)

        def on_selection_change() -> None:
            self.remove_button.setEnabled(
                bool(self.path_list.selectedItems()))
        cast(pyqtSignal, self.path_list.itemSelectionChanged
             ).connect(on_selection_change)

    @property
    def paths(self) -> Set[Path]:
        out = set()
        for i in range(self.path_list.count()):
            out.add(Path(self.path_list.item(i).text()))
        return out

    @paths.setter
    def paths(self, paths: Iterable[Path]) -> None:
        self.path_list.clear()
        self.path_list.addItems(sorted(str(p) for p in paths))

    def add_directory(self) -> None:
        roots = QtCore.QStandardPaths.standardLocations(
            QtCore.QStandardPaths.PicturesLocation)
        root = roots[0] if roots else str(Path.home())
        new_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Choose a directory', root)
        if new_dir:
            self.path_list.addItem(new_dir)

    def remove_directories(self) -> None:
        for item in self.path_list.selectedItems():
            self.path_list.takeItem(self.path_list.row(item))


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()

    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)

    class AppEventFilter(QtCore.QObject):
        activation_event = QtCore.pyqtSignal()

        def eventFilter(self, object: QtCore.QObject,
                        event: QtCore.QEvent) -> bool:
            if event.type() == QtCore.QEvent.ApplicationActivate:
                self.activation_event.emit()
            return False
    event_filter = AppEventFilter()
    app.installEventFilter(event_filter)

    config = read_config()
    window = MainWindow(config, event_filter.activation_event)
    app.setActiveWindow(window)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
