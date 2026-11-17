"""Supplement the screen detector with enclosed bubbles containing short lines."""
import cv2
import numpy as np
from core.cleaner import BubbleCleaner


def detect_page_bubbles(frame):
    bubbles = BubbleCleaner.detect_speech_bubbles(frame)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Thin antialiased outlines can have one-pixel gaps; close those gaps before
    # searching interiors, otherwise the entire panel becomes a single region.
    dark = cv2.morphologyEx((gray < 220).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    light = 1 - dark
    count, labels, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=8)
    ih, iw = gray.shape
    for i in range(1, count):
        x, y, w, h, area = map(int, stats[i])
        if (x == 0 or y == 0 or x + w == iw or y + h == ih or
                min(w, h) < 24 or area < 300 or area > ih * iw * .5 or area < w * h * .45):
            continue
        region = (labels[y:y+h, x:x+w] == i).astype(np.uint8)
        contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        outline_area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        circularity = 4 * np.pi * outline_area / max(1, perimeter * perimeter)
        # Reject rectangular panel backgrounds and irregular spaces in artwork.
        if circularity < .35 or outline_area / (w * h) > .93:
            continue
        interior = np.zeros_like(region)
        cv2.drawContours(interior, contours, -1, 1, cv2.FILLED)
        interior = cv2.erode(interior, np.ones((11, 11), np.uint8))
        ink = ((gray[y:y+h, x:x+w] < 185) & (interior > 0)).astype(np.uint8)
        n, _, ink_stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        if not any(2 <= s[4] <= area * .25 for s in ink_stats[1:]):
            continue
        points = cv2.findNonZero(ink)
        if points is None:
            continue
        tx, ty, tw, th = cv2.boundingRect(points)
        rect = (max(0, x + tx - 14), max(0, y + ty - 14), min(iw - max(0, x + tx - 14), tw + 28), min(ih - max(0, y + ty - 14), th + 28))
        # One OCR crop per enclosed bubble, including ALL its text columns.
        remaining = []
        for b in bubbles:
            bx, by, bw, bh = b['rect']
            center_x, center_y = int(bx + bw / 2 - x), int(by + bh / 2 - y)
            if not (0 <= center_x < w and 0 <= center_y < h and interior[center_y, center_x]):
                remaining.append(b)
        bubbles = remaining + [{'rect': rect}]
    return sorted(bubbles, key=lambda b: (b['rect'][1] // 150, -b['rect'][0]))
