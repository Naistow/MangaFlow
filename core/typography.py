from dataclasses import dataclass
from typing import List, Tuple
import pyphen
from PIL import ImageDraw, ImageFont
from core.fonts import load_font

@dataclass
class BubbleRect:
    x: int
    y: int
    width: int
    height: int

class AntiOverflowEngine:
    def __init__(self, font_path: str, lang: str = "ru"):
        self.font_path = font_path
        self.dic = pyphen.Pyphen(lang=lang)

    def _split_with_hyphens(self, text: str) -> List[str]:
        return text.replace("\n", " ").split()

    def _wrap_text(self, words: List[str], font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> Tuple[bool, List[str]]:
        lines: List[str] = []
        current_line: List[str] = []

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]

            if line_width <= max_width:
                current_line.append(word)
            else:
                syllables = self.dic.inserted(word).split("-")
                hyphenated = False
                if len(syllables) > 1:
                    for i in range(len(syllables) - 1, 0, -1):
                        part1 = "".join(syllables[:i]) + "-"
                        part2 = "".join(syllables[i:])
                        test_hyphen_line = " ".join(current_line + [part1])
                        h_bbox = draw.textbbox((0, 0), test_hyphen_line, font=font)
                        if (h_bbox[2] - h_bbox[0]) <= max_width:
                            lines.append(test_hyphen_line)
                            current_line = [part2]
                            hyphenated = True
                            break
                
                if not hyphenated:
                    if current_line:
                        lines.append(" ".join(current_line))
                        current_line = [word]
                    else:
                        return False, []

        if current_line:
            lines.append(" ".join(current_line))

        return True, lines

    def calculate_optimal_font_layout(
        self, 
        text: str, 
        bubble: BubbleRect, 
        draw: ImageDraw.ImageDraw,
        padding_pct: float = 0.10,
        min_font_size: int = 8,
        max_font_size: int = 36
    ) -> Tuple[int, List[str], int]:
        safe_width = max(20, int(bubble.width * (1.0 - 2 * padding_pct)))
        safe_height = max(20, int(bubble.height * (1.0 - 2 * padding_pct)))
        words = self._split_with_hyphens(text)

        best_size = min_font_size
        best_lines: List[str] = [text]
        best_line_spacing = 2

        low = min_font_size
        high = max_font_size

        while low <= high:
            mid = (low + high) // 2
            font = load_font(self.font_path, mid)
            line_spacing = int(mid * 0.25)
            
            fits_width, wrapped_lines = self._wrap_text(words, font, safe_width, draw)
            
            if not fits_width:
                high = mid - 1
                continue

            total_height = 0
            for line in wrapped_lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                total_height += (bbox[3] - bbox[1]) + line_spacing
            total_height -= line_spacing

            if total_height <= safe_height:
                best_size = mid
                best_lines = wrapped_lines
                best_line_spacing = line_spacing
                low = mid + 1
            else:
                high = mid - 1

        return best_size, best_lines, best_line_spacing
