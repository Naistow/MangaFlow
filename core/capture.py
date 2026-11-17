import mss
import numpy as np
import cv2

class ScreenCapture:
    def __init__(self):
        self.sct = mss.mss()

    def grab_primary_screen(self) -> np.ndarray:
        """Захватывает основной монитор и возвращает массив BGR для OpenCV."""
        monitor = self.sct.monitors[1]  # 1 — основной монитор
        sct_img = self.sct.grab(monitor)
        img_bgra = np.array(sct_img)
        img_bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
        return img_bgr