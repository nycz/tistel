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
from PyQt5.QtCore import pyqtProperty, pyqtSignal, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialogButtonBox

from jfti import jfti

PATH = Qt.UserRole
DIMENSIONS = Qt.UserRole + 1
FILESIZE = Qt.UserRole + 2
TAGS = Qt.UserRole + 3
TAGSTATE = Qt.UserRole + 4
VISIBLE_TAGS = Qt.UserRole + 5
DEFAULT_COLOR = Qt.UserRole + 6

CONFIG = Path.home() / '.config' / 'tistel' / 'config.json'
CACHE = Path.home() / '.cache' / 'tistel' / 'cache.json'
THUMBNAILS = Path.home() / '.thumbnails' / 'normal'
LOCAL_PATH = Path(__file__).resolve().parent
CSS_FILE = LOCAL_PATH / 'qt.css'


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

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self._default_color = QColor(Qt.white)
        self._whitelisted_color = QColor(Qt.green)
        self._blacklisted_color = QColor(Qt.red)

    @pyqtProperty(QColor)
    def default_color(self) -> QColor:
        return self._default_color

    @default_color.setter  # type: ignore
    def default_color(self, color: QColor) -> None:
        self._default_color = color

    @pyqtProperty(QColor)
    def whitelisted_color(self) -> QColor:
        return self._whitelisted_color

    @whitelisted_color.setter  # type: ignore
    def whitelisted_color(self, color: QColor) -> None:
        self._whitelisted_color = color

    @pyqtProperty(QColor)
    def blacklisted_color(self) -> QColor:
        return self._blacklisted_color

    @blacklisted_color.setter  # type: ignore
    def blacklisted_color(self, color: QColor) -> None:
        self._blacklisted_color = color

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
    parent = tag_item.listWidget()
    colors = {TagState.WHITELISTED: parent.property('whitelisted_color'),
              TagState.DEFAULT: parent.property('default_color'),
              TagState.BLACKLISTED: parent.property('blacklisted_color')}
    color = colors[state]
    font = tag_item.font()
    if (count == 0 or visible_count == 0) \
            and state != TagState.BLACKLISTED:
        color.setAlphaF(0.4)
        if not tag_item.font().italic():
            font.setItalic(True)
    elif tag_item.font().italic():
        font.setItalic(False)
    if state != TagState.DEFAULT:
        font.setBold(True)
    elif font.bold():
        font.setBold(False)
    tag_item.setFont(font)
    tag_item.setForeground(color)


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
        print(f'Getting metadata failed in: {path}')
        raise
    size = jfti.dimensions(path)
    return tags, size


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
    scaled_pixmap = pixmap.scaled(192, 128,
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
        self.base_thumb = QtGui.QImage(192, 128, QtGui.QImage.Format_ARGB32)
        self.base_thumb.fill(Qt.transparent)
        self.fail_icon = QtGui.QIcon(fail_thumb)
        self.cached_thumbs: Dict[Path, QtGui.QIcon] = {}

    def make_thumb(self, path: Path) -> QtGui.QIcon:
        img = self.base_thumb.copy()
        thumb = QtGui.QImage(str(path))
        painter = QtGui.QPainter(img)
        painter.drawImage(int((img.width() - thumb.width()) / 2),
                          int((img.height() - thumb.height()) / 2),
                          thumb)
        painter.end()
        return QtGui.QIcon(QtGui.QPixmap.fromImage(img))

    def load_image(self, batch: int,
                   imgs: Iterable[Tuple[int, bool, Path]]) -> None:
        for index, skip_cache, path in imgs:
            if not skip_cache and path in self.cached_thumbs:
                self.thumbnail_ready.emit(index, batch,
                                          self.cached_thumbs[path])
                continue
            m = hashlib.md5()
            uri = b'file://' + quote(str(path)).encode()
            m.update(uri)
            thumb_path = self.cache_path / (m.hexdigest() + '.png')
            if skip_cache or not thumb_path.is_file():
                success = generate_thumbnail(thumb_path, path, uri)
                if success:
                    icon = self.make_thumb(thumb_path)
                    self.cached_thumbs[path] = icon
                else:
                    icon = self.fail_icon
                self.thumbnail_ready.emit(index, batch, icon)
            else:
                icon = self.make_thumb(thumb_path)
                self.cached_thumbs[path] = icon
                self.thumbnail_ready.emit(index, batch, icon)


class ProgressBar(QtWidgets.QProgressBar):
    def text(self) -> str:
        value = self.value()
        total = self.maximum()
        return (f'Reloading thumbnails: {value}/{total}'
                f' ({value/max(total, 1):.0%})')


class IndexerProgress(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setModal(True)
        layout = QtWidgets.QVBoxLayout(self)
        self.status_text = QtWidgets.QLabel(self)
        layout.addWidget(self.status_text)
        self.counter = QtWidgets.QLabel(self)
        layout.addWidget(self.counter)
        self.progress_bar = QtWidgets.QProgressBar(self)
        layout.addWidget(self.progress_bar)

    def update_status(self, text: str, current: int, total: int) -> None:
        self.status_text.setText(text)
        if current >= 0 and total >= 0:
            if not self.progress_bar.isVisible():
                self.progress_bar.show()
            self.counter.setText(f'{current}/{total}')
            self.progress_bar.setValue(current)
            self.progress_bar.setMaximum(total)
        elif current >= 0:
            if self.progress_bar.isVisible():
                self.progress_bar.hide()
            self.counter.setText(str(current))


class Indexer(QtCore.QObject):
    status_report = pyqtSignal(str, int, int)
    done = pyqtSignal()

    def index_images(self, paths: Iterable[Path]) -> None:
        if CACHE.exists():
            self.status_report.emit('Loading cache', -1, -1)
            cache = json.loads(CACHE.read_text())
        else:
            cache = {'updated': time.time(), 'images': {}}
        cached_images = cache['images']
        image_paths = []
        count = 0
        for root_path in paths:
            for path in root_path.rglob('**/*'):
                if path.suffix.lower() not in {'.png', '.jpg'}:
                    continue
                count += 1
                self.status_report.emit('Searching for images', count, -1)
                image_paths.append(path)
        total = count
        count = 0
        for path in image_paths:
            self.status_report.emit('Indexing image', count, total)
            count += 1
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
        self.status_report.emit('Saving cache', -1, -1)
        CACHE.write_text(json.dumps(cache))
        self.done.emit()


class MainWindow(QtWidgets.QWidget):
    image_queued = pyqtSignal(int, list)
    start_indexing = pyqtSignal(set)

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
        self.tag_count: typing.Counter[str] = Counter()

        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QtWidgets.QSplitter(self)
        layout.addWidget(splitter)

        # Statusbar
        self.progress = ProgressBar(self)
        self.progress.hide()
        layout.addWidget(self.progress)

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
        self.thumb_view.setUniformItemSizes(True)
        self.thumb_view.setViewMode(QtWidgets.QListView.IconMode)
        self.thumb_view.setIconSize(QtCore.QSize(192, 128))
        self.thumb_view.setGridSize(QtCore.QSize(210, 160))
        self.thumb_view.setMovement(QtWidgets.QListWidget.Static)
        self.thumb_view.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.thumb_view.setObjectName('thumb_view')
        self.thumb_view.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)

        splitter.addWidget(self.thumb_view)
        splitter.setStretchFactor(1, 2)

        self.left_column.tag_list.tag_state_updated.connect(
            self.update_tag_filter)

        # Right column - big image
        self.image_view = ImagePreview(splitter)
        self.image_view.setObjectName('image_view')

        def load_big_image(current: QtWidgets.QListWidgetItem,
                           prev: QtWidgets.QListWidgetItem) -> None:
            if current and not current.isHidden():
                self.image_view.setPixmap(
                    QtGui.QPixmap(str(current.data(PATH))))
                self.left_column.set_info(current)
            else:
                self.image_view.setPixmap(None)
                self.left_column.set_info(None)

        cast(pyqtSignal, self.thumb_view.currentItemChanged
             ).connect(load_big_image)

        def change_image(diff: int) -> None:
            current = max(self.thumb_view.currentRow(), 0)
            total = self.thumb_view.count()
            i = current
            item = self.thumb_view.item
            for _ in range(total + 1):
                i = (i + diff) % total
                if not item(i).isHidden():
                    self.thumb_view.setCurrentRow(i)
                    return
                elif current == i:
                    self.image_view.setPixmap(None)
                    return

        self.image_view.change_image.connect(change_image)
        splitter.addWidget(self.image_view)
        splitter.setStretchFactor(2, 1)

        # Settings dialog
        self.settings_dialog = SettingsWindow(self, self.paths)

        def show_settings_window() -> None:
            self.settings_dialog.paths = self.paths.copy()
            self.settings_dialog.reset_thumbnails = False
            result = self.settings_dialog.exec_()
            if result == QtWidgets.QDialog.Accepted:
                self.paths = self.settings_dialog.paths
                self.config['directories'] = [str(p) for p in self.paths]
                CONFIG.write_text(json.dumps(self.config, indent=2))
                if self.settings_dialog.reset_thumbnails:
                    self.load_index(True)

        cast(pyqtSignal, self.left_column.settings_button.clicked
             ).connect(show_settings_window)

        # Tagging dialog
        self.tagging_dialog = TaggingWindow(self)

        def show_tagging_dialog() -> None:
            selected_items = self.thumb_view.selectedItems()
            self.tagging_dialog.set_up(self.tag_count, selected_items)
            result = self.tagging_dialog.exec_()
            if result:
                new_tag_count: typing.Counter[str] = Counter()
                updated_files = {}
                tags_to_add = self.tagging_dialog.get_tags_to_add()
                tags_to_remove = self.tagging_dialog.get_tags_to_remove()
                created_tags = tags_to_add - set(self.tag_count.keys())
                progress_dialog = QtWidgets.QProgressDialog(
                    'Tagging images...', 'Cancel',
                    0, len(selected_items), self)
                progress_dialog.setWindowModality(Qt.WindowModal)
                progress_dialog.setMinimumDuration(0)

                for n, item in enumerate(selected_items):
                    progress_dialog.setValue(n)
                    old_tags = item.data(TAGS)
                    new_tags = (old_tags | tags_to_add) - tags_to_remove
                    if old_tags != new_tags:
                        added_tags = new_tags - old_tags
                        removed_tags = old_tags - new_tags
                        new_tag_count.update({t: 1 for t in added_tags})
                        new_tag_count.update({t: -1 for t in removed_tags})
                        path = item.data(PATH)
                        jfti.set_tags(path, new_tags)
                        item.setData(TAGS, new_tags)
                        updated_files[item.data(PATH)] = new_tags
                    if progress_dialog.wasCanceled():
                        break
                progress_dialog.setValue(len(selected_items))
                if updated_files:
                    # Update the cache
                    if not CACHE.exists():
                        print('WARNING: no cache! probably reload ??')
                        return
                    cache = json.loads(CACHE.read_text())
                    cache['updated'] = time.time()
                    img_cache = cache['images']
                    for fname, tags in updated_files.items():
                        path_str = str(fname)
                        if path_str not in img_cache:
                            print('WARNING: img not in cache ??')
                            continue
                        img_cache[path_str]['tags'] = list(tags)
                    CACHE.write_text(json.dumps(cache))
                    # Update the tag list
                    self.tag_count.update(new_tag_count)
                    untagged_item = self.left_column.tag_list.takeItem(0)
                    tag_items_to_delete = []
                    for i in range(self.left_column.tag_list.count()):
                        tag_item = self.left_column.tag_list.item(i)
                        tag = tag_item.data(PATH)
                        diff = new_tag_count.get(tag, 0)
                        if diff != 0:
                            new_count = tag_item.data(TAGS) + diff
                            if new_count <= 0:
                                tag_items_to_delete.append(i)
                            tag_item.setData(TAGS, new_count)
                    # Get rid of the items in reverse order
                    # to not mess up the numbers
                    for i in reversed(tag_items_to_delete):
                        self.left_column.tag_list.takeItem(i)
                    for tag in created_tags:
                        count = new_tag_count.get(tag, 0)
                        if count > 0:
                            self.left_column.create_tag(tag, count)
                    self.left_column.tag_list.sortItems(Qt.DescendingOrder)
                    self.left_column.tag_list.insertItem(0, untagged_item)
                    self.update_tag_filter()

        cast(pyqtSignal, QtWidgets.QShortcut(QtGui.QKeySequence('Ctrl+T'),
                                             self).activated
             ).connect(show_tagging_dialog)

        # Reloading
        self.indexer = Indexer()
        self.indexer_thread = QtCore.QThread()
        cast(QtCore.pyqtSignal, QtWidgets.QApplication.instance().aboutToQuit
             ).connect(self.indexer_thread.quit)
        self.indexer.moveToThread(self.indexer_thread)
        self.indexer.done.connect(self.load_index)
        self.start_indexing.connect(self.indexer.index_images)
        self.indexer_thread.start()

        self.indexer_progressbar = IndexerProgress(self)
        self.indexer.status_report.connect(self.indexer_progressbar.update_status)

        cast(pyqtSignal, self.left_column.reload_button.clicked
             ).connect(self.index_images)

        # Finalize
        self.batch = 0
        self.thumbnails_done = 0
        self.show()
        self.index_images()

    def index_images(self) -> None:
        self.start_indexing.emit(self.paths)
        self.indexer_progressbar.show()

    def load_index(self, skip_cache: bool = False) -> None:
        self.indexer_progressbar.accept()
        if not CACHE.exists():
            return
        self.thumb_view.clear()
        self.batch += 1
        imgs = []
        cache = json.loads(CACHE.read_text())
        self.tag_count.clear()
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
            item.setSizeHint(QtCore.QSize(192, 160))
            self.thumb_view.addItem(item)
            item.setData(PATH, path)
            item.setData(TAGS, set(data['tags']))
            item.setData(DIMENSIONS, (data['w'], data['h']))
            imgs.append((n, skip_cache, path))
            n += 1
            self.tag_count.update(data['tags'])
            if not data['tags']:
                untagged += 1
        if self.thumb_view.currentItem() is None:
            self.thumb_view.setCurrentRow(0)
        self.image_queued.emit(self.batch, imgs)
        self.tags = [('', untagged)]
        for tag, count in self.tag_count.most_common():
            self.tags.append((tag, count))
        self.left_column.set_tags(self.tags)
        total = self.thumb_view.count()
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(0)
            self.progress.show()
        else:
            self.progress.hide()

    def add_thumbnail(self, index: int, batch: int, icon: QtGui.QIcon) -> None:
        if batch != self.batch:
            return
        item = self.thumb_view.item(index)
        item.setIcon(icon)
        done = self.progress.value() + 1
        total = self.thumb_view.count()
        self.progress.setValue(done)
        if done == total:
            self.progress.hide()

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
        # Set the current row to the first visible item
        get_item = self.thumb_view.item
        for i in range(self.thumb_view.count()):
            if not get_item(i).isHidden():
                self.thumb_view.setCurrentRow(i)
                break
        else:
            self.thumb_view.setCurrentRow(-1)
            self.image_view.setPixmap(None)


class TaggingWindow(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.original_tags: typing.Counter[str] = Counter()
        self.tags_to_add: Set[str] = set()
        self.tags_to_remove: Set[str] = set()

        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        self.heading_label = QtWidgets.QLabel('Change tags')
        self.heading_label.setObjectName('dialog_heading')
        layout.addWidget(self.heading_label)

        # Input
        input_box = QtWidgets.QHBoxLayout()
        self.tag_input = QtWidgets.QLineEdit(self)
        input_box.addWidget(self.tag_input)
        self.add_tag_button = QtWidgets.QPushButton('Add tag', self)
        input_box.addWidget(self.add_tag_button)
        layout.addLayout(input_box)

        def update_add_button(text: str) -> None:
            tags = {self.tag_list.item(i).data(PATH)
                    for i in range(self.tag_list.count())}
            tag = text.strip()
            self.add_tag_button.setEnabled(bool(tag) and tag not in tags)

        cast(pyqtSignal, self.tag_input.textChanged).connect(update_add_button)
        cast(pyqtSignal, self.tag_input.returnPressed).connect(self.add_tag)
        cast(pyqtSignal, self.add_tag_button.clicked).connect(self.add_tag)

        # Tag list
        self.tag_list = QtWidgets.QListWidget(self)
        layout.addWidget(self.tag_list)

        # Buttons
        button_box = QDialogButtonBox(self)
        button_box.addButton(QDialogButtonBox.Cancel)
        self.accept_button = button_box.addButton('Apply to images',
                                                  QDialogButtonBox.AcceptRole)
        cast(pyqtSignal, button_box.accepted).connect(self.accept)
        cast(pyqtSignal, button_box.rejected).connect(self.reject)
        layout.addWidget(button_box)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key_Return:
            if event.modifiers() & Qt.ControlModifier:
                self.accept()
        else:
            super().keyPressEvent(event)

    def get_tags_to_add(self) -> Set[str]:
        out = set()
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            if item.checkState() == Qt.Checked:
                out.add(item.data(PATH))
        return out

    def get_tags_to_remove(self) -> Set[str]:
        out = set()
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            if item.checkState() == Qt.Unchecked:
                out.add(item.data(PATH))
        return out

    def add_tag(self) -> None:
        if not self.add_tag_button.isEnabled():
            return
        tag = self.tag_input.text().strip()
        if tag:
            tags = {self.tag_list.item(i).data(PATH)
                    for i in range(self.tag_list.count())}
            if tag not in tags:
                item = TagListWidgetItem(f'{tag} (NEW)')
                item.setData(PATH, tag)
                item.setData(TAGS, (0, 0))
                item.setCheckState(Qt.Checked)
                self.tag_list.insertItem(0, item)
            self.tag_input.clear()

    def set_up(self, tags: typing.Counter[str],
               images: List[QtWidgets.QListWidgetItem]) -> None:
        self.original_tags = tags
        self.accept_button.setText(f'Apply to {len(images)} images')
        self.tag_input.clear()
        self.tag_list.clear()
        tag_counter: typing.Counter[str] = Counter()
        for img in images:
            img_tags = img.data(TAGS)
            tag_counter.update(img_tags)
        for tag, total in tags.items():
            count = tag_counter.get(tag, 0)
            item = TagListWidgetItem(f'{tag} ({count}/{total})')
            item.setData(PATH, tag)
            item.setData(TAGS, (count, total))
            if count == len(images):
                item.setCheckState(Qt.Checked)
            elif count == 0:
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.PartiallyChecked)
            self.tag_list.addItem(item)
        self.tag_list.sortItems(Qt.DescendingOrder)
        self.tag_input.setFocus()


class LeftColumn(QtWidgets.QWidget):
    tag_selected = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter between tabs and info
        splitter = QtWidgets.QSplitter(Qt.Vertical, self)
        layout.addWidget(splitter)

        # Tab widget
        self.tab_widget = QtWidgets.QTabWidget(self)
        splitter.addWidget(self.tab_widget)
        splitter.setStretchFactor(0, 1)

        # Tag list
        self.tag_list = TagListWidget(self.tab_widget)
        self.tag_list.setObjectName('tag_list')
        self.tag_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.tab_widget.addTab(self.tag_list, 'Tags')

        # Info widget
        self.info_box = QtWidgets.QWidget(self)
        info_layout = QtWidgets.QVBoxLayout(self.info_box)
        self.info_path = QtWidgets.QLabel(self.info_box)
        self.info_path.setWordWrap(True)
        info_layout.addWidget(self.info_path)
        self.info_tags = QtWidgets.QLabel(self.info_box)
        self.info_tags.setWordWrap(True)
        info_layout.addWidget(self.info_tags)
        self.info_dimensions = QtWidgets.QLabel(self.info_box)
        self.info_dimensions.setWordWrap(True)
        info_layout.addWidget(self.info_dimensions)
        info_layout.addStretch()
        splitter.addWidget(self.info_box)
        splitter.setStretchFactor(1, 0)

        # Buttons at the bottom
        bottom_row = QtWidgets.QHBoxLayout()
        self.settings_button = QtWidgets.QPushButton('Settings', self)
        bottom_row.addWidget(self.settings_button)
        self.reload_button = QtWidgets.QPushButton('Reload', self)
        bottom_row.addWidget(self.reload_button)
        layout.addLayout(bottom_row)

    def set_info(self, item: Optional[QtWidgets.QListWidgetItem]) -> None:
        if item is not None:
            if self.info_box.isHidden():
                self.info_box.show()
            tags = item.data(TAGS)
            path = item.data(PATH)
            width, height = item.data(DIMENSIONS)
            self.info_path.setText(str(path))
            self.info_tags.setText(', '.join(sorted(tags)))
            self.info_dimensions.setText(f'{width} x {height}')
        else:
            self.info_box.hide()
            self.info_path.clear()
            self.info_tags.clear()
            self.info_dimensions.clear()

    @staticmethod
    def _tag_format(tag: str, visible: int, total: int) -> str:
        return f'{tag or "<Untagged>"}   ({visible}/{total})'

    def create_tag(self, tag: str, count: int) -> None:
        item = TagListWidgetItem(self._tag_format(tag, count, count))
        item.setData(PATH, tag)
        item.setData(TAGS, count)
        item.setData(VISIBLE_TAGS, count)
        item.setData(TAGSTATE, TagState.DEFAULT)
        self.tag_list.addItem(item)
        update_looks(item)

    def set_tags(self, tags: List[Tuple[str, int]]) -> None:
        self.tag_list.clear()
        for tag, count in tags:
            self.create_tag(tag, count)
        self.tag_list.sortItems(Qt.DescendingOrder)

    def update_tags(self, tag_count: Dict[str, int]) -> None:
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            tag = item.data(PATH)
            new_count = tag_count[tag]
            item.setData(VISIBLE_TAGS, new_count)
            item.setText(self._tag_format(tag, new_count, item.data(TAGS)))
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
        self.empty_image = QtGui.QPixmap(128, 128)
        self.empty_image.fill(Qt.transparent)

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

    def setPixmap(self, image: Optional[QtGui.QPixmap]) -> None:
        if image is None:
            self.image = self.empty_image
        else:
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
        self.reset_thumbnails = False

        # Layout
        layout = QtWidgets.QVBoxLayout(self)
        self.heading_label = QtWidgets.QLabel('Image directories')
        self.heading_label.setObjectName('dialog_heading')
        layout.addWidget(self.heading_label)

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

        # Clear cache (not thumbnails)
        def clear_cache() -> None:
            msg = ('Are you sure you want to remove the cache? This will not '
                   'reset any thumbnails, only the file information.')
            reply = QtWidgets.QMessageBox.question(self, 'Clear cache', msg)
            if reply:
                CACHE.unlink()

        self.clear_cache_button = QtWidgets.QPushButton('Clear cache', self)
        cast(pyqtSignal, self.clear_cache_button.clicked).connect(clear_cache)
        layout.addWidget(self.clear_cache_button)

        # Regenerate thumbnails
        def regenerate_thumbnails() -> None:
            msg = ('Are you sure you want to regenerate the thumbnails? '
                   'Only the ones loaded right now will be affected.')
            reply = QtWidgets.QMessageBox.question(
                self, 'Regenerate thumbnails', msg)
            if reply:
                self.reset_thumbnails = True

        self.regen_thumbnails_button = QtWidgets.QPushButton(
            'Regenerate thumbnails', self)
        cast(pyqtSignal, self.regen_thumbnails_button.clicked
             ).connect(regenerate_thumbnails)
        layout.addWidget(self.regen_thumbnails_button)

        # Action buttons
        layout.addSpacing(10)
        btm_buttons = QDialogButtonBox(QDialogButtonBox.Cancel
                                       | QDialogButtonBox.Save)
        layout.addWidget(btm_buttons)
        cast(pyqtSignal, btm_buttons.accepted).connect(self.accept)
        cast(pyqtSignal, btm_buttons.rejected).connect(self.reject)

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
    app.setStyleSheet(CSS_FILE.read_text())

    config = read_config()
    window = MainWindow(config, event_filter.activation_event)
    app.setActiveWindow(window)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
