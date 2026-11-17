import re
import shutil
from pathlib import Path
from PyQt6 import QtCore, QtGui, QtWidgets
from core.batch.page_renderer import PageRenderer
from core.batch.processor import BatchProcessor
from ui.cabinet_dashboard import DashboardLayout

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}


class CabinetWindow(DashboardLayout, QtWidgets.QMainWindow):
    def __init__(self, context, store, user):
        super().__init__()
        self.context, self.store, self.user = context, store, user
        self.paths, self.worker, self.rows = [], None, []
        self.build_dashboard()
        self.refresh()

    def report_error(self, exc):
        QtWidgets.QMessageBox.warning(self, 'MangaFlow', str(exc))

    def set_paths(self, paths):
        self.paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
        self.selection.setText(f'Выбрано страниц: {len(self.paths)}')

    def pick_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, 'Страницы манги', '', 'Изображения (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
        if paths:
            self.set_paths(paths)

    def pick_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Папка с мангой')
        if folder:
            try:
                paths = [p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
                paths.sort(key=lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', p.name)])
                self.set_paths(paths)
            except OSError as exc:
                self.report_error(exc)

    def is_processing(self):
        return self.worker is not None and self.worker.isRunning()

    def start_batch(self):
        if (self.context.shutting_down or self.context.screen_starting or self.is_processing()
                or (self.context.worker and self.context.worker.isRunning())):
            self.report_error('Перевод уже выполняется. Дождитесь завершения.')
            return
        if not self.paths or not self.title.text().strip():
            self.report_error('Выберите страницы и укажите название тома.')
            return
        try:
            batch_id = self.store.create_batch(self.user['id'], self.title.text().strip(), self.paths)
            authorize = self.context.auth.ensure_authorized if self.context.auth else None
            self.worker = BatchProcessor(self.store, batch_id, PageRenderer(
                self.context.ocr, self.context.translator, self.context.typography, authorize=authorize),
                parent=self, authorize=authorize)
            self.worker.progress.connect(self.on_progress)
            self.worker.completed.connect(self.on_completed)
            self.worker.finished.connect(self.on_finished)
            self.start.setEnabled(False)
            self.progress.setRange(0, len(self.paths))
            self.progress.setValue(0)
            self.status.setText('Подготовка страниц…')
            self.summary_status.setText('Статус: перевод выполняется')
            self.worker.start()
            self.refresh()
        except Exception as exc:
            self.start.setEnabled(True)
            self.report_error(exc)

    def on_progress(self, current, total, message):
        self.status.setText(message)
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.log.appendPlainText(message)

    def on_completed(self, batch_id, status, message):
        self.status.setText(f'{status} — {message}')
        self.summary_status.setText(f'Статус: {status}')
        self.log.appendPlainText(f'Пакет #{batch_id}: {status}. {message}')
        self.refresh()

    def on_finished(self):
        self.start.setEnabled(True)

    def refresh(self):
        try:
            self.rows = self.store.history(self.user['id'])
            volumes, pages = self.store.statistics(self.user['id'])
            self.stats_labels[0].setText(str(volumes))
            self.stats_labels[1].setText(str(pages))
            self.table.setRowCount(len(self.rows))
            for i, row in enumerate(self.rows):
                for j, key in enumerate(('title', 'created_at', 'page_count', 'status')):
                    self.table.setItem(i, j, QtWidgets.QTableWidgetItem(str(row[key])))
        except Exception as exc:
            self.report_error(exc)

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def save_zip(self):
        row = self.selected()
        if not row or not row['zip_path'] or not Path(row['zip_path']).is_file():
            self.report_error('Выберите пакет с готовым ZIP-архивом.')
            return
        target, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Сохранить ZIP', Path(row['zip_path']).name, 'ZIP (*.zip)')
        if target:
            try:
                if Path(target).resolve() != Path(row['zip_path']).resolve():
                    shutil.copy2(row['zip_path'], target)
            except OSError as exc:
                self.report_error(exc)

    def open_folder(self):
        row = self.selected()
        if row and row['output_dir'] and Path(row['output_dir']).is_dir():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(row['output_dir']))
        else:
            self.report_error('Папка результатов пока недоступна.')

    def delete_record(self):
        row = self.selected()
        if not row:
            return
        if self.is_processing() and row['id'] == self.worker.batch_id:
            self.report_error('Дождитесь завершения пакета.')
            return
        try:
            self.store.delete_batch(self.user['id'], row['id'])
            self.refresh()
        except Exception as exc:
            self.report_error(exc)

    def closeEvent(self, event):
        # Keep ownership of the running worker while the cabinet is hidden.
        self.hide()
        event.ignore()
