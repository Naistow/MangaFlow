from PyQt6 import QtCore, QtGui, QtWidgets

class AreaSnipper(QtWidgets.QWidget):
    area_selected = QtCore.pyqtSignal(tuple)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        screen_geo = QtWidgets.QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geo)
        self.begin = QtCore.QPoint()
        self.end = QtCore.QPoint()
        self.is_selecting = False

    def start_selection(self):
        self.begin = QtCore.QPoint()
        self.end = QtCore.QPoint()
        self.is_selecting = False
        self.show()
        self.activateWindow()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 90))
        if self.is_selecting:
            rect = QtCore.QRect(self.begin, self.end).normalized()
            painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, QtCore.Qt.GlobalColor.transparent)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 180, 255), 2))
            painter.drawRect(rect)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.begin = event.pos()
            self.end = self.begin
            self.is_selecting = True
            self.update()
        elif event.button() == QtCore.Qt.MouseButton.RightButton:
            self.hide()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.hide()
            rect = QtCore.QRect(self.begin, self.end).normalized()
            if rect.width() > 20 and rect.height() > 20:
                self.area_selected.emit((rect.x(), rect.y(), rect.width(), rect.height()))
