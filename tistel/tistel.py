#!/usr/bin/env python3
from collections import Counter
import json
from pathlib import Path
import sys
import time
import typing
from typing import cast, Dict, List, Optional, Set, Tuple

import exifread
from PyQt5 import QtGui, QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import QDialogButtonBox, QPushButton

from jfti import jfti

from .shared import (CACHE, CONFIG, CSS_FILE, DIMENSIONS,
                     PATH, TAGS, TAGSTATE, VISIBLE_TAGS)
from .image_loading import ImageLoader, Indexer, set_rotation, THUMB_SIZE
from .image_view import ImagePreview
from .settings import Settings, SettingsWindow
from .shared import ListWidget, Signal2
from .tag_list import TagListWidget, TagListWidgetItem, TagState


class ProgressBar(QtWidgets.QProgressBar):
    def text(self) -> str:
        value = self.value()
        total = self.maximum()
        return (f'Reloading thumbnails: {value}/{total}'
                f' ({value/max(total, 1):.0%})')


class ThumbView(ListWidget):

    def find_visible(self, reverse: bool = False
                     ) -> Optional[QtWidgets.QListWidgetItem]:
        diff = -1 if reverse else 1
        total = self.count()
        i = self.currentRow()
        if i < 0 or total < 0:
            return None
        for _ in range(total):
            i += diff
            i %= total
            item = self.item(i)
            if not item.isHidden():
                return item
        return None

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key_Right:
            self.setCurrentItem(self.find_visible())
        elif event.key() == Qt.Key_Left:
            self.setCurrentItem(self.find_visible(reverse=True))
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        current = self.currentItem()
        if current:
            painter = QtGui.QPainter(self.viewport())
            rect = self.visualItemRect(current).adjusted(10, 10, -11, -11)
            pen = QtGui.QPen(QtGui.QColor('#1bf986'))
            pen.setWidth(3)
            pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen)
            painter.drawRect(rect)


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
        self.splitter = QtWidgets.QSplitter(self)
        layout.addWidget(self.splitter)

        # Statusbar
        self.progress = ProgressBar(self)
        self.progress.hide()
        layout.addWidget(self.progress)

        # Left column - tags/files/dates and info
        self.left_column = LeftColumn(self)
        self.splitter.addWidget(self.left_column)

        # Middle column - thumbnails
        default_thumb = QtGui.QPixmap(THUMB_SIZE)
        default_thumb.fill(QtGui.QColor(QtCore.Qt.gray))
        self.default_icon = QtGui.QIcon(default_thumb)
        self.default_icon.addPixmap(default_thumb, QtGui.QIcon.Selected)

        self.thumb_loader_thread = QtCore.QThread()
        cast(QtCore.pyqtSignal, QtWidgets.QApplication.instance().aboutToQuit
             ).connect(self.thumb_loader_thread.quit)
        self.thumb_loader = ImageLoader()
        self.thumb_loader.moveToThread(self.thumb_loader_thread)
        self.image_queued.connect(self.thumb_loader.load_image)
        self.thumb_loader.thumbnail_ready.connect(self.add_thumbnail)
        self.thumb_loader_thread.start()
        self.thumb_view = ThumbView(self.splitter)
        self.thumb_view.setUniformItemSizes(True)
        self.thumb_view.setViewMode(QtWidgets.QListView.IconMode)
        self.thumb_view.setFocus()
        self.update_thumb_size()
        self.thumb_view.setMovement(QtWidgets.QListWidget.Static)
        self.thumb_view.setResizeMode(QtWidgets.QListWidget.Adjust)
        p = self.thumb_view.palette()
        p.setColor(QtGui.QPalette.Highlight, Qt.green)
        self.thumb_view.setPalette(p)
        self.thumb_view.setObjectName('thumb_view')
        self.thumb_view.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)

        self.splitter.addWidget(self.thumb_view)
        self.splitter.setStretchFactor(1, 2)

        self.left_column.tag_list.tag_state_updated.connect(
            self.update_tag_filter)

        # Right column - big image
        self.image_view = ImagePreview(self.splitter)
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
        self.splitter.addWidget(self.image_view)
        self.splitter.setStretchFactor(2, 1)

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
                    if old_config.show_names != self.config.show_names:
                        for item in self.thumb_view:
                            item.setText(item.data(PATH).name
                                         if self.config.show_names else None)
                        self.update_thumb_size()

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
                slider_pos = self.thumb_view.verticalScrollBar()\
                    .sliderPosition()
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
                        try:
                            jfti.set_tags(path, new_tags)
                        except Exception:
                            print('FAIL', path)
                            raise
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
                    self.left_column.tag_list.insertItem(0, untagged_item)
                    self.left_column.sort_tags()
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
        if config.main_splitter:
            self.splitter.setSizes(config.main_splitter)
        if config.side_splitter:
            self.left_column.splitter.setSizes(config.side_splitter)
        self.make_event_filter()
        self.batch = 0
        self.thumbnails_done = 0
        self.show()
        self.index_images()

    def make_event_filter(self) -> None:
        class MainWindowEventFilter(QtCore.QObject):
            def eventFilter(self_, obj: QtCore.QObject,
                            event: QtCore.QEvent) -> bool:
                if event.type() == QtCore.QEvent.Close:
                    self.config.main_splitter = self.splitter.sizes()
                    self.config.side_splitter = \
                        self.left_column.splitter.sizes()
                    self.config.save()
                return False
        self.close_filter = MainWindowEventFilter()
        self.installEventFilter(self.close_filter)

    def update_thumb_size(self) -> None:
        if self.config.show_names:
            text_height = int(QtGui.QFontMetricsF(self.thumb_view.font()
                                                  ).height() * 1.5)
        else:
            text_height = 0
        self.thumb_view.setIconSize(THUMB_SIZE + QtCore.QSize(0, text_height))
        margin = (10 + 3) * 2
        self.thumb_view.setGridSize(THUMB_SIZE
                                    + QtCore.QSize(margin,
                                                   margin + text_height))

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
            self.thumb_view.addItem(item)
            item.setBackground(QtGui.QBrush(Qt.red))
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
        for tag_item in self.left_column.tag_list:
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
        self.left_column.update_tags(tag_count)
        # Set the current row to the first visible item
        for item in self.thumb_view:
            if not item.isHidden():
                self.thumb_view.setCurrentItem(item)
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
        self.resize(300, 500)

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
            tags = {item.data(PATH) for item in self.tag_list}
            tag = text.strip()
            self.add_tag_button.setEnabled(bool(tag) and tag not in tags)

        cast(pyqtSignal, self.tag_input.textChanged).connect(update_add_button)
        cast(pyqtSignal, self.tag_input.returnPressed).connect(self.add_tag)
        cast(pyqtSignal, self.add_tag_button.clicked).connect(self.add_tag)

        # Tag list
        self.tag_list = ListWidget(self)
        self.tag_list.sort_by_alpha = True
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
        for item in self.tag_list:
            if item.checkState() == Qt.Checked:
                out.add(item.data(PATH))
        return out

    def get_tags_to_remove(self) -> Set[str]:
        out = set()
        for item in self.tag_list:
            if item.checkState() == Qt.Unchecked:
                out.add(item.data(PATH))
        return out

    def add_tag(self) -> None:
        if not self.add_tag_button.isEnabled():
            return
        tag = self.tag_input.text().strip()
        if tag:
            tags = {item.data(PATH) for item in self.tag_list}
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
        self.tag_list.sortItems()
        self.tag_input.setFocus()


class SortButton(QtWidgets.QPushButton):
    def __init__(self, text: str, parent: QtWidgets.QWidget) -> None:
        super().__init__(text, parent)
        self.reversed = False

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.RightButton:
            self.reversed = not self.reversed
            self.setText(self.text()[::-1])
        elif event.button() == Qt.LeftButton:
            self.setChecked(True)
        self.pressed.emit()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        return


class LeftColumn(QtWidgets.QWidget):
    tag_selected = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter between tabs and info
        self.splitter = QtWidgets.QSplitter(Qt.Vertical, self)
        layout.addWidget(self.splitter)

        # Tab widget
        self.tab_widget = QtWidgets.QTabWidget(self)
        self.tab_widget.setFocusPolicy(Qt.NoFocus)
        self.splitter.addWidget(self.tab_widget)
        self.splitter.setStretchFactor(0, 1)

        # Tag list box
        tag_list_box = QtWidgets.QWidget(self.tab_widget)
        tag_list_box.setObjectName('tag_list_box')
        tag_list_box_layout = QtWidgets.QVBoxLayout(tag_list_box)
        tag_list_box_layout.setContentsMargins(0, 0, 0, 0)
        tag_list_box_layout.setSpacing(0)
        self.tab_widget.addTab(tag_list_box, 'Tags')

        # Tag list buttons
        tag_buttons_hbox = QtWidgets.QHBoxLayout()
        tag_buttons_hbox.setContentsMargins(0, 0, 0, 0)
        tag_list_box_layout.addLayout(tag_buttons_hbox)
        clear_button = QPushButton('Clear tags', tag_list_box)
        clear_button.setObjectName('clear_button')
        sort_buttons = QtWidgets.QButtonGroup(tag_list_box)
        sort_buttons.setExclusive(True)
        sort_alpha_button = SortButton('a-z', tag_list_box)
        sort_alpha_button.setObjectName('sort_button')
        sort_alpha_button.setCheckable(True)
        sort_alpha_button.setChecked(True)
        sort_count_button = SortButton('0-9', tag_list_box)
        sort_count_button.setObjectName('sort_button')
        sort_count_button.setCheckable(True)
        sort_buttons.addButton(sort_alpha_button)
        sort_buttons.addButton(sort_count_button)

        tag_buttons_hbox.addWidget(clear_button)
        tag_buttons_hbox.addStretch()
        tag_buttons_hbox.addWidget(sort_alpha_button)
        tag_buttons_hbox.addWidget(sort_count_button)

        # Tag list
        self.tag_list = TagListWidget(tag_list_box)
        self.tag_list.setObjectName('tag_list')
        self.tag_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.tag_list.setFocusPolicy(Qt.NoFocus)
        tag_list_box_layout.addWidget(self.tag_list)

        def sort_button_pressed(button: SortButton) -> None:
            if not button.isChecked():
                return
            self.tag_list.sort_by_alpha = (button == sort_alpha_button)
            self.tag_list.sortItems(Qt.DescendingOrder
                                    if button.reversed else Qt.AscendingOrder)

        sort_alpha_button.pressed.connect(
            lambda: sort_button_pressed(sort_alpha_button))
        sort_count_button.pressed.connect(
            lambda: sort_button_pressed(sort_count_button))
        self.sort_alpha_button = sort_alpha_button
        self.sort_count_button = sort_count_button

        def clear_tag_filters():
            for tag in self.tag_list:
                tag.setData(TAGSTATE, TagState.DEFAULT)
            self.tag_list.tag_state_updated.emit()

        clear_button.clicked.connect(clear_tag_filters)

        # Files tab
        self.tab_widget.addTab(QtWidgets.QLabel('todo'), 'Files')

        # Dates tab
        self.tab_widget.addTab(QtWidgets.QLabel('todo'), 'Dates')

        # Info widget
        self.info_box = QtWidgets.QFrame(self)
        self.info_box.setObjectName('info_box')
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
        self.splitter.addWidget(self.info_box)
        self.splitter.setStretchFactor(1, 0)

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

    def set_tags(self, tags: List[Tuple[str, int]]) -> None:
        self.tag_list.clear()
        for tag, count in tags:
            self.create_tag(tag, count)
        untagged = self.tag_list.takeItem(0)
        self.tag_list.insertItem(0, untagged)
        self.sort_tags()

    def sort_tags(self) -> None:
        if self.sort_alpha_button.isChecked():
            button = self.sort_alpha_button
        else:
            button = self.sort_count_button
        self.tag_list.sortItems(Qt.DescendingOrder
                                if button.reversed else Qt.AscendingOrder)

    def update_tags(self, tag_count: Dict[str, int]) -> None:
        for item in self.tag_list:
            tag = item.data(PATH)
            new_count = tag_count[tag]
            item.setData(VISIBLE_TAGS, new_count)
            item.setText(self._tag_format(tag, new_count, item.data(TAGS)))


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
