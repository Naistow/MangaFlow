from PyQt6 import QtWidgets, QtGui

class MangaFlowTray(QtWidgets.QSystemTrayIcon):
    def __init__(self, app_context, parent=None):
        icon = QtGui.QIcon("assets/tray_icon.png")
        super().__init__(icon, parent)
        self.ctx = app_context
        self.setToolTip("MangaFlow Translator")
        self.init_menu()

    def init_menu(self):
        menu = QtWidgets.QMenu()

        translate_area = QtGui.QAction("Выделить область мышкой (Alt+A)", menu)
        translate_area.triggered.connect(self.ctx.start_area_snip)
        menu.addAction(translate_area)

        translate_now = QtGui.QAction("Перевести весь экран (Alt+X)", menu)
        translate_now.triggered.connect(self.ctx.trigger_screen_translation)
        menu.addAction(translate_now)

        self.toggle_overlay_action = QtGui.QAction("Показать/Скрыть оверлей (Alt+Z)", menu)
        self.toggle_overlay_action.triggered.connect(self.ctx.toggle_overlay)
        menu.addAction(self.toggle_overlay_action)

        clear_action = QtGui.QAction("Очистить экран (Alt+C)", menu)
        clear_action.triggered.connect(self.ctx.clear_overlay)
        menu.addAction(clear_action)

        menu.addSeparator()

        cabinet = QtGui.QAction('Личный кабинет / Пакетный перевод', menu)
        cabinet.triggered.connect(self.ctx.open_profile_window)
        menu.addAction(cabinet)
        menu.addSeparator()

        exit_action = QtGui.QAction("Выход", menu)
        exit_action.triggered.connect(self.ctx.graceful_shutdown)
        menu.addAction(exit_action)

        self.setContextMenu(menu)
