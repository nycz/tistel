#!/usr/bin/env python3
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
from typing import List, Optional
from urllib.parse import quote, unquote

# import pyexiv2
from PIL import Image
from PyQt5 import QtCore, QtGui, QtQml, QtQuick
from PyQt5.QtCore import pyqtSignal, pyqtSlot, pyqtProperty, Qt

import jfti
# from . import common, gameslib, gog, humble, local, qrc

# TODO: more platform-independant path
CONFIG = Path.home() / '.config' / 'tistel' / 'config.json'
CACHE = Path.home() / '.cache' / 'tistel' / 'cache.json'

# Thumbnail item data types
PATH = Qt.UserRole
DIMENSION = Qt.UserRole + 1
FILESIZE = Qt.UserRole + 2

# Image formats
IMAGE_EXTS = ('.png', '.jpg', '.gif')
IMAGE_MAGICS = ((b'\x89PNG\x0d\x0a\x1a\x0a',),
                (b'\xff\xd8',),
                (b'\x47\x49\x46\x38\x39\x61', b'\x47\x49\x46\x38\x37\x61'))


def extract_metadata(path):
    try:
        tags = sorted(jfti.read_tags(path))
    except Exception:
        print(path)
        raise
    size = QtGui.QImage(str(path)).size()
    # TODO: maybe get size from jfti too?
    # size = Image.open(str(path)).size
    return tags, (size.width(), size.height())


def write_tags(path, tags):
    return False
    # metadata = pyexiv2.ImageMetadata(path)
    # try:
        # metadata.read()
    # except OSError:
        # return False
    # else:
        # for tag in ('Iptc.Application2.Keywords', 'Xmp.dc.subject'):
            # if not tags:
                # try:
                    # if tag in metadata:
                        # del metadata[tag]
                # except UnicodeDecodeError:
                    # continue
            # else:
                # metadata[tag] = list(tags)
        # metadata.write()
        # return True


def try_to_load_image(path: Path):
    pixmap = QtGui.QPixmap(str(path))
    if not pixmap.isNull():
        return pixmap, path.suffix.lower()
    else:
        with path.open('rb') as f:
            magic_data = f.read(8)

        for img_format, magics in zip(IMAGE_EXTS, IMAGE_MAGICS):
            for magic in magics:
                if magic == magic_data[:len(magic)]:
                    pixmap = QtGui.QPixmap(str(path), format=img_format[1:].upper())
                    if not pixmap.isNull():
                        return pixmap, img_format
    return None, None


def filesize(bytenum):
    for t in ['', 'K', 'M', 'G', 'T']:
        if bytenum < 1000:
            break
        bytenum /= 1000
    return f'{bytenum:.1f}{t}'


def crc(data):
    crc_table = []
    for n in range(256):
        c = n
        for k in range(8):
            if c & 1:
                c = 0xedb88320 ^ (c >> 1)
            else:
                c >>= 1
        crc_table.append(c)
    c2 = 0xffffffff
    for n in range(len(data)):
        c2 = crc_table[(c2 ^ data[n]) & 0xff] ^ (c2 >> 8)
    return struct.pack('>I', c2 ^ 0xffffffff)


def png_text_chunk(name, text):
    header_and_data = b'tEXt%s\x00%s' % (name, text)
    length = struct.pack('>I', len(header_and_data) - 4)
    crc_bytes = crc(header_and_data)
    return length + header_and_data + crc_bytes


def generate_thumbnail(thumb_path: Path, image_path: Path, uri_path: str):
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
                           # str(int(os.path.getmtime(image_path))).encode())
    uri = png_text_chunk(b'Thumb::URI', uri_path)
    software = png_text_chunk(b'Software', b'imgview')
    data = data[:offset] + mtime + uri + software + data[offset:]
    thumb_path.write_bytes(data)
    thumb_path.chmod(0o600)
    return True


class ThumbLoader(QtQuick.QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QtQml.QQmlImageProviderBase.Pixmap)
        self.cache_path = Path.home() / '.thumbnails' / 'normal'
        self._images = {}

    def requestPixmap(self, image_id, requested_size) -> QtGui.QPixmap:
        # print(image_id)
        # print(unquote(image_id))
        wh = requested_size or QtCore.QSize(192, 128)
        path = unquote(image_id)
        if path in self._images:
            return self._images[path]
        # Thumbnail
        m = hashlib.md5()
        uri = b'file://' + quote(path).encode()
        m.update(uri)
        thumb_path = self.cache_path / (m.hexdigest() + '.png')
        if not thumb_path.is_file():
            success = generate_thumbnail(thumb_path, Path(path), uri)
            # icon = QtGui.QIcon(thumb_path) if success else self.fail_icon
        # path = image_id[7:]
        img = QtGui.QPixmap(str(thumb_path))
        if img.isNull():
            img = QtGui.QPixmap(wh)
            img.fill(QtCore.Qt.green)
        else:
            img = img.scaled(wh, QtCore.Qt.KeepAspectRatio,
                             QtCore.Qt.SmoothTransformation)
            self._images[path] = (img, wh)
        return (img, wh)


class ImageLoader(QtQuick.QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QtQml.QQmlImageProviderBase.Pixmap)
        self._images = {}
        self._image_history = []
        self.limit = 500 * (1024 ** 2)
        self.total = 0

    def requestPixmap(self, image_id, requested_size) -> QtGui.QPixmap:
        # print(image_id)
        # print(unquote(image_id))
        # wh = requested_size or QtCore.QSize(192, 128)
        path = unquote(image_id)
        if path in self._images:
            self._image_history.remove(path)
            self._image_history.append(path)
            return self._images[path]
        img = QtGui.QPixmap(str(path))
        if img.isNull():
            img = QtGui.QPixmap(requested_size)
            img.fill(QtCore.Qt.green)
            wh = requested_size
        else:
            wh = img.size()
            self._images[path] = (img, wh)
            self._image_history.append(path)
            self.total += img.width() * img.height() * img.depth() // 8
        while self.total > self.limit:
            cache_path = self._image_history.pop(0)
            i, _ = self._images[cache_path]
            del self._images[cache_path]
            self.total -= i.width() * i.height() * i.depth() // 8

        return (img, wh)


class Thumbnail(QtCore.QObject):
    selectedChanged = pyqtSignal()

    def __init__(self, path: Path, tags: List[str], size: int,
                 width: int, height: int) -> None:
        super().__init__()
        self._path = path
        self._tags = tags
        self._selected = False
        self._size = size
        self._dimensions = (width, height)

    @pyqtProperty(bool, notify=selectedChanged)
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool) -> None:
        if self._selected == value:
            return
        self._selected = value
        self.selectedChanged.emit()

    @pyqtProperty(str, constant=True)
    def path(self) -> str:
        return 'image://thumbs/' + quote(str(self._path))

    @pyqtProperty(str, constant=True)
    def fullPath(self) -> str:
        return 'image://fullsize/' + quote(str(self._path))

    @pyqtProperty(str, constant=True)
    def rawPath(self) -> str:
        return quote(str(self._path))

    @pyqtProperty(str, constant=True)
    def dimensions(self) -> str:
        return str(self._dimensions)

    @pyqtProperty(str, constant=True)
    def humanSize(self) -> str:
        return str(self._size)

    @pyqtProperty(str, constant=True)
    def tags(self) -> str:
        return str(self._tags)


class Tag(QtCore.QObject):
    countChanged = pyqtSignal()

    class State:
        Inactive = 0
        Whitelisted = 1
        Blacklisted = 2

    QtCore.Q_ENUMS(State)

    stateChanged = pyqtSignal(State, arguments=['state'])

    def __init__(self, parent: 'BackEnd', name: str, count: int,
                 key: Optional[str] = None) -> None:
        super().__init__()
        self._parent = parent
        self._name = name
        self._state = Tag.State.Inactive
        self._key = key or f'tag:{name}'
        self._count = count

    @pyqtProperty(str, constant=True)
    def name(self) -> str:
        if self._count >= 0:
            return f'{self._name} ({self._count})'
        else:
            return self._name

    @pyqtProperty(str, constant=True)
    def key(self) -> str:
        return self._key

    @pyqtProperty(int, notify=countChanged)
    def count(self) -> str:
        return self._count

    @pyqtProperty(State, notify=stateChanged)
    def state(self):
        return self._state

    @state.setter
    def state(self, state):
        if self._key == 'special:clear':
            self._parent.clear_tag_filter()
            return
        if state == self._state:
            return
        self._parent.update_tag_filter(self._key, self._state, state)
        self._state = state
        self.stateChanged.emit(self._state)


# class TagDialogBackEnd(QtCore.QObject):
    # def __init__(self) -> None:
        # super().__init__()

    # def selectedTags(self) -> List[Tag]:



class BackEnd(QtCore.QObject):
    imagesChanged = pyqtSignal()
    tagsChanged = pyqtSignal()
    pathsChanged = pyqtSignal()
    selectionChanged = pyqtSignal()

    def __init__(self, config, context) -> None:
        super().__init__()
        # Misc init
        self.pathsChanged.connect(self.index_images)
        self.config = config
        self.paths = [Path(p).expanduser() for p in config['directories']]
        self.context = context
        self.images = []
        self.visible_images = []
        self._selected_images = []
        self._selected_tags = []
        self.whitelist = set()
        self.blacklist = set()
        self.untagged_status = Tag.State.Inactive
        self.tags = [Tag(self, 'Clear tag filter', -1, key='special:clear'),
                     Tag(self, 'Untagged', -1, key='special:untagged')]
        self.index_images()
        self.load_index()

    def load_index(self) -> None:
        if not CACHE.exists():
            return
        cache = json.loads(CACHE.read_text())
        tag_count = Counter()
        root_paths = [str(p) for p in self.paths]
        for n, (raw_path, data) in enumerate(list(cache['images'].items())):
            # if n % 1000 == 0:
                # print(n)
            path = Path(raw_path)
            if not path.exists():
                del cache['images'][raw_path]
                continue
            for p in root_paths:
                if raw_path.startswith(p):
                    break
            else:
                continue
            thumb = Thumbnail(path, data['tags'], data['size'],
                              data['w'], data['h'])
            self.images.append(thumb)
            tag_count.update(thumb._tags)
        del self.tags[2:]
        for tag, count in tag_count.most_common():
            self.tags.append(Tag(self, tag, count))
        if self.images:
            self.images[0]._selected = True
        self.visible_images = self.images
        self.imagesChanged.emit()
        self.tagsChanged.emit()
        self.selectionChanged.emit()

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
                tags, (width, height) = extract_metadata(path_str)
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

    def clear_tag_filter(self):
        self.visible_images = self.images
        for tag in self.tags:
            if tag._state != Tag.State.Inactive:
                tag._state = Tag.State.Inactive
                tag.stateChanged.emit(Tag.State.Inactive)
        for img in self.images:
            img.selected = False
        if self.visible_images:
            self.visible_images[0].selected = True
        self.imagesChanged.emit()
        self.selectionChanged.emit()

    def update_tag_filter(self, key, old_state, new_state):
        type_, tag = key.split(':', 1)
        if type_ == 'tag':
            if old_state == Tag.State.Whitelisted:
                self.whitelist.remove(tag)
            elif old_state == Tag.State.Blacklisted:
                self.blacklist.remove(tag)
            if new_state == Tag.State.Whitelisted:
                self.whitelist.add(tag)
            elif new_state == Tag.State.Blacklisted:
                self.blacklist.add(tag)
        else:
            self.untagged_status = new_state
        self.visible_images = []
        for img in self.images:
            tags = set(img._tags)
            if not tags and self.untagged_status == Tag.State.Blacklisted:
                continue
            if tags and self.untagged_status == Tag.State.Whitelisted:
                continue
            if not tags.isdisjoint(self.blacklist):
                continue
            if not tags >= self.whitelist:
                continue
            self.visible_images.append(img)
        for img in self.images:
            img.selected = False
        if self.visible_images:
            self.visible_images[0].selected = True
        self.imagesChanged.emit()
        self.selectionChanged.emit()

    @pyqtSlot(int, int, int)
    def updateSelection(self, modifiers: int,
                        old_pos: int, new_pos: int) -> None:
        shift = bool(modifiers & Qt.ShiftModifier)
        ctrl = bool(modifiers & Qt.ControlModifier)
        if ctrl:
            img = self.visible_images[new_pos]
            img.selected = not img._selected
            return
        start = min(old_pos, new_pos)
        end = max(old_pos, new_pos)
        for pos, img in enumerate(self.visible_images):
            if shift:
                if start <= pos <= end:
                    img.selected = True
            elif pos != new_pos:
                img.selected = False
            elif pos == new_pos:
                img.selected = True
        self.selectionChanged.emit()

    @pyqtSlot(str)
    def addDirectory(self, path_str: str) -> None:
        path = Path(path_str[len('file://'):]).expanduser()
        if path in self.paths:
            return
        self.paths.append(path)
        self.pathsChanged.emit()
        # TODO: less shitty than this
        self.config['directories'] = [str(p) for p in self.paths]
        CONFIG.write_text(json.dumps(self.config, indent=2))

    @pyqtSlot(str)
    def removeDirectory(self, path: str) -> None:
        self.paths.remove(Path(path))
        self.pathsChanged.emit()
        self.config['directories'] = [str(p) for p in self.paths]
        CONFIG.write_text(json.dumps(self.config, indent=2))

    @pyqtProperty(list, notify=pathsChanged)
    def imageDirectories(self) -> List[str]:
        return [str(p) for p in self.paths]

    @pyqtProperty(list, notify=imagesChanged)
    def imageModel(self) -> List[Thumbnail]:
        return self.visible_images

    @pyqtProperty(list, notify=tagsChanged)
    def tagsModel(self) -> List[Tag]:
        return self.tags

    @pyqtProperty(list, notify=selectionChanged)
    def selectedImages(self) -> List[Thumbnail]:
        self._selected_images = [x for x in self.visible_images if x.selected]
        return self._selected_images

    @pyqtProperty(list, notify=selectionChanged)
    def selectedTags(self) -> List[Thumbnail]:
        self._selected_tags = [
            Tag(self, tag, count)
            for tag, count in Counter(t for img in self.selectedImages
                                      for t in img._tags).most_common()
        ]
        return self._selected_tags


def read_config():
    if not CONFIG.exists():
        default_config = {'directories': []}
        if not CONFIG.parent.exists():
            CONFIG.parent.mkdir(parents=True)
        CONFIG.write_text(json.dumps(default_config, indent=2))
        return default_config
    else:
        return json.loads(CONFIG.read_text())


def main() -> None:
    config = read_config()
    app = QtGui.QGuiApplication(sys.argv)
    app.setOrganizationName('syntyche')
    app.setOrganizationDomain('syntyche')
    app.setApplicationName('tistel')
    QtQml.qmlRegisterType(Tag, 'Tag', 1, 0, 'Tag')
    engine = QtQml.QQmlApplicationEngine()
    thumb_loader = ThumbLoader()
    image_loader = ImageLoader()
    engine.addImageProvider('thumbs', thumb_loader)
    engine.addImageProvider('fullsize', image_loader)
    context = engine.rootContext()
    backend = BackEnd(config, context)
    context.setContextProperty('backend', backend)

    def on_qml_error(obj, url):
        if obj is None:
            print('QML errors caught, force-quitting')
            sys.exit(1)

    engine.objectCreated.connect(on_qml_error)

    engine.load(str(Path(__file__).resolve().with_name('tistel.qml')))
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
