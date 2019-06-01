from pathlib import Path

from PyQt5.QtCore import Qt


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
