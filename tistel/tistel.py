#!/usr/bin/env python3
from collections import Counter
import json
import logging
from pathlib import Path
import sys
import time
import typing
from typing import cast, List, Optional, Set

import exifread
from PyQt5 import QtGui, QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt

from .details_view import DetailsBox
from .image_loading import Indexer, set_rotation, try_to_get_orientation
from .image_view import ImagePreview
from .settings import Settings, SettingsWindow
from .shared import CACHE, CSS_FILE, PATH, Signal2, TAGS, TAGSTATE, THUMBNAILS
from .sidebar import SideBar
from .tag_list import TagState
from .tagging_window import TaggingWindow
from .thumb_view import ProgressBar, ThumbView


class MainWindow(QtWidgets.QWidget):
    start_indexing: Signal2[Set[Path], bool] = pyqtSignal(set, bool)

    def __init__(self, config: Settings,
                 activation_event: QtCore.pyqtSignal) -> None:
        super().__init__()
        # Make thumbnails directory if needed
        if not THUMBNAILS.exists():
            THUMBNAILS.mkdir(parents=True)

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
        self.splitter = QtWidgets.QSplitter(self)
        layout.addWidget(self.splitter)

        # Statusbar
        progress = ProgressBar(self)
        progress.hide()
        layout.addWidget(progress)

        # Left column - tags/files/dates and info
        self.sidebar = SideBar(config, self)
        self.splitter.addWidget(self.sidebar)

        # Middle column - thumbnails
        self.thumb_view = ThumbView(progress, config, self.splitter)
        self.splitter.addWidget(self.thumb_view)
        self.splitter.setStretchFactor(1, 2)

        self.sidebar.tag_list.tag_state_updated.connect(
            self.update_tag_filter)
        self.thumb_view.currentItemChanged.connect(
            self.sidebar.tag_list.set_current_thumb)

        # Right column - big image
        self.image_view_splitter = QtWidgets.QSplitter(Qt.Vertical, self.splitter)

        self.image_view = ImagePreview(self.image_view_splitter)
        self.image_view.setObjectName('image_view')

        def load_big_image(current: QtWidgets.QListWidgetItem,
                           prev: QtWidgets.QListWidgetItem) -> None:
            if current and not current.isHidden():
                path = current.data(PATH)
                orientation = try_to_get_orientation(path)
                pixmap: Optional[QtGui.QPixmap] = None
                if orientation:
                    transform = set_rotation(orientation)
                    if not transform.isIdentity():
                        img = QtGui.QImage(str(path)).transformed(transform)
                        pixmap = QtGui.QPixmap.fromImage(img)
                if pixmap is None:
                    pixmap = QtGui.QPixmap(str(path))
                self.image_view.setPixmap(pixmap)
                self.image_info_box.set_info(current)
            else:
                self.image_view.setPixmap(None)
                self.image_info_box.set_info(None)

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
        self.image_view_splitter.addWidget(self.image_view)
        self.image_view_splitter.setStretchFactor(0, 1)

        # Image info box
        self.image_info_box = DetailsBox(self)
        self.image_view_splitter.addWidget(self.image_info_box)
        self.image_view_splitter.setStretchFactor(1, 0)

        self.splitter.addWidget(self.image_view_splitter)
        self.splitter.setStretchFactor(2, 1)

        # Toggle fullscreen
        def toggle_fullscreen() -> None:
            if self.thumb_view.isHidden():
                self.thumb_view.show()
                self.sidebar.show()
            else:
                self.config.main_splitter = self.splitter.sizes()
                self.config.side_splitter = \
                    self.image_view_splitter.sizes()
                self.config.save()
                self.thumb_view.hide()
                self.sidebar.hide()

        cast(pyqtSignal, QtWidgets.QShortcut(QtGui.QKeySequence('f'),
                                             self).activated
             ).connect(toggle_fullscreen)

        # Settings dialog
        self.settings_dialog = SettingsWindow(self)

        def show_settings_window() -> None:
            self.settings_dialog.set_up(self.config)
            result = self.settings_dialog.exec_()
            if result == QtWidgets.QDialog.Accepted:
                new_config = self.settings_dialog.config
                if new_config != self.config:
                    update_paths = (new_config.paths != self.config.paths)
                    update_names = (new_config.show_names != self.config.show_names)
                    self.config.update(new_config)
                    self.config.save()
                    if self.settings_dialog.clear_cache:
                        CACHE.unlink()
                    skip_thumb_cache = self.settings_dialog.reset_thumbnails
                    if update_paths:
                        self.index_images(skip_thumb_cache)
                    elif skip_thumb_cache:
                        self.load_index(True)
                    if update_names:
                        for item in self.thumb_view:
                            item.setText(item.data(PATH).name
                                         if self.config.show_names else None)
                        self.thumb_view.update_thumb_size()

        cast(pyqtSignal, self.sidebar.settings_button.clicked
             ).connect(show_settings_window)

        # Tagging dialog
        self.tagging_dialog = TaggingWindow(self)

        cast(pyqtSignal, QtWidgets.QShortcut(QtGui.QKeySequence('Ctrl+T'),
                                             self).activated
             ).connect(self.show_tagging_dialog)

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

        cast(pyqtSignal, self.sidebar.reload_button.clicked
             ).connect(self.index_images)

        # Finalize
        if config.main_splitter:
            self.splitter.setSizes(config.main_splitter)
        if config.side_splitter:
            self.image_view_splitter.setSizes(config.side_splitter)
        self.make_event_filter()
        self.show()
        self.index_images()
        self.thumb_view.setFocus()

    def show_tagging_dialog(self) -> None:
        current_item = self.thumb_view.currentItem()
        selected_items = self.thumb_view.selectedItems()
        self.tagging_dialog.set_up(self.tag_count, selected_items)
        result = self.tagging_dialog.exec_()
        if not result:
            return
        slider_pos = self.thumb_view.verticalScrollBar()\
            .sliderPosition()
        untagged_diff, updated_files, new_tag_count, created_tags =\
            self.tagging_dialog.tag_images(selected_items)
        if not updated_files:
            return
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
        untagged_item = self.sidebar.tag_list.takeItem(0)
        untagged_item.setData(TAGS, (untagged_item.data(TAGS)
                                     + untagged_diff))
        tag_items_to_delete = []
        for i in range(self.sidebar.tag_list.count()):
            tag_item = self.sidebar.tag_list.item(i)
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
            self.sidebar.tag_list.takeItem(i)
        for tag in created_tags:
            count = new_tag_count.get(tag, 0)
            if count > 0:
                self.sidebar.create_tag(tag, count)
        self.sidebar.tag_list.insertItem(0, untagged_item)
        self.sidebar.sort_tags()
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
        self.thumb_view.verticalScrollBar()\
            .setSliderPosition(slider_pos)

    def make_event_filter(self) -> None:
        class MainWindowEventFilter(QtCore.QObject):
            def eventFilter(self_, obj: QtCore.QObject,
                            event: QtCore.QEvent) -> bool:
                if event.type() == QtCore.QEvent.Close:
                    if self.thumb_view.isVisible():
                        self.config.main_splitter = self.splitter.sizes()
                        self.config.side_splitter = \
                            self.image_view_splitter.sizes()
                        self.config.save()
                return False
        self.close_filter = MainWindowEventFilter()
        self.installEventFilter(self.close_filter)

    def index_images(self, skip_thumb_cache: bool = False) -> None:
        self.start_indexing.emit(self.config.active_paths, skip_thumb_cache)

    def load_index(self, skip_thumb_cache: bool) -> None:
        self.indexer_progressbar.accept()
        result = self.thumb_view.load_index(skip_thumb_cache)
        if result is not None:
            tags, self.tag_count = result
            self.sidebar.set_tags(tags)
        self.sidebar.dir_tree.update_paths(self.config.active_paths)

    def update_tag_filter(self) -> None:
        whitelist = set()
        blacklist = set()
        untagged_state = TagState.DEFAULT
        tag_count: typing.Counter[str] = Counter()
        for tag_item in self.sidebar.tag_list:
            state = tag_item.data(TAGSTATE)
            tag = tag_item.data(PATH)
            if tag == '':
                untagged_state = state
            elif state == TagState.WHITELISTED:
                whitelist.add(tag)
            elif state == TagState.BLACKLISTED:
                blacklist.add(tag)
        untagged = 0
        for item in self.thumb_view:
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
        self.sidebar.update_tags(tag_count)
        # Set the current row to the first visible item
        for item in self.thumb_view:
            if not item.isHidden():
                self.thumb_view.setCurrentItem(item)
                break
        else:
            self.thumb_view.setCurrentRow(-1)
            self.image_view.setPixmap(None)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--path', nargs='+', dest='paths',
                        metavar='path', type=Path,
                        help='Use these paths instead of the settings')
    logging.basicConfig()

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

    config = Settings.load(args.paths)
    window = MainWindow(config, event_filter.activation_event)
    app.setActiveWindow(window)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
