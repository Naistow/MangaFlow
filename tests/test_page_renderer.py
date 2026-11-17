"""Page rendering checks without Qt, OCR models or Ollama."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageChops
import cv2
import numpy as np
from core.batch.page_renderer import PageRenderer
from core.batch.bubble_cleanup import clean_text_region, BubbleRegionError


class PageRendererTests(unittest.TestCase):
    def test_two_ocr_columns_in_one_bubble_are_translated_together(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'in.png', Path(directory) / 'out.png'
            page = np.full((260, 320, 3), 140, np.uint8)
            cv2.ellipse(page, (160, 130), (100, 105), 0, 0, 360, (255, 255, 255), -1)
            cv2.ellipse(page, (160, 130), (100, 105), 0, 0, 360, (0, 0, 0), 3)
            Image.fromarray(page).save(source)
            from unittest.mock import Mock
            ocr = SimpleNamespace(recognize_bubble=Mock(side_effect=['甲乙', '丙丁']))
            translate = Mock(return_value=['Привет'])
            renderer = PageRenderer(ocr, SimpleNamespace(translate_bubbles_batch=translate),
                                    SimpleNamespace(font_path='C:/Windows/Fonts/arial.ttf'))
            with patch('core.batch.page_renderer.detect_page_bubbles', return_value=[
                    {'rect': (115, 85, 35, 70)}, {'rect': (160, 85, 35, 70)}]):
                result = renderer.render(source, target)
            translate.assert_called_once_with(['甲乙 丙丁'])
            self.assertEqual(1, result.rendered)
            self.assertEqual([], result.warnings)

    def test_narrow_bubble_uses_wider_safe_rect_before_shortening(self):
        from unittest.mock import Mock
        from core.batch.bubble_cleanup import inner_rect_candidates
        # Reproduce the reported 64x137 / 68x126 geometry, with both
        # rectangles fully inside the same protected contour mask.
        safe = np.zeros((180, 110), np.uint8)
        safe[20:157, 20:84] = 1
        safe[25:151, 18:86] = 1
        primary = (20, 20, 64, 137)
        compact = Mock(side_effect=AssertionError('The full translation already fits'))
        renderer = PageRenderer(None, SimpleNamespace(compact_bubble_translation=compact),
                                SimpleNamespace(font_path='C:/Windows/Fonts/arial.ttf'))
        text = 'Может, лёгкая тепловая ударка? Говорят, можно заболеть даже в прохладном помещении.'
        candidate, (font, block, _, bounds), (x, y, w, h) = renderer._fit_translation_in_regions(
            '軽い熱中症かな？涼しい室内でもなるんだって', text,
            [primary] + inner_rect_candidates(safe), lambda: False)
        compact.assert_not_called()
        self.assertEqual(text, candidate)
        self.assertEqual(text.split(), block.split())
        self.assertGreater(w, primary[2])
        self.assertGreaterEqual(font.size, 11)
        self.assertTrue(np.all(safe[y:y+h, x:x+w]))
        self.assertLessEqual(bounds[2] - bounds[0], w - 4)
        self.assertLessEqual(bounds[3] - bounds[1], h - 4)

    def test_missed_bubble_gets_compact_translation_at_readable_size(self):
        from unittest.mock import Mock
        compact = Mock(return_value='Лицо красное. У тебя жар?')
        renderer = PageRenderer(None, SimpleNamespace(compact_bubble_translation=compact),
                                SimpleNamespace(font_path='C:/Windows/Fonts/arial.ttf'))
        candidate, (font, block, _, bounds) = renderer._fit_translation(
            '顔が少し赤いね熱はある？',
            'У тебя немного покраснел румянец. Может, у тебя жар?', 54, 96, lambda: False)
        compact.assert_called_once()
        self.assertEqual('Лицо красное. У тебя жар?', candidate)
        self.assertGreaterEqual(font.size, 11)
        self.assertEqual(candidate.split(), block.split())
        self.assertLessEqual(bounds[2] - bounds[0], 50)
        self.assertLessEqual(bounds[3] - bounds[1], 92)

    def test_unsafe_bubble_keeps_original_and_next_bubble_is_rendered(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source.png', Path(directory) / 'result.png'
            original = np.full((120, 260, 3), 255, np.uint8)
            original[45:60, 40:50] = 0
            original[45:60, 185:195] = 0
            Image.fromarray(original).save(source)
            bad, good = (10, 20, 90, 70), (150, 20, 90, 70)
            def cleanup(frame, rect):
                if rect == bad:
                    raise BubbleRegionError('Не найдена безопасная внутренняя область бабла.')
                return clean_text_region(frame, rect)
            renderer = PageRenderer(SimpleNamespace(recognize_bubble=lambda *_: 'ん…'),
                                    SimpleNamespace(translate_bubbles_batch=lambda texts: ['Да'] * len(texts)),
                                    SimpleNamespace(font_path='C:/Windows/Fonts/arial.ttf'))
            with patch('core.batch.page_renderer.detect_page_bubbles', return_value=[{'rect': bad}, {'rect': good}]), \
                    patch('core.batch.page_renderer.clean_text_region', side_effect=cleanup):
                result = renderer.render(source, target)
            self.assertEqual(1, result.rendered)
            self.assertEqual(1, len(result.warnings))
            self.assertIn('Перевод: Да', result.warnings[0])
            with Image.open(target) as output:
                actual = np.array(output)
            np.testing.assert_array_equal(original[:, :110], actual[:, :110])
            self.assertTrue(np.any(original[:, 150:] != actual[:, 150:]))

    def test_unfit_translation_preserves_original_without_failing_page(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'in.png', Path(directory) / 'out.png'
            Image.new('RGB', (100, 100), 'white').save(source)
            renderer = PageRenderer(SimpleNamespace(recognize_bubble=lambda *_: 'ん…'),
                                    SimpleNamespace(translate_bubbles_batch=lambda _: ['Длинная реплика ' * 100]),
                                    SimpleNamespace(font_path='C:/Windows/Fonts/arial.ttf'))
            with patch('core.batch.page_renderer.detect_page_bubbles', return_value=[{'rect': (20, 20, 40, 40)}]):
                result = renderer.render(source, target)
            self.assertEqual(0, result.rendered)
            self.assertEqual(1, len(result.warnings))
            with Image.open(source) as before, Image.open(target) as after:
                self.assertIsNone(ImageChops.difference(before, after).getbbox())

    def test_translation_preserves_oval_contour_and_gray_artwork(self):
        page = np.full((180, 220, 3), 130, np.uint8)
        cv2.ellipse(page, (110, 90), (85, 70), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(page, (110, 90), (85, 70), 0, 0, 360, (0, 0, 0), 3)
        contour = np.all(page == 0, axis=2)
        cv2.putText(page, 'HI', (90, 90), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'in.png', Path(directory) / 'out.png'
            Image.fromarray(page).save(source)
            from core.typography import AntiOverflowEngine
            renderer = PageRenderer(
                SimpleNamespace(recognize_bubble=lambda *_: 'こんにちは'),
                SimpleNamespace(translate_bubbles_batch=lambda _: ['Привет!']),
                AntiOverflowEngine('C:/Windows/Fonts/arial.ttf'))
            with patch('core.batch.page_renderer.detect_page_bubbles',
                       return_value=[{'rect': (65, 50, 90, 80)}]):
                renderer.render(source, target)
            with Image.open(target) as result:
                output = np.array(result)
            np.testing.assert_array_equal(output[contour], page[contour])
            outside = page[:, :, 0] == 130
            np.testing.assert_array_equal(output[outside], page[outside])
            self.assertTrue(np.any(output != page))

    def test_small_region_handles_fractional_pillow_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.png'
            destination = Path(directory) / 'result.png'
            Image.new('RGB', (120, 100), 'white').save(source)
            original_bytes = source.read_bytes()
            typography = SimpleNamespace(
                font_path='C:/Windows/Fonts/arial.ttf',
                )
            renderer = PageRenderer(
                SimpleNamespace(recognize_bubble=lambda *_: 'こんにちは'),
                SimpleNamespace(translate_bubbles_batch=lambda _: ['Да']),
                typography)
            with patch('core.batch.page_renderer.detect_page_bubbles',
                       return_value=[{'rect': (30, 25, 50, 40)}]):
                renderer.render(source, destination)
            self.assertEqual(original_bytes, source.read_bytes())
            with Image.open(destination) as result:
                self.assertEqual((120, 100), result.size)
                difference = ImageChops.difference(result, Image.new('RGB', result.size, 'white'))
                bounds = difference.getbbox()
                self.assertIsNotNone(bounds)
                self.assertGreaterEqual(bounds[0], 30)
                self.assertGreaterEqual(bounds[1], 25)
                self.assertLessEqual(bounds[2], 80)
                self.assertLessEqual(bounds[3], 65)

    def test_short_lines_ocr_all_originals_before_translation_in_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source.png', Path(directory) / 'result.png'
            Image.new('RGB', (260, 120), 'white').save(source)
            calls, groups = [], []
            def recognize(frame, rect):
                self.assertFalse(frame.flags.writeable)
                self.assertTrue(np.all(frame == 255))
                calls.append(rect)
                return 'ん…'
            def translate(texts):
                self.assertEqual(2, len(calls))
                groups.append(texts)
                return ['Да'] * len(texts)
            renderer = PageRenderer(SimpleNamespace(recognize_bubble=recognize),
                                    SimpleNamespace(translate_bubbles_batch=translate),
                                    SimpleNamespace(font_path='C:/Windows/Fonts/arial.ttf'))
            with patch('core.batch.page_renderer.detect_page_bubbles',
                       return_value=[{'rect': (10, 20, 90, 70)}, {'rect': (150, 20, 90, 70)}]):
                renderer.render(source, target)
            self.assertEqual([['ん…', 'ん…']], groups)
            self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
