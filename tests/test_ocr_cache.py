import importlib.util
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image
from core.cache import BoundedCache


class OCRCacheTests(unittest.TestCase):
    def test_exact_image_cache_shared_by_both_ocr_entry_points(self):
        # Load the adapter with a fake model package; no CUDA/model downloads.
        spec = importlib.util.spec_from_file_location('ocr_adapter_test', Path('ocr/manga_ocr_local.py'))
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'manga_ocr': SimpleNamespace(MangaOcr=Mock())}):
            spec.loader.exec_module(module)
        engine = module.LocalMangaOCR.__new__(module.LocalMangaOCR)
        engine.mocr = Mock(return_value='ん…')
        engine._inference_mode = nullcontext
        engine._cache = BoundedCache(2)
        image = Image.new('RGB', (50, 50), 'white')
        self.assertEqual('ん…', engine._recognize_image(image))
        self.assertEqual('ん…', engine._recognize_image(image.copy()))
        self.assertEqual(1, engine.mocr.call_count)
        image.putpixel((20, 20), (0, 0, 0))
        engine._recognize_image(image)
        self.assertEqual(2, engine.mocr.call_count)

    def test_lru_is_bounded_and_reads_refresh_recency(self):
        cache = BoundedCache(2)
        cache.put('a', 'A')
        cache.put('b', 'B')
        self.assertEqual('A', cache.get('a'))
        cache.put('c', 'C')
        self.assertIsNone(cache.get('b'))
        self.assertEqual('A', cache.get('a'))
        self.assertEqual('C', cache.get('c'))


if __name__ == '__main__':
    unittest.main()
