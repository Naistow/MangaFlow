import unittest
from unittest.mock import patch
import cv2
import numpy as np
from core.batch.ocr_crop import prepare_ocr_crop
from core.batch.text_layout import fit_text
from core.batch.detection import detect_page_bubbles


class BatchTextTests(unittest.TestCase):
    def test_blank_crop_is_rejected(self):
        frame = np.full((120, 120, 3), 255, np.uint8)
        self.assertIsNone(prepare_ocr_crop(frame, (20, 20, 70, 70)))

    def test_single_glyph_near_edge_retains_ink_and_white_padding(self):
        frame = np.full((80, 80, 3), 255, np.uint8)
        frame[1:8, 1:4] = 0
        original = frame.copy()
        crop = prepare_ocr_crop(frame, (0, 0, 20, 20))
        self.assertIsNotNone(crop)
        array = np.array(crop)
        self.assertTrue(np.all(array[:24] == 255))
        self.assertTrue(np.all(array[-24:] == 255))
        self.assertTrue(np.all(array[:, :24] == 255))
        self.assertTrue(np.all(array[:, -24:] == 255))
        self.assertTrue(np.any(array[24:-24, 24:-24] < 185))
        np.testing.assert_array_equal(frame, original)

    def test_enclosed_short_line_is_detected_without_legacy_hits(self):
        frame = np.full((200, 240, 3), 150, np.uint8)
        cv2.ellipse(frame, (120, 100), (75, 65), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(frame, (120, 100), (75, 65), 0, 0, 360, (0, 0, 0), 3)
        cv2.putText(frame, '?', (110, 110), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
        with patch('core.batch.detection.BubbleCleaner.detect_speech_bubbles', return_value=[]):
            bubbles = detect_page_bubbles(frame)
        self.assertEqual(1, len(bubbles))
        self.assertIsNotNone(prepare_ocr_crop(frame, bubbles[0]['rect']))

    def test_layout_uses_readable_size_and_same_multiline_bounds(self):
        font, block, spacing, bounds = fit_text('Очень длинная реплика с переносом слов', 'C:/Windows/Fonts/arial.ttf', 150, 95)
        self.assertGreaterEqual(font.size, 11)
        self.assertLessEqual(font.size, 18)
        self.assertIn('\n', block)
        self.assertLessEqual(bounds[2] - bounds[0], 146)
        self.assertLessEqual(bounds[3] - bounds[1], 91)

    def test_impossible_layout_reports_error_instead_of_microscopic_text(self):
        with self.assertRaisesRegex(ValueError, '11px'):
            fit_text('Реплика ' * 100, 'C:/Windows/Fonts/arial.ttf', 25, 25)

    def test_words_are_never_split_across_lines(self):
        text = 'Господин, вы плохо выглядите. Ты в порядке?'
        _, block, _, _ = fit_text(text, 'C:/Windows/Fonts/arial.ttf', 100, 140)
        self.assertEqual(text.split(), block.split())

    def test_long_word_reports_overflow_instead_of_character_wrapping(self):
        with self.assertRaises(ValueError):
            fit_text('температуры', 'C:/Windows/Fonts/arial.ttf', 35, 150)

    def test_punctuation_stays_with_preceding_word(self):
        _, block, _, _ = fit_text('Эй !...', 'C:/Windows/Fonts/arial.ttf', 65, 80)
        self.assertEqual('Эй!...', block)


if __name__ == '__main__':
    unittest.main()
