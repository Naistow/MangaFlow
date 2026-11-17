"""Original-image OCR crops with ink validation and generous white margins."""
import cv2
import numpy as np
from PIL import Image


def prepare_ocr_crop(frame, rect, margin=20, padding=24):
    x, y, w, h = map(int, rect)
    ih, iw = frame.shape[:2]
    left, top = max(0, x - margin), max(0, y - margin)
    right, bottom = min(iw, x + w + margin), min(ih, y + h + margin)
    gray = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY) if right > left and bottom > top else None
    if gray is None:
        return None
    count, labels, stats, _ = cv2.connectedComponentsWithStats((gray < 185).astype(np.uint8), connectivity=8)
    boxes = []
    for i in range(1, count):
        cx, cy, cw, ch, area = map(int, stats[i])
        # Reject borders; accept a single short kana or punctuation component.
        if area < 2 or cw >= max(12, w * .95) or ch >= max(12, h * .95):
            continue
        if cx + cw + left > x and cy + ch + top > y and cx + left < x + w and cy + top < y + h:
            boxes.append((cx, cy, cw, ch))
    if not boxes:
        return None
    x1 = max(0, min(b[0] for b in boxes) - margin)
    y1 = max(0, min(b[1] for b in boxes) - margin)
    x2 = min(gray.shape[1], max(b[0] + b[2] for b in boxes) + margin)
    y2 = min(gray.shape[0], max(b[1] + b[3] for b in boxes) + margin)
    crop = gray[y1:y2, x1:x2]
    # Bound model input instead of upscaling exceptionally large crops without limit.
    scale = min(2.0, 1488 / max(crop.shape))
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=255)
    return Image.fromarray(crop).convert('RGB')
