"""Conservative CPU-only text masks; never paint a rectangular background."""
import cv2
import numpy as np


class BubbleRegionError(ValueError):
    """Expected unsupported/unsafe bubble geometry, not a page I/O error."""


def _histogram_rectangles(mask):
    """Enumerate maximal rectangles once, in deterministic scan order."""
    heights = np.zeros(mask.shape[1], dtype=np.int32)
    for y, row in enumerate(mask):
        heights = np.where(row > 0, heights + 1, 0)
        stack = []
        for x in range(len(heights) + 1):
            current = int(heights[x]) if x < len(heights) else 0
            start = x
            while stack and stack[-1][1] > current:
                left, height = stack.pop()
                yield left, y - height + 1, x - left, height
                start = left
            if current and (not stack or stack[-1][1] < current):
                stack.append((start, current))


def largest_inner_rect(mask, min_width=1, min_height=1):
    """Largest axis-aligned rectangle wholly inside the contour."""
    best, best_area = None, 0
    for x, y, width, height in _histogram_rectangles(mask):
        area = width * height
        if area > best_area and width >= min_width and height >= min_height:
            best_area, best = area, (x, y, width, height)
    return best


def inner_rect_candidates(mask):
    """Trade height for width within the same protected bubble contour.

    The largest rectangle by area can be narrow and reject a whole Russian
    word even though a slightly wider, shorter rectangle fits the same bubble.
    """
    columns = np.flatnonzero(np.any(mask, axis=0))
    if not len(columns):
        return []
    rows = np.flatnonzero(np.any(mask, axis=1))
    left, top = int(columns[0]), int(rows[0])
    cropped = mask[top:int(rows[-1])+1, left:int(columns[-1])+1]
    full_width = cropped.shape[1]
    maximal = np.asarray([r for r in _histogram_rectangles(cropped) if r[3] >= 15], dtype=np.int32)
    if not maximal.size:
        return []
    areas = maximal[:, 2].astype(np.int64) * maximal[:, 3]
    rectangles = []
    for width in (1, *range(12, full_width + 1, 4), full_width):
        eligible = np.where(maximal[:, 2] >= width, areas, -1)
        index = int(np.argmax(eligible))
        if eligible[index] >= 0:
            rect = tuple(map(int, maximal[index]))
            rect = (rect[0] + left, rect[1] + top, rect[2], rect[3])
            if rect not in rectangles:
                rectangles.append(rect)
    return rectangles


def clean_text_region(image_bgr, rect):
    """Return (cleaned ROI, ROI origin, safe text rect, safe mask).

    Search around the detector's text box for an enclosed light interior.
    Contour components and strokes touching the search border are protected.
    With open/uncertain contours only the inset text box is considered.
    """
    height, width = image_bgr.shape[:2]
    x, y, w, h = map(int, rect)
    # The detector bounds glyphs, not the cloud. Short columns need enough
    # surrounding space to see the whole outline and recognize shared bubbles.
    margin = max(64, min(224, 2 * max(w, h)))
    left, top = max(0, x - margin), max(0, y - margin)
    right, bottom = min(width, x + w + margin), min(height, y + h + margin)
    roi = image_bgr[top:bottom, left:right].copy()
    if not roi.size:
        raise BubbleRegionError('Пустая область бабла.')
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    ink = (gray < 190).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    protected_labels = np.zeros(count, dtype=np.uint8)
    candidate_labels = np.zeros(count, dtype=np.uint8)
    rh, rw = ink.shape
    bx, by = max(0, x - left), max(0, y - top)
    ex, ey = min(rw, x + w - left), min(rh, y + h - top)
    for label in range(1, count):
        cx, cy, cw, ch, area = stats[label]
        touches_edge = cx == 0 or cy == 0 or cx + cw == rw or cy + ch == rh
        # Large/long components are usually bubble borders or artwork.
        if touches_edge or cw > w * .9 or ch > h * .9 or area > w * h * .25:
            protected_labels[label] = 1
        else:
            candidate_labels[label] = 1

    # Connected white space inside a closed bubble does not reach ROI edges.
    # Bubble outlines can be light gray after screenshot scaling. Their barrier
    # threshold must be independent of the darker text-ink threshold above.
    barriers = cv2.morphologyEx((gray < 220).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, regions, region_stats, _ = cv2.connectedComponentsWithStats(1 - barriers, connectivity=8)
    best, score = None, 0
    for label in range(1, n):
        cx, cy, cw, ch, area = region_stats[label]
        if cx == 0 or cy == 0 or cx + cw == rw or cy + ch == rh:
            continue
        region_contours, _ = cv2.findContours((regions[cy:cy+ch, cx:cx+cw] == label).astype(np.uint8),
                                             cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(region_contours, key=cv2.contourArea)
        outline_area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        # Rectangular narration boxes are legitimate text containers. Only
        # admit them when their size matches this text field, not a whole panel.
        narration_box = (outline_area / (cw * ch) > .85 and cw * ch <= w * h * 3 and
                         cw <= w * 2.2 and ch <= h * 2.2)
        if (outline_area / (cw * ch) > .93 or
                4 * np.pi * outline_area / max(1, perimeter * perimeter) < .35) and not narration_box:
            continue
        overlap = np.count_nonzero(regions[by:ey, bx:ex] == label)
        if overlap > max(score, w * h * .35) and area > max(30, w * h * .15):
            best, score = label, overlap

    interior = np.zeros_like(ink)
    if best is not None:
        contours, _ = cv2.findContours((regions == best).astype(np.uint8), cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(interior, contours, -1, 1, cv2.FILLED)
        interior = cv2.erode(interior, np.ones((11, 11), np.uint8))
    else:
        inset = max(5, min(w, h) // 12)
        interior[by + inset:max(by + inset, ey - inset), bx + inset:max(bx + inset, ex - inset)] = 1
    # Connected vertical glyph columns can be tall/large but are not contours
    # if they are wholly INSIDE a verified interior. For open white fields use
    # the same rule only when the background is predominantly clean white.
    region_gray = gray[by:ey, bx:ex]
    white_field = region_gray.size and np.mean(region_gray > 220) >= .65
    if best is not None or white_field:
        outside = np.bincount(labels[interior == 0], minlength=count)
        internal = outside == 0
        internal[0] = False
        protected_labels[internal] = 0
        candidate_labels[internal] = 1
    protected = protected_labels[labels]
    protected = cv2.dilate(protected, np.ones((11, 11), np.uint8))
    safe = interior & (1 - protected)

    # Only erase complete small components contained within the safe interior.
    unsafe_counts = np.bincount(labels[safe == 0], minlength=count)
    erasable = candidate_labels & (unsafe_counts == 0).astype(np.uint8)
    mask = erasable[labels]
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8)) & safe
    cleaned = roi.copy()
    if np.any(mask):
        restored = cv2.inpaint(roi, mask * 255, 3, cv2.INPAINT_TELEA)
        cleaned[mask != 0] = restored[mask != 0]

    inner_rect = largest_inner_rect(safe)
    if (inner_rect is None or min(inner_rect[2:]) < 8 or
            inner_rect[2] * inner_rect[3] < w * h * .25):
        raise BubbleRegionError('Не найдена безопасная внутренняя область бабла.')
    return cleaned, (left, top), inner_rect, safe
