"""Frameless account window with native Qt moving/resizing gestures."""
from PyQt6 import QtCore, QtWidgets


class WindowChrome(QtCore.QObject):
    def __init__(self, window, header):
        super().__init__(window)
        self.window = window
        self.header = header
        QtWidgets.QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QtCore.QEvent.Type.MouseButtonPress, QtCore.QEvent.Type.MouseButtonDblClick):
            return False
        if not isinstance(watched, QtWidgets.QWidget) or watched.window() is not self.window:
            return False
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        point = self.window.mapFromGlobal(event.globalPosition().toPoint())
        handle = self.window.windowHandle()
        if handle is None:
            return False
        if kind == QtCore.QEvent.Type.MouseButtonPress and not self.window.isMaximized():
            edges = QtCore.Qt.Edge(0)
            if point.x() < 8:
                edges |= QtCore.Qt.Edge.LeftEdge
            elif point.x() >= self.window.width() - 8:
                edges |= QtCore.Qt.Edge.RightEdge
            if point.y() < 8:
                edges |= QtCore.Qt.Edge.TopEdge
            elif point.y() >= self.window.height() - 8:
                edges |= QtCore.Qt.Edge.BottomEdge
            if edges:
                return handle.startSystemResize(edges)
        in_header = watched is self.header or self.header.isAncestorOf(watched)
        if in_header and not isinstance(watched, QtWidgets.QAbstractButton):
            if kind == QtCore.QEvent.Type.MouseButtonDblClick:
                self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()
                return True
            return handle.startSystemMove()
        return False
