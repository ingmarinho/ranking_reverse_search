from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2


class FrameExtractError(RuntimeError):
    pass


@lru_cache(maxsize=32)
def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of the video. Falls back to (16, 9) if probe fails.

    Memoized by path: each source video is probed at most once per process.
    Cache is fine because source files under data/jobs/<id>/ are written once
    and never overwritten in place."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    if w <= 0 or h <= 0:
        return (16, 9)
    return (w, h)


def extract_frame(video_path: Path, frame_number: int, out_path: Path) -> Path:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise FrameExtractError(f"could not open {video_path}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_number))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise FrameExtractError(f"could not read frame {frame_number} from {video_path}")
    finally:
        cap.release()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise FrameExtractError(f"failed to write {out_path}")
    return out_path


def crop_image(
    src_path: Path, rect_norm: tuple[float, float, float, float], out_path: Path
) -> Path:
    """Write a cropped copy of `src_path` to `out_path`.

    `rect_norm` is (x, y, w, h) as fractions (0..1) of the source image. Pixel
    bounds are clamped so the crop is always a non-empty region."""
    img = cv2.imread(str(src_path))
    if img is None:
        raise FrameExtractError(f"could not read {src_path}")
    h, w = img.shape[:2]
    x, y, cw, ch = rect_norm
    x0 = max(0, min(w - 1, round(x * w)))
    y0 = max(0, min(h - 1, round(y * h)))
    x1 = max(x0 + 1, min(w, round((x + cw) * w)))
    y1 = max(y0 + 1, min(h, round((y + ch) * h)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out_path), img[y0:y1, x0:x1], [cv2.IMWRITE_JPEG_QUALITY, 88]):
        raise FrameExtractError(f"failed to write {out_path}")
    return out_path
