"""Measure and draw using Pillow pixels only, independent of Qt screen DPI."""
from PIL import ImageFont
import re
from core.fonts import load_font


class TextLayoutError(ValueError):
    """Expected text overflow at the minimum readable font size."""


def fit_text(text, font_path, width, height, min_size=11, max_size=18):
    from PIL import Image, ImageDraw
    draw = ImageDraw.Draw(Image.new('L', (1, 1)))
    available_w, available_h = max(1, width - 4), max(1, height - 4)
    # Punctuation belongs to the preceding word and must not get its own line.
    words = re.sub(r'\s+([,.!?…:;])', r'\1', text).split()
    for size in range(max_size, min_size - 1, -1):
        font = load_font(font_path, size)
        spacing = max(2, size // 5)
        lines, current = [], ''
        too_wide = False
        for word in words:
            word_bounds = draw.textbbox((0, 0), word, font=font)
            if word_bounds[2] - word_bounds[0] > available_w:
                too_wide = True
                break
            candidate = (current + ' ' + word).strip()
            candidate_bounds = draw.textbbox((0, 0), candidate, font=font)
            if candidate_bounds[2] - candidate_bounds[0] <= available_w:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ''
            current = word
        if too_wide:
            continue
        if current:
            lines.append(current)
        block = '\n'.join(lines)
        bounds = draw.multiline_textbbox((0, 0), block, font=font, spacing=spacing, align='center')
        if bounds[2] - bounds[0] <= available_w and bounds[3] - bounds[1] <= available_h:
            return font, block, spacing, bounds
    raise TextLayoutError(f'Перевод не помещается в {width}×{height}px при читаемом шрифте {min_size}px. Нужна более короткая реплика.')
