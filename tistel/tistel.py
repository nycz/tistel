#!/usr/bin/env python3
import logging
import sys
import time
import typing
from pathlib import Path
from typing import (Any, Counter, Dict, FrozenSet, List, NamedTuple, Optional,
                    Set, cast)

from libsyntyche import app
from libsyntyche.widgets import (Signal0, Signal2, kill_theming, mk_signal0,
                                 mk_signal2)
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from . import jfti
from .details_view import DetailsBox
from .image_loading import Indexer, set_rotation, try_to_get_orientation
from .image_view import ImagePreview
from .settings import Settings, SettingsWindow
from .shared import CACHE, CSS_FILE, THUMBNAILS, Cache, ImageData
from .sidebar import SideBar
from .tagging_window import TagChanges, TaggingWindow
from .thumb_view import Container as ThumbViewContainer
from .thumb_view import Mode as ThumbViewMode
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
        self.sidebar.setFixedWidth(int(min(
            max(
                event.windowPos().x() - self.x_offset,
                self.sidebar.minimumSizeHint().width()
            ),
            (
                cast(QtWidgets.QWidget, self.parent()).width() - self.width()
                - ((self.thumb_view.width() + self.image_view.minimumSizeHint().width())
                   if self.thumb_view.mode == ThumbViewMode.normal else
                   self.thumb_view.minimumSizeHint().width())
            ),
        )))

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.x_offset = event.pos().x()


class MainWindow(app.RootWindow):
    start_indexing: Signal2[Set[Path], bool] = mk_signal2(set, bool)

    def __init__(self, config: Settings) -> None:
        super().__init__('tistel')
        # Make thumbnails directory if needed
        if not THUMBNAILS.exists():
            THUMBNAILS.mkdir(parents=True)

        # Settings
        self.config = config
        self.tag_count: typing.Counter[str] = Counter()

        # Main layout
        kill_theming(self.layout())
        self.splitter = QtWidgets.QHBoxLayout()
        kill_theming(self.splitter)
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
        kill_theming(thumb_view_container_layout)

        status_bar = StatusBar(self)
        thumb_view_container_layout.addWidget(status_bar)

        self.thumb_view = ThumbView(progress, status_bar, config, self.thumb_view_container)
        thumb_view_container_layout.addWidget(self.thumb_view)
        self.splitter.addWidget(self.thumb_view_container, stretch=0)
        self.thumb_view_container.thumb_view = self.thumb_view

        self.sidebar.tag_list.tag_state_updated.connect(
            self.update_tag_filter)
        self.thumb_view.image_selected.connect(
            self.sidebar.tag_list.set_current_image_data)

        # Right column - big image
        self.image_view_splitter = QtWidgets.QSplitter(Qt.Vertical, self)

        self.image_view = ImagePreview(self.image_view_splitter)
        self.image_view.setObjectName('image_view')

        def load_big_image(current: Optional[ImageData]) -> None:
            if current:
                path = current.path
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

        self.thumb_view.image_selected.connect(load_big_image)

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
                        for item in self.thumb_view.items():
                            item.setText(item.path.name if self.config.show_names else '')
                        self.thumb_view.update_thumb_size()

        cast(Signal0, self.sidebar.settings_button.clicked
             ).connect(show_settings_window)

        cast(Signal0, QtWidgets.QShortcut(QtGui.QKeySequence('Ctrl+T'), self).activated
             ).connect(self.show_tagging_dialog)

        # Reloading
        self.indexing = True
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

        def reset_progressbar(*args: Any) -> None:
            self.indexer_progressbar.reset()
        self.indexer.done.connect(reset_progressbar)
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
        current_index = self.thumb_view.currentIndex()
        selected_items = self.thumb_view.selectedItems()
        if not selected_items:
            return
        result = TaggingWindow.get_tag_changes(selected_items, self.tag_count, self)
        if not result:
            return
        slider_pos = self.thumb_view.verticalScrollBar().sliderPosition()
        changes = tag_images(set(self.tag_count.keys()), result, selected_items)
        if not changes.updated_files:
            return
        # Update the cache
        if not CACHE.exists():
            print('WARNING: no cache! probably reload ??')
            return
        cache = Cache.load()
        cache.updated = time.time()
        for path, tags in changes.updated_files.items():
            if path not in cache.images:
                print('WARNING: img not in cache ??')
                continue
            cache.images[path].tags = list(tags)
        cache.save()
        # Update the tag list
        self.tag_count.update(changes.new_tag_count)
        self.sidebar.tag_list.update_tags(changes.untagged_diff, changes.new_tag_count,
                                          changes.created_tags)
        self.update_tag_filter()
        self.thumb_view.setCurrentIndex(current_index)
        self.thumb_view.verticalScrollBar().setSliderPosition(slider_pos)

    def make_event_filter(self) -> None:
        class MainWindowEventFilter(QtCore.QObject):
            def eventFilter(self_, obj: QtCore.QObject,
                            event: QtCore.QEvent) -> bool:
                if event.type() == QtCore.QEvent.Close:
                    if self.thumb_view.isVisible():
                        self.config.sidebar_width = self.sidebar.width()
                        self.config.side_splitter = self.image_view_splitter.sizes()
                        self.config.save()
                return False
        self.close_filter = MainWindowEventFilter()
        self.installEventFilter(self.close_filter)

    def index_images(self, skip_thumb_cache: bool = False) -> None:
        self.indexing = True
        self.start_indexing.emit(self.config.active_paths, skip_thumb_cache)

    def load_index(self, skip_thumb_cache: bool) -> None:
        self.indexing = False
        self.indexer_progressbar.accept()
        result = self.thumb_view.load_index(skip_thumb_cache)
        if result is not None:
            self.tag_count = result
            self.sidebar.tag_list.set_tags(result)
        self.sidebar.dir_tree.update_paths(self.config.active_paths)

    def update_tag_filter(self) -> None:
        self.thumb_view.set_tag_filter(self.sidebar.tag_list.get_tag_states())
        self.sidebar.tag_list.update_visible_tags(self.thumb_view.get_tag_count())
        if self.thumb_view.visibleCount():
            self.thumb_view.setCurrentRow(0)
        else:
            self.thumb_view.setCurrentRow(-1)
            self.image_view.setPixmap(None)


class TagUpdateResult(NamedTuple):
    untagged_diff: int
    updated_files: Dict[Path, Set[str]]
    new_tag_count: Counter[str]
    created_tags: FrozenSet[str]


def tag_images(original_tags: Set[str], changes: TagChanges,
               images: List[ImageData]) -> TagUpdateResult:
    # Progress dialog
    progress_dialog = QtWidgets.QProgressDialog(
        'Tagging images...', 'Cancel', 0, len(images))
    progress_dialog.setWindowModality(Qt.WindowModal)
    progress_dialog.setMinimumDuration(0)
    # Info about the data we're working with
    total = len(images)
    created_tags = changes.tags_to_add - original_tags
    # Info about the changes
    new_tag_count: Counter[str] = Counter()
    untagged_diff = 0
    updated_files = {}
    # Tag the files
    for n, image in enumerate(images):
        progress_dialog.setLabelText(f'Tagging images... ({n}/{total})')
        progress_dialog.setValue(n)
        old_tags = image.tags
        new_tags = (old_tags | changes.tags_to_add) - changes.tags_to_remove
        if old_tags != new_tags:
            added_tags = new_tags - old_tags
            removed_tags = old_tags - new_tags
            new_tag_count.update({t: 1 for t in added_tags})
            new_tag_count.update({t: -1 for t in removed_tags})
            try:
                jfti.set_tags(image.path, new_tags)
            except Exception:
                print('FAIL', image.path)
                raise
            image.tags = new_tags
            updated_files[image.path] = new_tags
            if not old_tags and new_tags:
                untagged_diff -= 1
            elif old_tags and not new_tags:
                untagged_diff += 1
        if progress_dialog.wasCanceled():
            break
    progress_dialog.setValue(total)
    return TagUpdateResult(untagged_diff, updated_files, new_tag_count, created_tags)


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

    paths: List[Path] = args.paths
    config = Settings.load(paths)
    window = MainWindow(config)
    app.setActiveWindow(window)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
