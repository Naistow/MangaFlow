"""Indigo dashboard palette, scoped to account windows only."""
from PyQt6 import QtWidgets

DASHBOARD_STYLE = '''
QWidget { background: #151426; color: #EEEFFA; font-family: "Segoe UI"; font-size: 13px; }
QDialog, QMainWindow { background: #151426; }
QFrame#sidebar { background: #1E1D35; border-radius: 16px; }
QFrame#panel { background: #1E1D35; border: 1px solid #302E4D; border-radius: 16px; }
QLabel { background: transparent; border: none; }
QLabel#brand { color: #ADABFF; font-size: 30px; font-weight: 800; }
QLabel#heading { color: #F4F2FF; font-size: 25px; font-weight: 700; padding-bottom: 8px; }
QLabel#section { color: #E4E0FC; font-size: 16px; font-weight: 600; }
QLabel#eyebrow { color: #A6A1C4; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#muted { color: #A29DBC; }
QLabel#statNumber { color: #C4B9FF; font-size: 30px; font-weight: 700; }
QLabel#activated { background: #272542; color: #BDB9EA; border: 1px solid #3D385E; border-radius: 12px; padding: 7px 12px; }
QLabel#status { color: #BDB5EF; padding: 8px; background: #272542; border-radius: 8px; }
QGroupBox { background: #272542; border: 1px solid #363251; border-radius: 10px; margin-top: 16px; padding: 12px; }
QGroupBox::title { color: #A9A2C8; subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QLineEdit, QPlainTextEdit, QTableWidget { background: #19182C; border: 1px solid #363251; border-radius: 9px; padding: 10px; selection-background-color: #61528F; selection-color: #FFFFFF; }
QLineEdit:focus, QPlainTextEdit:focus, QTableWidget:focus { border: 1px solid #A69BDD; }
QLineEdit { min-height: 22px; }
QPushButton { background: #272542; color: #DCD7F0; border: 1px solid #40395E; border-radius: 9px; padding: 11px 12px; font-weight: 600; }
QPushButton:hover { background: #353051; border-color: #8E81BC; }
QPushButton:pressed { background: #4D426C; }
QPushButton#primary { background: #A898E4; color: #171427; border-color: #A898E4; }
QPushButton#primary:hover { background: #C0B1F4; }
QPushButton#nav { text-align: left; border: none; background: transparent; padding: 13px 8px; font-size: 12px; }
QPushButton#nav:checked { background: #34304F; color: #D1C4FF; }
QPushButton#nav:hover { background: #2B2844; }
QPushButton#windowControl { padding: 0; border: none; background: transparent; color: #A59EBB; }
QPushButton#windowControl:hover { background: #353051; color: white; }
QPushButton:disabled { background: #252239; color: #6E6785; border-color: #302A43; }
QPushButton#danger { color: #DD9AB1; }
QProgressBar { background: #272542; border: none; border-radius: 4px; min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: #A898E4; border-radius: 4px; }
QHeaderView::section { background: #1E1D35; color: #928BAE; font-size: 10px; padding: 8px 4px; border: none; border-bottom: 1px solid #363251; }
QTableWidget { gridline-color: #2F2C46; alternate-background-color: #272542; padding: 3px; }
QTableWidget::item { padding: 6px; border-bottom: 1px solid #2F2C46; }
QTableWidget::item:selected { background: #39304F; color: #E7DEFF; }
QScrollBar:vertical { background: #1E1D35; width: 8px; }
QScrollBar::handle:vertical { background: #4E446C; min-height: 24px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #272542; color: #DDD5FC; border: 1px solid #61528F; }
'''


def apply_dashboard_theme(window):
    window.setStyleSheet(DASHBOARD_STYLE)


# Compatibility with existing dialog imports.
apply_eva_theme = apply_dashboard_theme


def label(text, name):
    widget = QtWidgets.QLabel(text)
    widget.setObjectName(name)
    return widget
