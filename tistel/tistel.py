#!/usr/bin/env python3
from collections import Counter
import json
from pathlib import Path
import sys
import time
import typing
from typing import cast, Dict, Iterable, List, Optional, Set, Tuple

import exifread
from PyQt5 import QtGui, QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import QDialogButtonBox

from jfti import jfti

from .shared import (CACHE, CONFIG, CSS_FILE, DIMENSIONS,
                     PATH, TAGS, TAGSTATE, VISIBLE_TAGS)
from .image_loading import ImageLoader, Indexer, set_rotation
from .image_view import ImagePreview
from .settings import Settings, SettingsWindow
from .shared import Signal1, Signal2
from .tag_list import TagListWidget, TagListWidgetItem, TagState, update_looks


class ProgressBar(QtWidgets.QProgressBar):
    def text(self) -> str:
        value = self.value()
        total = self.maximum()
        return (f'Reloading thumbnails: {value}/{total}'
                f' ({value/max(total, 1):.0%})')


class MainWindow(QtWidgets.QWidget):
    image_queued: Signal2[int,
                          List[Tuple[int, bool, Path]]] = pyqtSignal(int, list)
    start_indexing: Signal2[Set[Path], bool] = pyqtSignal(set, bool)

    def __init__(self, config: Settings,
                 activation_event: QtCore.pyqtSignal) -> None:
        super().__init__()
        # Settings
        self.setWindowTitle('tistel')
        cast(pyqtSignal, QtWidgets.QShortcut(QtGui.QKeySequence('Escape'),
                                             self).activated
             ).connect(self.close)
        self.config = config
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
                path = current.data(PATH)
                with open(path, 'rb') as f:
                    exif = exifread.process_file(f, stop_tag='Orientation')
                orientation = exif.get('Image Orientation')
                pixmap: Optional[QtGui.QPixmap] = None
                if orientation:
                    transform = set_rotation(orientation)
                    if not transform.isIdentity():
                        img = QtGui.QImage(str(path)).transformed(transform)
                        pixmap = QtGui.QPixmap.fromImage(img)
                if pixmap is None:
                    pixmap = QtGui.QPixmap(str(path))
                self.image_view.setPixmap(pixmap)
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
        self.settings_dialog = SettingsWindow(self)

        def show_settings_window() -> None:
            self.settings_dialog.set_up(self.config)
            result = self.settings_dialog.exec_()
            if result == QtWidgets.QDialog.Accepted:
                old_config = self.config
                self.config = self.settings_dialog.config
                if old_config != self.config:
                    self.config.save()
                    if self.settings_dialog.clear_cache:
                        CACHE.unlink()
                    skip_thumb_cache = self.settings_dialog.reset_thumbnails
                    if old_config.paths != self.config.paths:
                        self.index_images(skip_thumb_cache)
                    elif skip_thumb_cache:
                        self.load_index(True)
                    elif old_config.show_names != self.config.show_names:
                        for i in range(self.thumb_view.count()):
                            item = self.thumb_view.item(i)
                            item.setText(item.data(PATH).name
                                         if self.config.show_names else None)

        cast(pyqtSignal, self.left_column.settings_button.clicked
             ).connect(show_settings_window)

        # Tagging dialog
        self.tagging_dialog = TaggingWindow(self)

        def show_tagging_dialog() -> None:
            current_item = self.thumb_view.currentItem()
            selected_items = self.thumb_view.selectedItems()
            self.tagging_dialog.set_up(self.tag_count, selected_items)
            result = self.tagging_dialog.exec_()
            if result:
                new_tag_count: typing.Counter[str] = Counter()
                untagged_diff = 0
                updated_files = {}
                tags_to_add = self.tagging_dialog.get_tags_to_add()
                tags_to_remove = self.tagging_dialog.get_tags_to_remove()
                created_tags = tags_to_add - set(self.tag_count.keys())
                progress_dialog = QtWidgets.QProgressDialog(
                    'Tagging images...', 'Cancel',
                    0, len(selected_items))
                progress_dialog.setWindowModality(Qt.WindowModal)
                progress_dialog.setMinimumDuration(0)

                total = len(selected_items)
                for n, item in enumerate(selected_items):
                    progress_dialog.setLabelText(f'Tagging images... '
                                                 f'({n}/{total})')
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
                        if not old_tags and new_tags:
                            untagged_diff -= 1
                        elif old_tags and not new_tags:
                            untagged_diff += 1
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
                    untagged_item.setData(TAGS, (untagged_item.data(TAGS)
                                                 + untagged_diff))
                    tag_items_to_delete = []
                    for i in range(self.left_column.tag_list.count()):
                        tag_item = self.left_column.tag_list.item(i)
                        tag = tag_item.data(PATH)
                        diff = new_tag_count.get(tag, 0)
                        if diff != 0:
                            new_count = tag_item.data(TAGS) + diff
                            if new_count <= 0:
                                del self.tag_count[tag]
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
                    # Go back to the same selected items as before (if visible)
                    for item in self.thumb_view.selectedItems():
                        if (item.isHidden() or item not in selected_items) \
                                and item.isSelected():
                            item.setSelected(False)
                    for item in selected_items:
                        if not item.isHidden() and not item.isSelected():
                            item.setSelected(True)
                    self.thumb_view.setCurrentItem(current_item)

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

        self.indexer_progressbar = QtWidgets.QProgressDialog()
        self.indexer_progressbar.setWindowModality(Qt.WindowModal)
        self.indexer_progressbar.setMinimumDuration(0)
        self.indexer.done.connect(lambda _: self.indexer_progressbar.reset())
        self.indexer.set_text.connect(self.indexer_progressbar.setLabelText)
        self.indexer.set_value.connect(self.indexer_progressbar.setValue)
        self.indexer.set_max.connect(self.indexer_progressbar.setMaximum)

        cast(pyqtSignal, self.left_column.reload_button.clicked
             ).connect(self.index_images)

        # Finalize
        self.batch = 0
        self.thumbnails_done = 0
        self.show()
        self.index_images()

    def index_images(self, skip_thumb_cache: bool = False) -> None:
        self.start_indexing.emit(self.config.paths, skip_thumb_cache)

    def load_index(self, skip_thumb_cache: bool) -> None:
        self.indexer_progressbar.accept()
        if not CACHE.exists():
            return
        self.thumb_view.clear()
        self.batch += 1
        imgs = []
        cache = json.loads(CACHE.read_text())
        self.tag_count.clear()
        root_paths = [str(p) for p in self.config.paths]
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
            item_text = path.name if self.config.show_names else None
            item = QtWidgets.QListWidgetItem(self.default_icon, item_text)
            item.setSizeHint(QtCore.QSize(192, 160))
            self.thumb_view.addItem(item)
            item.setData(PATH, path)
            item.setData(TAGS, set(data['tags']))
            item.setData(DIMENSIONS, (data['w'], data['h']))
            imgs.append((n, skip_thumb_cache, path))
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
        untagged = self.tag_list.takeItem(0)
        self.tag_list.sortItems(Qt.DescendingOrder)
        self.tag_list.insertItem(0, untagged)

    def update_tags(self, tag_count: Dict[str, int]) -> None:
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            tag = item.data(PATH)
            new_count = tag_count[tag]
            item.setData(VISIBLE_TAGS, new_count)
            item.setText(self._tag_format(tag, new_count, item.data(TAGS)))
            update_looks(item)


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

    config = Settings.load()
    window = MainWindow(config, event_filter.activation_event)
    app.setActiveWindow(window)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
