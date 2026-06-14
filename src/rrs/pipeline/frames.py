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


def extract_evenly_spaced(
    video_path: Path,
    start_frame: int,
    end_frame: int,
    count: int,
    out_dir: Path,
) -> list[tuple[int, Path]]:
    """Extract `count` frames evenly spaced through [start_frame, end_frame).

    Returns list of (frame_number, written_path) in order.
    """
    if count < 1:
        return []
    span = max(1, end_frame - start_frame)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[int, Path]] = []
    for i in range(count):
        fn = start_frame + int((i + 0.5) * span / count)
        path = out_dir / f"cand_{i}.jpg"
        extract_frame(video_path, fn, path)
        results.append((fn, path))
    return results
