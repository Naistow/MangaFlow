import unittest
import cv2
import numpy as np
from core.batch.bubble_cleanup import clean_text_region


class BubbleCleanupTests(unittest.TestCase):
    def test_rectangular_narration_keeps_frame_and_cleans_internal_text(self):
        page = np.full((330, 220, 3), 140, np.uint8)
        cv2.rectangle(page, (55, 30), (165, 300), (255, 255, 255), -1)
        cv2.rectangle(page, (55, 30), (165, 300), (0, 0, 0), 2)
        border = np.all(page == 0, axis=2)
        cv2.putText(page, 'HI', (85, 160), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 0), 2)
        cleaned, (x, y), (_, _, w, h), _ = clean_text_region(page, (70, 60, 80, 210))
        result = page.copy()
        result[y:y+cleaned.shape[0], x:x+cleaned.shape[1]] = cleaned
        np.testing.assert_array_equal(page[border], result[border])
        self.assertGreater(w, 60)
        self.assertGreater(h, 150)
        self.assertTrue(np.any(result != page))

    def test_connected_tall_text_inside_contour_is_not_protected_as_art(self):
        page = np.full((400, 300, 3), 130, np.uint8)
        cv2.ellipse(page, (150, 200), (85, 175), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(page, (150, 200), (85, 175), 0, 0, 360, (0, 0, 0), 3)
        border = np.all(page == 0, axis=2)
        cv2.rectangle(page, (135, 115), (165, 285), (0, 0, 0), -1)
        cleaned, (x, y), _, _ = clean_text_region(page, (115, 100, 70, 200))
        result = page.copy()
        result[y:y+cleaned.shape[0], x:x+cleaned.shape[1]] = cleaned
        np.testing.assert_array_equal(page[border], result[border])
        self.assertGreater(result[120:280, 140:160].mean(), 220)

    def test_neighbor_bubble_does_not_steal_layout_of_open_text_field(self):
        page = np.full((400, 300, 3), 255, np.uint8)
        cv2.ellipse(page, (170, 145), (50, 50), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(page, 'HI', (150, 260), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 0), 2)
        _, (ox, oy), (x, y, w, h), _ = clean_text_region(page, (120, 180, 100, 180))
        self.assertGreaterEqual(oy + y, 185)
        self.assertGreater(h, 100)

    def test_thin_gray_outline_does_not_select_white_panel_background(self):
        page = np.full((220, 280, 3), 255, np.uint8)
        cv2.rectangle(page, (5, 5), (274, 214), (0, 0, 0), 1)
        cv2.ellipse(page, (160, 110), (45, 80), 0, 0, 360, (200, 200, 200), 1)
        cv2.putText(page, 'HI', (145, 110), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 1)
        cleaned, (ox, oy), (x, y, w, h), _ = clean_text_region(page, (125, 70, 70, 90))
        self.assertGreater(ox + x, 115)
        self.assertLess(ox + x + w, 205)
        border = np.all(page == 200, axis=2)
        result = page.copy()
        result[oy:oy+cleaned.shape[0], ox:ox+cleaned.shape[1]] = cleaned
        np.testing.assert_array_equal(page[border], result[border])

    def bubble(self):
        page = np.full((220, 260, 3), 120, np.uint8)
        cv2.ellipse(page, (130, 110), (95, 80), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(page, (130, 110), (95, 80), 0, 0, 360, (0, 0, 0), 3)
        border = np.all(page == 0, axis=2)
        cv2.putText(page, 'HI', (105, 110), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 0), 2)
        return page, border

    def test_erases_letters_preserves_contour_and_outside_pixels(self):
        page, border = self.bubble()
        cleaned, (x, y), (tx, ty, w, h), safe = clean_text_region(page, (80, 65, 100, 85))
        result = page.copy()
        result[y:y + cleaned.shape[0], x:x + cleaned.shape[1]] = cleaned
        np.testing.assert_array_equal(result[border], page[border])
        np.testing.assert_array_equal(result[page[:, :, 0] == 120], page[page[:, :, 0] == 120])
        self.assertTrue(np.all(safe[ty:ty + h, tx:tx + w]))
        text = np.all(page[90:113, 103:132] < 190, axis=2)
        self.assertGreater(np.count_nonzero(text), 10)
        self.assertGreater(result[90:113, 103:132][text].mean(), 220)

    def test_open_contour_keeps_long_strokes(self):
        page = np.full((160, 180, 3), 255, np.uint8)
        cv2.line(page, (25, 35), (150, 35), (0, 0, 0), 3)
        cv2.putText(page, 'HI', (65, 80), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 1)
        cleaned, (x, y), _, _ = clean_text_region(page, (30, 30, 120, 80))
        result = page.copy()
        result[y:y + cleaned.shape[0], x:x + cleaned.shape[1]] = cleaned
        np.testing.assert_array_equal(page[32:39], result[32:39])


if __name__ == '__main__':
    unittest.main()
