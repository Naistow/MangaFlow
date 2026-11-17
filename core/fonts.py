from functools import lru_cache
from PIL import ImageFont


@lru_cache(maxsize=128)
def load_font(path, size):
    """Reuse font handles for both Pillow layout paths, preserving pixel metrics."""
    return ImageFont.truetype(path, size)
