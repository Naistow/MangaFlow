
import sys
import ctypes
from PyQt6 import QtCore, QtGui, QtWidgets

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

class ScreenOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.bubbles_data = []
        self.init_window_flags()

    def init_window_flags(self):
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        
        screen_geo = QtWidgets.QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geo)

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_click_through()

    def apply_click_through(self):
        if sys.platform == "win32":
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            current_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current_style | WS_EX_TRANSPARENT | WS_EX_LAYERED)

    def update_bubbles(self, new_bubbles):
        self.bubbles_data = new_bubbles
        if self.bubbles_data:
            self.show()
            self.raise_()
        self.update()

    def paintEvent(self, event):
        if not self.bubbles_data:
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        flags = (
            QtCore.Qt.AlignmentFlag.AlignCenter |
            QtCore.Qt.TextFlag.TextWordWrap
        )

        for rect, lines, _, bg_color in self.bubbles_data:
            full_text = " ".join([line.replace("- ", "") for line in lines]) if isinstance(lines, list) else str(lines)

            painter.setPen(QtGui.QPen(QtGui.QColor(35, 35, 35), 2))
            painter.setBrush(QtGui.QColor(255, 255, 255, 248))
            radius = min(rect.width(), rect.height()) * 0.22
            painter.drawRoundedRect(rect, radius, radius)

            inner_rect = rect.adjusted(6, 6, -6, -6)

            best_pixel_size = 9
            for px_size in range(24, 8, -1):
                font = QtGui.QFont("Arial")
                font.setPixelSize(px_size)
                font.setWeight(QtGui.QFont.Weight.DemiBold)
                metrics = QtGui.QFontMetrics(font)
                
                bound = metrics.boundingRect(
                    inner_rect, flags, full_text
                )
                if bound.width() <= inner_rect.width() and bound.height() <= inner_rect.height():
                    best_pixel_size = px_size
                    break

            final_font = QtGui.QFont("Arial")
            final_font.setPixelSize(best_pixel_size)
            final_font.setWeight(QtGui.QFont.Weight.DemiBold)
            painter.setFont(final_font)
            painter.setPen(QtGui.QColor(15, 15, 15))

            painter.drawText(inner_rect, flags, full_text)

        painter.end()