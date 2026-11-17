# ocr/manga_ocr_local.py
import cv2
import numpy as np
from PIL import Image
from manga_ocr import MangaOcr
import hashlib
import logging
from core.cache import BoundedCache

class LocalMangaOCR:
    def __init__(self):
        self.mocr = MangaOcr()
        import torch
        self._inference_mode = torch.inference_mode
        self.mocr.model.eval()
        self._cache = BoundedCache(512)

    def _recognize_image(self, image):
        # Hash the exact preprocessed input, not coordinates or approximate
        # similarity: a changed kana must cause a fresh model invocation.
        key = (id(self.mocr), image.mode, image.size,
               hashlib.blake2b(image.tobytes(), digest_size=16).digest())
        cached = self._cache.get(key)
        if cached is not None:
            logging.getLogger(__name__).debug('OCR cache hit')
            return cached
        with self._inference_mode():
            text = self.mocr(image).strip()
        self._cache.put(key, text)
        return text

    def recognize_page_bubble(self, image_bgr, rect):
        """Batch-only preprocessing; keep the legacy screen method unchanged."""
        from core.batch.ocr_crop import prepare_ocr_crop
        crop = prepare_ocr_crop(image_bgr, rect)
        if crop is None:
            return ''
        return self._recognize_image(crop)

    def recognize_bubble(self, image_bgr: np.ndarray, rect: tuple[int, int, int, int]) -> str:
        x, y, w, h = rect
        img_h, img_w = image_bgr.shape[:2]
        x, y = max(0, x), max(0, y)
        w, h = min(img_w - x, w), min(img_h - y, h)

        roi_bgr = image_bgr[y:y+h, x:x+w]
        if roi_bgr.size == 0:
            return ""

        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)

        _, binary_inv = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY_INV)
        
        border = 6
        if h > border * 3 and w > border * 3:
            binary_inv[:border, :] = 0
            binary_inv[-border:, :] = 0
            binary_inv[:, :border] = 0
            binary_inv[:, -border:] = 0

        coords = cv2.findNonZero(binary_inv)
        if coords is not None:
            tx, ty, tw, th = cv2.boundingRect(coords)
            if tw > 10 and th > 10:
                gray = gray[ty:ty+th, tx:tx+tw]

        padded = cv2.copyMakeBorder(gray, 18, 18, 18, 18, cv2.BORDER_CONSTANT, value=255)

        upscaled = cv2.resize(padded, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

        pil_img = Image.fromarray(upscaled).convert("RGB")
        return self._recognize_image(pil_img)
