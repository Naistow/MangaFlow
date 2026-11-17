# main.py
import os
import re
import sys
import signal
import logging
import time
from PIL import Image, ImageDraw
from PyQt6 import QtWidgets, QtCore

from ui.tray import MangaFlowTray
from ui.overlay import ScreenOverlay
from ui.snipper import AreaSnipper
from ui.hotkeys import GlobalHotkeyListener
from core.capture import ScreenCapture
from core.cleaner import BubbleCleaner
from core.typography import AntiOverflowEngine, BubbleRect
from core.auth import AuthError, get_hwid
from core.remote_auth import create_auth_client
from database.store import Store, DEFAULT_DB
from ui.login_dialog import LoginDialog


class TranslationWorker(QtCore.QThread):
    """Фоновый поток для распознавания и перевода без зависания интерфейса."""
    finished_bubbles = QtCore.pyqtSignal(list)
    access_error = QtCore.pyqtSignal(str)

    def __init__(self, frame_bgr, ocr_engine, translator, typography, custom_rect=None, authorize=None):
        super().__init__()
        self.frame_bgr = frame_bgr
        self.ocr = ocr_engine
        self.translator = translator
        self.typography = typography
        self.custom_rect = custom_rect
        self.authorize = authorize

    def run(self):
        try:
            if self.authorize:
                self.authorize()
            started = time.perf_counter()
            if self.custom_rect:
                print(f"[1/4] Перевод выделенной области {self.custom_rect}...")
                bubbles = [{"rect": self.custom_rect}]
            else:
                print("[1/4] Автопоиск диалоговых баблов на экране...")
                bubbles = BubbleCleaner.detect_speech_bubbles(self.frame_bgr)

            if not bubbles:
                print("[!] На экране не найдено замкнутых баблов. Используйте Alt+A для ручного выделения!")
                self.finished_bubbles.emit([])
                return

            print(f"[2/4] Распознавание текста в {len(bubbles)} баблах через Manga-OCR...")
            detected_at = time.perf_counter()
            valid_bubbles = []
            raw_texts = []

            for b in bubbles:
                if self.authorize:
                    self.authorize()
                text = self.ocr.recognize_bubble(self.frame_bgr, b["rect"])
                has_real_words = bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\a-zA-Z]{2,}', text))
                if self.custom_rect or has_real_words:
                    valid_bubbles.append(b)
                    raw_texts.append(text)

            if not raw_texts:
                print("[!] Текст внутри рамок не обнаружен.")
                self.finished_bubbles.emit([])
                return

            print(f"[3/4] Распознано ({len(raw_texts)} шт.): {raw_texts}")
            recognized_at = time.perf_counter()
            print("[4/4] Перевод через локальную модель Ollama...")
            if self.authorize:
                self.authorize()
            translated_texts = self.translator.translate_bubbles_batch(raw_texts)
            translated_at = time.perf_counter()
            print(f"[Готово] Перевод: {translated_texts}")

            dummy_img = Image.new("RGB", (100, 100))
            draw = ImageDraw.Draw(dummy_img)
            overlay_payload = []

            for b, trans_text in zip(valid_bubbles, translated_texts):
                x, y, w, h = b["rect"]
                b_rect = BubbleRect(x=x, y=y, width=w, height=h)
                font_size, lines, _ = self.typography.calculate_optimal_font_layout(
                    trans_text, b_rect, draw, padding_pct=0.06, min_font_size=9, max_font_size=22
                )
                qrect = QtCore.QRect(x, y, w, h)
                overlay_payload.append((qrect, lines, font_size, (255, 255, 255)))

            self.finished_bubbles.emit(overlay_payload)
            logging.getLogger(__name__).info(
                'Экран: детекция %.2fs, OCR %.2fs, перевод %.2fs, верстка %.2fs, всего %.2fs',
                detected_at - started, recognized_at - detected_at, translated_at - recognized_at,
                time.perf_counter() - translated_at, time.perf_counter() - started)

        except AuthError as exc:
            logging.getLogger(__name__).warning('Доступ к переводу не подтверждён: %s', exc)
            self.access_error.emit(str(exc))
            self.finished_bubbles.emit([])
        except Exception as e:
            print(f"[Ошибка пайплайна]: {e}")
            self.finished_bubbles.emit([])


class AppContext(QtCore.QObject):
    def __init__(self, overlay: ScreenOverlay, snipper: AreaSnipper, store=None, user=None, auth=None):
        super().__init__()
        self.overlay = overlay
        self.snipper = snipper
        self.snipper.area_selected.connect(self.on_area_selected)
        self.capture = ScreenCapture()
        self.store, self.user = store, user
        self.auth = auth
        self.cabinet = None
        self.shutting_down = False
        self.screen_starting = False

        print("Загрузка Manga-OCR в память...")
        from ocr.manga_ocr_local import LocalMangaOCR
        from core.translator.llm_service import MangaLLMTranslator
        self.ocr = LocalMangaOCR()
        self.translator = MangaLLMTranslator()

        font_path = "assets/animeace.ttf"
        if not os.path.exists(font_path):
            font_path = "C:/Windows/Fonts/arial.ttf"
        self.typography = AntiOverflowEngine(font_path=font_path)
        self.worker = None
        print("\n=== MangaFlow готов! ===")
        print(" -> Alt + A : Выделить бабл/область мышкой (Рекомендуется)")
        print(" -> Alt + X : Автоперевод всего экрана")
        print(" -> Alt + Z : Скрыть / Показать перевод")
        print(" -> Alt + C : Очистить экран от плашек")
        print(" -> Выход   : ПКМ по иконке в трее -> Выход (или Ctrl+C в консоли)\n")

    def start_area_snip(self):
        if self.shutting_down or (self.cabinet and self.cabinet.is_processing()):
            return
        self.snipper.start_selection()

    def on_area_selected(self, rect_tuple):
        self.run_translation(custom_rect=rect_tuple)

    def trigger_screen_translation(self):
        self.run_translation(custom_rect=None)

    def run_translation(self, custom_rect=None):
        if self.shutting_down or self.screen_starting or (self.cabinet and self.cabinet.is_processing()):
            print('[!] Выполняется пакетный перевод или завершение работы. Подождите...')
            return
        if self.worker and self.worker.isRunning():
            print("[!] Перевод уже выполняется, подождите...")
            return

        self.screen_starting = True
        try:
            self.overlay.hide()
            QtWidgets.QApplication.processEvents()
            if self.shutting_down:
                return
            QtCore.QThread.msleep(80)
            frame = self.capture.grab_primary_screen()
            self.worker = TranslationWorker(
                frame, self.ocr, self.translator, self.typography, custom_rect=custom_rect,
                authorize=self.auth.ensure_authorized if self.auth else None
            )
            self.worker.finished_bubbles.connect(self.on_translation_ready)
            self.worker.access_error.connect(self.on_access_error)
            self.worker.start()
        finally:
            self.screen_starting = False

    def on_translation_ready(self, bubbles_data: list):
        if self.shutting_down or not bubbles_data:
            return
        if len(bubbles_data) == 1 and self.overlay.bubbles_data:
            combined = self.overlay.bubbles_data + bubbles_data
            self.overlay.update_bubbles(combined)
        else:
            self.overlay.update_bubbles(bubbles_data)
        self.overlay.show()

    def on_access_error(self, message):
        self.overlay.hide()
        QtWidgets.QMessageBox.warning(None, 'MangaFlow — доступ',
                                      message + '\nПри отзыве или истечении сессии перезапустите приложение для входа.')

    def toggle_overlay(self):
        if self.overlay.isVisible():
            self.overlay.hide()
            print("Оверлей скрыт.")
        else:
            self.overlay.show()
            print("Оверлей показан.")

    def clear_overlay(self):
        self.overlay.update_bubbles([])
        self.overlay.hide()
        print("Экран очищен.")

    def open_batch_dialog(self):
        self.open_profile_window()

    def open_hotkeys_config(self):
        print("Хоткеи: Alt+A (Область), Alt+X (Экран), Alt+Z (Скрыть/Показать), Alt+C (Очистить)")

    def open_profile_window(self):
        if self.store is None or self.user is None:
            return
        if self.cabinet is None:
            from ui.cabinet_window import CabinetWindow
            self.cabinet = CabinetWindow(self, self.store, self.user)
        self.cabinet.show()
        self.cabinet.raise_()
        self.cabinet.activateWindow()

    def set_preset(self, preset_name: str):
        print(f"Выбран пресет нагрузки: {preset_name}")

    def graceful_shutdown(self):
        print("Завершение работы MangaFlow...")
        self.shutting_down = True
        self.overlay.hide()
        if self.cabinet and self.cabinet.is_processing():
            self.cabinet.worker.requestInterruption()
        self._finish_shutdown()

    def _finish_shutdown(self):
        if ((self.worker and self.worker.isRunning()) or
                (self.cabinet and self.cabinet.is_processing())):
            QtCore.QTimer.singleShot(100, self._finish_shutdown)
            return
        QtWidgets.QApplication.quit()


def main():
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"

    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    instance_lock = QtCore.QLockFile(str(DEFAULT_DB) + '.lock')
    if not instance_lock.tryLock(0):
        QtWidgets.QMessageBox.information(None, 'MangaFlow', 'MangaFlow уже запущен или база заблокирована.')
        return

    try:
        store = Store()
        auth = create_auth_client()
        hwid = get_hwid()
        user = auth.automatic_login(hwid)
        if user is None:
            login = LoginDialog(auth, hwid)
            if login.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            user = login.user
        user = store.link_remote_user(auth.url, user)
        store.recover_interrupted(user['id'])
    except Exception as exc:
        logging.exception('Ошибка авторизации')
        QtWidgets.QMessageBox.critical(None, 'MangaFlow — авторизация', str(exc))
        return

    timer = QtCore.QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)

    overlay = ScreenOverlay()
    snipper = AreaSnipper()
    ctx = AppContext(overlay, snipper, store, user, auth)
    signal.signal(signal.SIGINT, lambda *args: ctx.graceful_shutdown())
    tray = MangaFlowTray(ctx)
    tray.show()

    hotkey_listener = GlobalHotkeyListener()
    hotkey_listener.translate_screen_signal.connect(ctx.trigger_screen_translation)
    hotkey_listener.translate_area_signal.connect(ctx.start_area_snip)
    hotkey_listener.toggle_visibility_signal.connect(ctx.toggle_overlay)
    hotkey_listener.emergency_stop_signal.connect(ctx.clear_overlay)
    hotkey_listener.start()

    exit_code = app.exec()
    # The legacy native hotkey listener blocks in GetMessageW. All translation
    # workers and database writes are finished before the event loop quits.
    sys.stdout.flush()
    sys.stderr.flush()
    instance_lock.unlock()
    os._exit(exit_code)


if __name__ == "__main__":
    main()
