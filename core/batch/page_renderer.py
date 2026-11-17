import re
import logging
import time
from dataclasses import dataclass, field
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from core.batch.bubble_cleanup import clean_text_region, inner_rect_candidates, BubbleRegionError
from core.batch.detection import detect_page_bubbles
from core.batch.text_layout import fit_text, TextLayoutError

log = logging.getLogger(__name__)


@dataclass
class RenderResult:
    rendered: int = 0
    warnings: list[str] = field(default_factory=list)


class PageRenderer:
    def __init__(self, ocr, translator, typography, authorize=None):
        self.ocr, self.translator, self.typography = ocr, translator, typography
        self.authorize = authorize

    def _fit_translation(self, source, translated, width, height, cancelled):
        candidate, layout, _ = self._fit_translation_in_regions(
            source, translated, [(0, 0, width, height)], cancelled)
        return candidate, layout

    def _fit_translation_in_regions(self, source, translated, rectangles, cancelled):
        candidate = translated
        compact = getattr(self.translator, 'compact_bubble_translation', None)
        _, _, width, height = max(rectangles, key=lambda rect: rect[2] * rect[3])
        for attempt in range(3):
            if self.authorize:
                self.authorize()
            fits, last_error = [], None
            for rect in rectangles:
                if cancelled():
                    raise InterruptedError('Пакет остановлен.')
                try:
                    layout = fit_text(candidate, self.typography.font_path, rect[2], rect[3])
                    fits.append((rect, layout))
                except TextLayoutError as exc:
                    last_error = exc
            if fits:
                rect, layout = max(fits, key=lambda item: (item[1][0].size, item[0][2] * item[0][3]))
                if rect != rectangles[0]:
                    log.info('Подобрана безопасная область %d×%d вместо %d×%d; шрифт %dpx',
                             rect[2], rect[3], rectangles[0][2], rectangles[0][3], layout[0].size)
                return candidate, layout, rect
            if attempt == 2 or compact is None:
                raise last_error
            budget = max(8, min(int(len(candidate) * .7), int((width - 4) * (height - 4) / 85)))
            shorter = compact(source, candidate, budget, max(2, int((width - 4) / 6)))
            if not shorter or shorter == candidate:
                raise last_error
            log.info('Повторная верстка бабла %d×%d: %d → %d символов',
                     width, height, len(candidate), len(shorter))
            candidate = shorter

    def render(self, source, destination, cancelled=lambda: False):
        started = time.perf_counter()
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
        # Immutable source for ALL OCR calls; never pass the cleaned image.
        frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        frame.setflags(write=False)
        recognized = []
        recognize = getattr(self.ocr, 'recognize_page_bubble', None) or getattr(self.ocr, 'recognize_bubble', None)
        bubbles = detect_page_bubbles(frame)
        detected_at = time.perf_counter()
        log.info('Страница %s: найдено областей: %d', source, len(bubbles))
        for bubble in bubbles:
            if self.authorize:
                self.authorize()
            if cancelled():
                raise InterruptedError('Пакет остановлен.')
            text = recognize(frame, bubble['rect']).strip()
            if re.search(r'[\u3040-\u30ff\u4e00-\u9faf\u0400-\u04ffA-Za-z0-9!?！？…]', text):
                recognized.append((bubble, text))
        log.info('Страница %s: OCR подтвердил %d/%d областей', source, len(recognized), len(bubbles))
        log.info('Страница: загрузка/детекция %.2fs, OCR %.2fs',
                 detected_at - started, time.perf_counter() - detected_at)
        # Resolve geometry once after ALL source OCR, and join detector clusters
        # that refer to the same bubble rather than dropping the second cluster
        # later as an overlapping translation.
        prepared = []
        for bubble, text in recognized:
            if cancelled():
                raise InterruptedError('Пакет остановлен.')
            try:
                geometry = clean_text_region(frame, bubble['rect'])
            except BubbleRegionError as exc:
                prepared.append((bubble, text, exc))
                continue
            _, (ox, oy), (tx, ty, w, h), _ = geometry
            x, y = ox + tx, oy + ty
            merged = False
            for i, (previous, old_text, old_geometry) in enumerate(prepared):
                if isinstance(old_geometry, BubbleRegionError):
                    continue
                _, (px, py), (rx, ry, rw, rh), _ = old_geometry
                rx, ry = px + rx, py + ry
                overlap = max(0, min(x+w, rx+rw)-max(x, rx)) * max(0, min(y+h, ry+rh)-max(y, ry))
                if overlap < .6 * min(w*h, rw*rh):
                    continue
                ax, ay, aw, ah = previous['rect']
                bx, by, bw, bh = bubble['rect']
                union = (min(ax, bx), min(ay, by), max(ax+aw, bx+bw)-min(ax, bx), max(ay+ah, by+bh)-min(ay, by))
                try:
                    union_geometry = clean_text_region(frame, union)
                except BubbleRegionError:
                    continue
                combined = old_text if text in old_text else text if old_text in text else old_text + ' ' + text
                prepared[i] = ({'rect': union}, combined, union_geometry)
                log.info('Объединены OCR-поля одного бабла: %s', union)
                merged = True
                break
            if not merged:
                prepared.append((bubble, text, geometry))
        rendered_regions = []
        result = RenderResult()
        for start in range(0, len(prepared), 4):
            if self.authorize:
                self.authorize()
            if cancelled():
                raise InterruptedError('Пакет остановлен.')
            group = prepared[start:start + 4]
            translations = self.translator.translate_bubbles_batch([text for _, text, _ in group])
            if len(translations) != len(group):
                raise RuntimeError('Число переводов не совпадает с числом реплик.')
            for (bubble, source_text, geometry), translated in zip(group, translations):
                if cancelled():
                    raise InterruptedError('Пакет остановлен.')
                if not translated.strip() or translated == source_text:
                    raise RuntimeError('Переводчик не вернул перевод; проверьте Ollama.')
                try:
                    if isinstance(geometry, BubbleRegionError):
                        raise geometry
                    cleaned, (ox, oy), inner_rect, safe = geometry
                    rectangles = [inner_rect] + [r for r in inner_rect_candidates(safe) if r != inner_rect]
                    translated, (font, block, spacing, bounds), (tx, ty, w, h) = self._fit_translation_in_regions(
                        source_text, translated, rectangles, cancelled)
                except (BubbleRegionError, TextLayoutError) as exc:
                    warning = (f"Бабл {bubble['rect']}: {exc} Оставлен оригинал. "
                               f'Распознано: {source_text} Перевод: {translated}')
                    result.warnings.append(warning)
                    log.warning('%s: бабл %s: %s Оставлен оригинал.', source, bubble['rect'], exc)
                    continue
                x, y = ox + tx, oy + ty
                if any(x < rx + rw and x + w > rx and y < ry + rh and y + h > ry
                       for rx, ry, rw, rh in rendered_regions):
                    warning = f"Бабл {bubble['rect']}: пересечение с другим переводом; оставлен оригинал. Перевод: {translated}"
                    result.warnings.append(warning)
                    log.warning('%s', warning)
                    continue
                # Expanded ROIs must not restore source text of a nearby bubble.
                source_roi = frame[oy:oy+cleaned.shape[0], ox:ox+cleaned.shape[1]]
                changed = np.any(cleaned != source_roi, axis=2).astype(np.uint8) * 255
                image.paste(Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB)), (ox, oy), Image.fromarray(changed))
                tile = Image.new('RGBA', (w, h), (0, 0, 0, 0))
                ink = ImageDraw.Draw(tile)
                text_w, text_h = bounds[2] - bounds[0], bounds[3] - bounds[1]
                ink.multiline_text(((w-text_w)/2-bounds[0], (h-text_h)/2-bounds[1]),
                                   block, font=font, fill='black', spacing=spacing, align='center')
                image.paste(tile, (x, y), tile)
                rendered_regions.append((x, y, w, h))
                result.rendered += 1
        if cancelled():
            raise InterruptedError('Пакет остановлен.')
        image.save(destination, format='PNG')
        log.info('Страница %s: сохранена за %.2fs; переведено=%d, предупреждений=%d',
                 source, time.perf_counter() - started, result.rendered, len(result.warnings))
        return result
