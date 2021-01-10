from typing import Optional, cast

from libsyntyche.widgets import Signal1, mk_signal1
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt


class ImagePreview(QtWidgets.QLabel):
    change_image = mk_signal1(int)

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
        cast(Signal1[QtGui.QPixmap], self.animation.frameChanged).connect(self.new_frame)
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
