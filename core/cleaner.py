# core/cleaner.py
from typing import Tuple, List
import cv2
import numpy as np

class BubbleCleaner:
    @staticmethod
    def detect_speech_bubbles(image_bgr: np.ndarray, offset_x: int = 0, offset_y: int = 0) -> List[dict]:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        img_h, img_w = gray.shape

        _, pure_white = cv2.threshold(gray, 232, 255, cv2.THRESH_BINARY)
        _, pure_black = cv2.threshold(gray, 155, 255, cv2.THRESH_BINARY_INV)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(pure_black, connectivity=8)
        valid_labels = np.zeros(num_labels, dtype=np.uint8)

        for i in range(1, num_labels):
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            area = stats[i, cv2.CC_STAT_AREA]

            if 5 <= area <= 750 and 2 <= w <= 38 and 2 <= h <= 42:
                x1, y1 = max(0, x - 4), max(0, y - 4)
                x2, y2 = min(img_w, x + w + 4), min(img_h, y + h + 4)
                ring_white = pure_white[y1:y2, x1:x2]
                ring_black = pure_black[y1:y2, x1:x2]
                non_black = np.sum(ring_black == 0)
                if non_black > 0:
                    white_purity = np.sum(ring_white > 0) / float(non_black)
                    if white_purity > 0.80:
                        valid_labels[i] = 255

        valid_chars_mask = valid_labels[labels]

        kernel_col = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 26))
        text_clusters = cv2.dilate(valid_chars_mask, kernel_col, iterations=1)

        contours, _ = cv2.findContours(text_clusters, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        tight_rects = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h

            if 500 <= area <= 55000 and 18 <= w <= 220 and 30 <= h <= 310:
                aspect = float(w) / h
                if 0.16 <= aspect <= 1.60:
                    roi_chars = valid_chars_mask[y:y+h, x:x+w]
                    n_chars, _, _, _ = cv2.connectedComponentsWithStats(roi_chars, connectivity=8)
                    char_count = n_chars - 1

                    roi_white = pure_white[y:y+h, x:x+w]
                    roi_black = pure_black[y:y+h, x:x+w]
                    non_ink = np.sum(roi_black == 0)
                    bg_purity = np.sum(roi_white > 0) / float(max(1, non_ink))

                    if char_count >= 4 and bg_purity >= 0.80:
                        tight_rects.append((x, y, w, h))

        merged = list(tight_rects)
        changed = True
        while changed:
            changed = False
            new_merged = []
            used = [False] * len(merged)
            for i in range(len(merged)):
                if used[i]:
                    continue
                rx, ry, rw, rh = merged[i]
                for j in range(i + 1, len(merged)):
                    if used[j]:
                        continue
                    mx, my, mw, mh = merged[j]
                    ox = max(0, min(rx + rw, mx + mw) - max(rx, mx))
                    oy = max(0, min(ry + rh, my + mh) - max(ry, my))
                    if ox > 6 and oy > 6:
                        nx, ny = min(rx, mx), min(ry, my)
                        nw = max(rx + rw, mx + mw) - nx
                        nh = max(ry + rh, my + mh) - ny
                        if nw <= 165 and nh <= 235:
                            rx, ry, rw, rh = nx, ny, nw, nh
                            used[j] = True
                            changed = True
                new_merged.append((rx, ry, rw, rh))
            merged = new_merged

        bubbles = []
        for (x, y, w, h) in merged:
            pad_x, pad_y = 14, 12
            bx = max(0, x - pad_x)
            by = max(0, y - pad_y)
            bw = min(img_w - bx, w + pad_x * 2)
            bh = min(img_h - by, h + pad_y * 2)
            bubbles.append({"rect": (bx + offset_x, by + offset_y, bw, bh)})

        bubbles.sort(key=lambda b: (b["rect"][1] // 150, -b["rect"][0]))
        return bubbles[:20]

    @staticmethod
    def mask_and_clean_bubble(image_bgr: np.ndarray, bubble_meta: dict) -> Tuple[np.ndarray, tuple]:
        return image_bgr, (255, 255, 255)
