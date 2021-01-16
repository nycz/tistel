#!/usr/bin/env python3
import json
import logging
import sys
import time
import typing
from collections import Counter
from pathlib import Path
from typing import Optional, Set, cast

from libsyntyche import app
from libsyntyche.widgets import Signal0, Signal2, mk_signal0, mk_signal2
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from .thumb_view import Container as ThumbViewContainer
from .thumb_view import Mode as ThumbViewMode
from .details_view import DetailsBox
from .image_loading import Indexer, set_rotation, try_to_get_orientation
from .image_view import ImagePreview
from .settings import Settings, SettingsWindow
from .shared import CACHE, CSS_FILE, PATH, TAGS, TAGSTATE, THUMBNAILS
from .sidebar import SideBar
from .tag_list import TagState
from .tagging_window import TaggingWindow
from .thumb_view import ProgressBar, StatusBar, ThumbView


class Divider(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName('main_divider')
        self.sidebar: QtWidgets.QWidget
        self.thumb_view: ThumbViewContainer
        self.image_view: QtWidgets.QWidget
        self.x_offset = 0

    def set_widgets(self, sidebar: QtWidgets.QWidget,
                    thumb_view: ThumbViewContainer,
                    image_view: QtWidgets.QWidget) -> None:
        self.sidebar = sidebar
        self.thumb_view = thumb_view
        self.image_view = image_view

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self.sidebar.setFixedWidth(min(
            max(
                event.windowPos().x() - self.x_offset,
                self.sidebar.minimumSizeHint().width()
            ),
            (self.parent().width() - self.width()
             - ((self.thumb_view.width() + self.image_view.minimumSizeHint().width())
                if self.thumb_view.mode == ThumbViewMode.normal else
                self.thumb_view.minimumSizeHint().width())
             )
        ))

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.x_offset = event.pos().x()


class MainWindow(app.RootWindow):
    start_indexing: Signal2[Set[Path], bool] = mk_signal2(set, bool)

    def __init__(self, config: Settings, activation_event: Signal0) -> None:
        super().__init__('tistel')
        # Make thumbnails directory if needed
        if not THUMBNAILS.exists():
            THUMBNAILS.mkdir(parents=True)

        # Settings
        self.config = config
        self.tag_count: typing.Counter[str] = Counter()

        # Main layout
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.splitter = QtWidgets.QHBoxLayout()
        self.splitter.setContentsMargins(0, 0, 0, 0)
        self.layout().addLayout(self.splitter)

        # Progress bar
        progress = ProgressBar(self)
        progress.hide()
        self.layout().addWidget(progress)

        # Left column - tags/files/dates and info
        self.sidebar = SideBar(config, self)
        self.splitter.addWidget(self.sidebar, stretch=0)

        self.split_handle = Divider(self)
        self.split_handle.setFixedWidth(8)
        self.split_handle.setCursor(Qt.SplitHCursor)
        self.splitter.addWidget(self.split_handle, stretch=0)

        # Middle column - thumbnails
        self.thumb_view_container = ThumbViewContainer(self)
        thumb_view_container_layout = QtWidgets.QVBoxLayout(self.thumb_view_container)
        thumb_view_container_layout.setContentsMargins(0, 0, 0, 0)

        status_bar = StatusBar(self)
        thumb_view_container_layout.addWidget(status_bar)

        self.thumb_view = ThumbView(progress, status_bar, config, self.thumb_view_container)
        thumb_view_container_layout.addWidget(self.thumb_view)
        self.splitter.addWidget(self.thumb_view_container, stretch=0)
        self.thumb_view_container.thumb_view = self.thumb_view

        self.sidebar.tag_list.tag_state_updated.connect(
            self.update_tag_filter)
        self.thumb_view.currentItemChanged.connect(
            self.sidebar.tag_list.set_current_thumb)

        # Right column - big image
        self.image_view_splitter = QtWidgets.QSplitter(Qt.Vertical, self)

        self.image_view = ImagePreview(self.image_view_splitter)
        self.image_view.setObjectName('image_view')

        def load_big_image(current: Optional[QtGui.QStandardItem],
                           prev: Optional[QtGui.QStandardItem]) -> None:
            if current:
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

        self.thumb_view.currentItemChanged.connect(load_big_image)

        def change_image(diff: int) -> None:
            total = self.thumb_view.visibleCount()
            if total:
                current = max(self.thumb_view.currentRow(), 0)
                self.thumb_view.setCurrentRow((current + diff) % total)

        self.image_view.change_image.connect(change_image)
        self.image_view_splitter.addWidget(self.image_view)

        # Image info box
        self.image_info_box = DetailsBox(self)
        self.image_view_splitter.addWidget(self.image_info_box)
        self.image_view_splitter.setStretchFactor(1, 0)

        self.splitter.addWidget(self.image_view_splitter, stretch=1)

        # Toggle fullscreen
        def toggle_fullscreen() -> None:
            if self.thumb_view_container.isHidden():
                self.thumb_view_container.show()
                self.sidebar.show()
                self.split_handle.show()
                self.image_info_box.show()
                self.thumb_view.setFocus()
                self.showNormal()
            elif self.thumb_view.allow_fullscreen():
                self.config.sidebar_width = self.sidebar.width()
                self.config.side_splitter = self.image_view_splitter.sizes()
                self.config.save()
                self.thumb_view_container.hide()
                self.sidebar.hide()
                self.split_handle.hide()
                self.image_info_box.hide()
                self.image_view.setFocus()
                self.showFullScreen()

        cast(Signal0, QtWidgets.QShortcut(QtGui.QKeySequence('f'), self).activated
             ).connect(toggle_fullscreen)

        def activate_select_mode() -> None:
            self.thumb_view.set_mode(ThumbViewMode.select)

        def activate_normal_mode() -> None:
            self.thumb_view.set_mode(ThumbViewMode.normal)

        cast(Signal0, QtWidgets.QShortcut(QtGui.QKeySequence('v'), self).activated
             ).connect(activate_select_mode)
        cast(Signal0, QtWidgets.QShortcut(QtGui.QKeySequence('n'), self).activated
             ).connect(activate_normal_mode)

        # On thumbnail view mode change
        def thumb_view_mode_change(mode: ThumbViewMode) -> None:
            if mode == ThumbViewMode.normal:
                self.image_view_splitter.show()
            elif mode == ThumbViewMode.select:
                self.image_view_splitter.hide()

        self.thumb_view.mode_changed.connect(thumb_view_mode_change)

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
                        count = self.thumb_view.count()
                        for i in range(count):
                            item = self.thumb_view.item(i)
                            item.setText(item.data(PATH).name
                                         if self.config.show_names else '')
                        self.thumb_view.update_thumb_size()

        cast(Signal0, self.sidebar.settings_button.clicked
             ).connect(show_settings_window)

        # Tagging dialog
        self.tagging_dialog = TaggingWindow(self)

        cast(Signal0, QtWidgets.QShortcut(QtGui.QKeySequence('Ctrl+T'), self).activated
             ).connect(self.show_tagging_dialog)

        # Reloading
        self.indexer = Indexer()
        self.indexer_thread = QtCore.QThread()
        cast(Signal0, QtWidgets.QApplication.instance().aboutToQuit  # type: ignore
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

        cast(Signal0, self.sidebar.reload_button.clicked).connect(self.index_images)

        # Finalize
        self.split_handle.set_widgets(self.sidebar, self.thumb_view_container,
                                      self.image_view_splitter)
        if config.sidebar_width:
            self.sidebar.setFixedWidth(config.sidebar_width)
        if config.side_splitter:
            self.image_view_splitter.setSizes(config.side_splitter)
        self.make_event_filter()
        self.show()
        self.index_images()
        self.thumb_view.setFocus()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.thumb_view.available_space_updated(
            event.size().width()
            - self.split_handle.x()
            - self.split_handle.width()
            - self.image_view.minimumSizeHint().width()
        )

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
                        self.config.sidebar_width = self.sidebar.width()
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
        for tag_item in self.sidebar.tag_list:
            state = tag_item.data(TAGSTATE)
            tag = tag_item.data(PATH)
            if tag == '':
                untagged_state = state
            elif state == TagState.WHITELISTED:
                whitelist.add(tag)
            elif state == TagState.BLACKLISTED:
                blacklist.add(tag)
        self.thumb_view.set_tag_filter(untagged_state, whitelist, blacklist)
        self.sidebar.update_tags(self.thumb_view.get_tag_count())
        if self.thumb_view.visibleCount():
            self.thumb_view.setCurrentRow(0)
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
        activation_event = mk_signal0()

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
