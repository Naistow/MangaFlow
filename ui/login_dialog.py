import sqlite3
from PyQt6 import QtWidgets
from core.auth import AuthError, HardwareMismatch
from ui.theme import apply_eva_theme, label


class LoginDialog(QtWidgets.QDialog):
    def __init__(self, auth, hwid, parent=None):
        super().__init__(parent)
        self.auth, self.hwid, self.user = auth, hwid, None
        self.setWindowTitle('MangaFlow — авторизация')
        self.setMinimumWidth(440)
        apply_eva_theme(self)
        layout = QtWidgets.QFormLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addRow(label('MangaFlow', 'heading'))
        layout.addRow(label('Вход в личный кабинет', 'section'))
        self.login = QtWidgets.QLineEdit()
        self.code = QtWidgets.QLineEdit()
        self.code.setPlaceholderText('MF-XXXX-XXXX')
        layout.addRow('Логин', self.login)
        layout.addRow('Инвайт-код', self.code)
        button = QtWidgets.QPushButton('Войти / Активировать')
        button.setObjectName('primary')
        button.setDefault(True)
        button.clicked.connect(self.activate)
        layout.addRow(button)
        self.message = label('Введите логин и инвайт для активации устройства', 'status')
        self.message.setWordWrap(True)
        layout.addRow(self.message)
        self.reason = QtWidgets.QLineEdit()
        self.reason.setPlaceholderText('Причина смены железа')
        self.reset = QtWidgets.QPushButton('Подать заявку на смену железа')
        self.reset.clicked.connect(self.request_reset)
        layout.addRow(self.reason)
        layout.addRow(self.reset)
        self.reason.hide()
        self.reset.hide()

    def activate(self):
        self.reset.setEnabled(True)
        self.reason.hide()
        self.reset.hide()
        try:
            self.user = self.auth.activate(self.login.text(), self.code.text(), self.hwid)
            self.accept()
        except HardwareMismatch as exc:
            self.message.setText(str(exc))
            self.reason.show()
            self.reset.show()
        except (AuthError, sqlite3.Error) as exc:
            self.message.setText(str(exc))

    def request_reset(self):
        try:
            self.auth.request_reset(self.login.text(), self.code.text(), self.hwid, self.reason.text())
            self.message.setText('Заявка сохранена. После одобрения администратором повторите вход.')
            self.reset.setEnabled(False)
        except (AuthError, sqlite3.Error) as exc:
            self.message.setText(str(exc))
