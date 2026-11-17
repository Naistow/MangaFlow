import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PyQt6.QtCore import QCoreApplication
from core.auth import AuthService
from core.batch.processor import BatchProcessor
from core.batch.page_renderer import PageRenderer
from core.typography import AntiOverflowEngine
from database.store import Store


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'test.db')
        auth = AuthService(self.store)
        self.user = auth.activate('Reader', auth.generate_invites()[0], 'machine')

    def test_real_qthread_partial_zip_and_user_isolation(self):
        class Renderer:
            def render(self, source, target, cancelled):
                if source.endswith('bad.jpg'):
                    raise ValueError('Unreadable image')
                Image.new('RGB', (60, 60), 'white').save(target)
        batch = self.store.create_batch(self.user['id'], 'Volume', ['good.jpg', 'bad.jpg'])
        worker = BatchProcessor(self.store, batch, Renderer(), self.root / 'storage')
        worker.start()
        self.assertTrue(worker.wait(10000))
        history = self.store.history(self.user['id'])
        self.assertEqual('partial', history[0]['status'])
        with zipfile.ZipFile(history[0]['zip_path']) as archive:
            self.assertEqual(['0001_good.png'], archive.namelist())
        self.store.delete_batch(self.user['id'] + 100, batch)
        self.assertEqual(1, len(self.store.history(self.user['id'])))
        self.store.delete_batch(self.user['id'], batch)
        self.assertEqual([], self.store.pages(batch))

    def test_bubble_warning_exports_png_and_report_as_partial(self):
        from core.batch.page_renderer import RenderResult
        class Renderer:
            def render(self, source, target, cancelled):
                Image.new('RGB', (60, 60), 'white').save(target)
                return RenderResult(rendered=2, warnings=['Бабл: оставлен оригинал. Перевод: Да'])
        batch = self.store.create_batch(self.user['id'], 'Volume', ['page.jpg'])
        worker = BatchProcessor(self.store, batch, Renderer(), self.root / 'storage')
        worker.start()
        self.assertTrue(worker.wait(10000))
        row = self.store.history(self.user['id'])[0]
        self.assertEqual('partial', row['status'])
        page = self.store.pages(batch)[0]
        self.assertEqual('partial', page['status'])
        self.assertIn('Перевод: Да', page['error'])
        with zipfile.ZipFile(row['zip_path']) as archive:
            self.assertIn('0001_page.png', archive.namelist())
            self.assertIn('Перевод: Да', archive.read('translation_warnings.txt').decode('utf-8'))

    def test_render_burns_text_and_does_not_modify_source(self):
        from types import SimpleNamespace
        source, target = self.root / 'source.png', self.root / 'translated.png'
        Image.new('RGB', (200, 200), 'white').save(source)
        before = source.read_bytes()
        font = 'C:/Windows/Fonts/arial.ttf'
        renderer = PageRenderer(SimpleNamespace(recognize_bubble=lambda *_: 'こんにちは'),
                                SimpleNamespace(translate_bubbles_batch=lambda _: ['Привет!']),
                                AntiOverflowEngine(font))
        with patch('core.batch.page_renderer.detect_page_bubbles',
                   return_value=[{'rect': (20, 20, 150, 100)}]):
            renderer.render(source, target)
        self.assertEqual(before, source.read_bytes())
        with Image.open(target) as result:
            self.assertLess(min(result.convert('L').getdata()), 128)

    def test_no_bubbles_still_exports_page(self):
        source, target = self.root / 'plain.png', self.root / 'out.png'
        Image.new('RGB', (32, 32), 'red').save(source)
        with patch('core.batch.page_renderer.detect_page_bubbles', return_value=[]):
            PageRenderer(None, None, None).render(source, target)
        self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
