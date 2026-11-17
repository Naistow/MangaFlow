import logging
import zipfile
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from database.store import STORAGE

log = logging.getLogger(__name__)


class BatchProcessor(QThread):
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(int, str, str)

    def __init__(self, store, batch_id, renderer, storage=STORAGE, parent=None, authorize=None):
        super().__init__(parent)
        self.store, self.batch_id, self.renderer = store, batch_id, renderer
        self.storage = Path(storage)
        self.authorize = authorize

    def run(self):
        output = self.storage / f'batch_{self.batch_id}'
        archive = self.storage / f'batch_{self.batch_id}.zip'
        status, message = 'failed', ''
        try:
            output.mkdir(parents=True, exist_ok=True)
            self.store.update_batch(self.batch_id, 'processing', output)
            pages = self.store.pages(self.batch_id)
            successes = []
            failures = 0
            partial_pages = 0
            warnings_report = []
            for i, page in enumerate(pages, 1):
                if self.authorize:
                    self.authorize()
                if self.isInterruptionRequested():
                    raise InterruptedError('Пакет остановлен пользователем.')
                self.progress.emit(i - 1, len(pages), f"Страница {i}: {page['filename']}")
                destination = output / f'{i:04d}_{Path(page["filename"]).stem}.png'
                self.store.update_page(page['id'], 'processing')
                try:
                    result = self.renderer.render(page['source_path'], destination, self.isInterruptionRequested)
                    warnings = getattr(result, 'warnings', [])
                    page_status = 'partial' if warnings else 'completed'
                    if warnings:
                        partial_pages += 1
                        details = '\n'.join(warnings)
                        warnings_report.append(f"{page['filename']}\n{details}")
                        self.progress.emit(i, len(pages), f"{page['filename']}: сохранена с предупреждениями; баблов переведено: {result.rendered}, пропущено: {len(warnings)}.\n{details}")
                    self.store.update_page(page['id'], page_status, destination,
                                           error='\n'.join(warnings) if warnings else None)
                    successes.append(destination)
                except InterruptedError:
                    self.store.update_page(page['id'], 'cancelled')
                    raise
                except Exception as exc:
                    failures += 1
                    log.exception('Ошибка страницы %s', page['filename'])
                    self.store.update_page(page['id'], 'failed', error=str(exc))
                    self.progress.emit(i, len(pages), f"Ошибка {page['filename']}: {exc}")
                self.progress.emit(i, len(pages), f'Обработано {i}/{len(pages)}; ошибок: {failures}')
            if successes:
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for path in successes:
                        zip_file.write(path, path.name)
                    if warnings_report:
                        zip_file.writestr('translation_warnings.txt', '\n\n'.join(warnings_report).encode('utf-8'))
                status = 'partial' if failures or partial_pages else 'completed'
            else:
                status = 'failed'
            message = f'Страниц сохранено: {len(successes)}. С предупреждениями: {partial_pages}. Ошибок: {failures}.'
            self.store.update_batch(self.batch_id, status, output, archive if successes else None, message)
        except Exception as exc:
            status = 'cancelled' if isinstance(exc, InterruptedError) else 'failed'
            message = str(exc)
            log.exception('Пакет %s: %s', self.batch_id, message)
            with self.store.connect() as db:
                db.execute("UPDATE pages SET status=?,error=? WHERE batch_id=? AND status IN ('pending','processing')",
                           (status, message, self.batch_id))
            self.store.update_batch(self.batch_id, status, output, error=message)
        finally:
            self.completed.emit(self.batch_id, status, message)
