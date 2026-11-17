# ui/hotkeys.py
import ctypes
from ctypes import wintypes
from PyQt6 import QtCore

MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

VK_A = 0x41  # Alt + A (или русская Ф)
VK_X = 0x58  # Alt + X (или русская Ч)
VK_Z = 0x5A  # Alt + Z (или русская Я)
VK_C = 0x43  # Alt + C (или русская С)

class GlobalHotkeyListener(QtCore.QThread):
    translate_screen_signal = QtCore.pyqtSignal()
    translate_area_signal = QtCore.pyqtSignal()
    toggle_visibility_signal = QtCore.pyqtSignal()
    emergency_stop_signal = QtCore.pyqtSignal()

    def run(self):
        user32 = ctypes.windll.user32

        user32.RegisterHotKey(None, 1, MOD_ALT | MOD_NOREPEAT, VK_X)
        user32.RegisterHotKey(None, 2, MOD_ALT | MOD_NOREPEAT, VK_A)
        user32.RegisterHotKey(None, 3, MOD_ALT | MOD_NOREPEAT, VK_Z)
        user32.RegisterHotKey(None, 4, MOD_ALT | MOD_NOREPEAT, VK_C)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                hotkey_id = msg.wParam
                if hotkey_id == 1:
                    print("[Hotkey] Нажато Alt+X (Весь экран)")
                    self.translate_screen_signal.emit()
                elif hotkey_id == 2:
                    print("[Hotkey] Нажато Alt+A (Выделение области)")
                    self.translate_area_signal.emit()
                elif hotkey_id == 3:
                    print("[Hotkey] Нажато Alt+Z (Скрыть/Показать)")
                    self.toggle_visibility_signal.emit()
                elif hotkey_id == 4:
                    print("[Hotkey] Нажато Alt+C (Очистить)")
                    self.emergency_stop_signal.emit()

            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))