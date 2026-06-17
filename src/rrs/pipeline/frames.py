from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

import cv2

from rrs.constants import DEFAULT_ASPECT_RATIO, JPEG_QUALITY, VIDEO_DIMENSIONS_CACHE_SIZE


class FrameExtractError(RuntimeError):
    pass


def _atomic_imwrite(out_path: Path, img) -> None:
    """Write `img` to `out_path` as JPEG without ever exposing a partial file.

    cv2.imwrite truncates then rewrites in place. These files are served over
    /_data, so a file overwritten while an HTTP response is streaming it shrinks
    mid-flight — which uvicorn reports as "Response content shorter than
    Content-Length" (B3). Instead we write to a unique temp file in the same
    directory and os.replace it into place: the rename is atomic, in-flight
    readers keep the intact old file until the swap, and concurrent writers (the
    overlapping scrub extractions that all target one path) never clobber each
    other's temp."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Encode by format, not by filename — the temp file's extension is ".tmp", so
    # cv2.imwrite couldn't infer the JPEG codec from it.
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise FrameExtractError(f"failed to encode {out_path}")
    fd, tmp = tempfile.mkstemp(dir=out_path.parent, prefix=f"{out_path.stem}-", suffix=".tmp")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as f:
            # buf is a uint8 ndarray; write it via the buffer protocol directly
            # rather than copying the whole encoded image out with .tobytes().
            f.write(buf)
        os.replace(tmp_path, out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


@lru_cache(maxsize=VIDEO_DIMENSIONS_CACHE_SIZE)
def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of the video. Falls back to DEFAULT_ASPECT_RATIO if probe fails.

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
        return DEFAULT_ASPECT_RATIO
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
    _atomic_imwrite(out_path, frame)
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
    _atomic_imwrite(out_path, img[y0:y1, x0:x1])
    return out_path
