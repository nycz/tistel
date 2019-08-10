import hashlib
import json
from pathlib import Path
import struct
import time
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote
import zlib

import exifread
from jfti import jfti
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal

from .shared import CACHE, Signal0, Signal1, Signal3


IMAGE_EXTS = ('.png', '.jpg', '.gif')
IMAGE_MAGICS = ([b'\x89PNG\x0d\x0a\x1a\x0a'],
                [b'\xff\xd8'],
                [b'GIF87a', b'GIF89a'])

THUMB_SIZE = QtCore.QSize(192, 128)


def set_rotation(orientation: List[int]) -> QtGui.QTransform:
    transform = QtGui.QTransform()
    if orientation.values == [8]:
        # Rotate left
        transform.rotate(-90)
    elif orientation.values == [6]:
        # Rotate right
        transform.rotate(90)
    elif orientation.values == [3]:
        # Rotate 180
        transform.rotate(180)
    return transform


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
    # Rotate the thumbnail
    with open(image_path, 'rb') as f:
        exif = exifread.process_file(f, stop_tag='Orientation')
    orientation = exif.get('Image Orientation')
    if orientation:
        transform = set_rotation(orientation)
        if not transform.isIdentity():
            pixmap = pixmap.transformed(transform)
    scaled_pixmap = pixmap.scaled(THUMB_SIZE,
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
    thumbnail_ready: Signal3[int, int, QtGui.QIcon] \
        = QtCore.pyqtSignal(int, int, QtGui.QIcon)

    def __init__(self) -> None:
        super().__init__()
        self.cache_path = Path.home() / '.thumbnails' / 'normal'
        fail_thumb = QtGui.QPixmap(THUMB_SIZE)
        fail_thumb.fill(QtGui.QColor(QtCore.Qt.darkRed))
        self.base_thumb = QtGui.QImage(THUMB_SIZE,
                                       QtGui.QImage.Format_ARGB32)
        self.base_thumb.fill(Qt.transparent)
        self.fail_icon = QtGui.QIcon(fail_thumb)
        self.fail_icon.addPixmap(fail_thumb, QtGui.QIcon.Selected)
        self.cached_thumbs: Dict[Path, QtGui.QIcon] = {}

    def make_thumb(self, path: Path) -> QtGui.QIcon:
        img = self.base_thumb.copy()
        thumb = QtGui.QImage(str(path))
        painter = QtGui.QPainter(img)
        painter.drawImage(
            int((THUMB_SIZE.width() - thumb.width()) / 2),
            int((THUMB_SIZE.height() - thumb.height()) / 2),
            thumb)
        painter.end()
        pixmap = QtGui.QPixmap.fromImage(img)
        icon = QtGui.QIcon(pixmap)
        icon.addPixmap(pixmap, QtGui.QIcon.Selected)
        return icon

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


class Indexer(QtCore.QObject):
    set_text: Signal1[str] = pyqtSignal(str)
    set_value: Signal1[int] = pyqtSignal(int)
    set_max: Signal1[int] = pyqtSignal(int)
    done: Signal1[bool] = pyqtSignal(bool)

    def index_images(self, paths: Iterable[Path],
                     skip_thumb_cache: bool) -> None:
        self.set_max.emit(0)
        self.set_value.emit(0)
        self.set_text.emit('Loading cache...')
        if CACHE.exists():
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
                self.set_text.emit(f'Searching for images... '
                                   f'({count} found)')
                image_paths.append(path)
        total = count
        self.set_max.emit(total)
        count = 0
        for path in image_paths:
            self.set_text.emit(f'Indexing images... ({count}/{total})')
            self.set_value.emit(count)
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
            except Exception as e:
                # TODO: handle this better and log it
                print(e)
            else:
                cached_images[path_str] = {
                    'tags': tags,
                    'size': stat.st_size,
                    'w': width,
                    'h': height,
                    'mtime': stat.st_mtime,
                    'ctime': stat.st_ctime
                }
        self.set_max.emit(0)
        self.set_value.emit(0)
        if not CACHE.parent.exists():
            CACHE.parent.mkdir(parents=True)
        self.set_text.emit('Saving cache...')
        CACHE.write_text(json.dumps(cache))
        self.done.emit(skip_thumb_cache)
