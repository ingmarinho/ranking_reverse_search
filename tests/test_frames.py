from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

import rrs.pipeline.frames as frames_mod
from rrs.pipeline.frames import crop_image, extract_frame


def test_extract_frame_writes_jpeg(synthetic_video: Path, tmp_path: Path):
    out = tmp_path / "f.jpg"
    extract_frame(video_path=synthetic_video, frame_number=12, out_path=out)
    assert out.exists()
    assert out.stat().st_size > 0
    assert out.read_bytes()[:2] == b"\xff\xd8"


def test_extract_frame_never_truncates_destination(
    synthetic_video: Path, tmp_path: Path, monkeypatch
):
    # Regression for B3: /_data serves these JPEGs, and a concurrent HTTP response
    # must never observe a partially-written file (which uvicorn reports as
    # "Response content shorter than Content-Length"). The destination must hold
    # the complete previous bytes right up until an atomic swap, never a truncated
    # in-place rewrite.
    out = tmp_path / "f.jpg"
    out.write_bytes(b"OLD-COMPLETE-CONTENT")

    real_replace = os.replace
    seen: dict = {}

    def spy_replace(src, dst):
        # Whatever a reader opens at `dst` before the swap is the intact old file.
        seen["dst_before"] = Path(dst).read_bytes()
        real_replace(src, dst)

    monkeypatch.setattr(frames_mod.os, "replace", spy_replace)
    extract_frame(synthetic_video, 12, out)

    assert seen["dst_before"] == b"OLD-COMPLETE-CONTENT"
    assert out.read_bytes()[:2] == b"\xff\xd8"
    # No temp artifact left behind next to the destination.
    assert list(tmp_path.glob("*.tmp")) == []


def test_crop_image_crops_to_normalized_bounds(tmp_path: Path):
    src = tmp_path / "src.png"  # lossless so pixel bounds are exact
    cv2.imwrite(str(src), np.zeros((100, 200, 3), dtype=np.uint8))  # h=100, w=200
    out = tmp_path / "crop.jpg"

    crop_image(src, (0.25, 0.5, 0.5, 0.5), out)

    cropped = cv2.imread(str(out))
    # x: 0.25*200..0.75*200 = 50..150 -> width 100; y: 0.5*100..1.0*100 -> height 50
    assert cropped.shape[1] == 100
    assert cropped.shape[0] == 50


def test_crop_image_clamps_degenerate_rect(tmp_path: Path):
    src = tmp_path / "src.png"
    cv2.imwrite(str(src), np.zeros((40, 40, 3), dtype=np.uint8))
    out = tmp_path / "crop.jpg"

    # Zero-size rect must still yield a non-empty (>=1px) crop, not crash.
    crop_image(src, (0.5, 0.5, 0.0, 0.0), out)
    cropped = cv2.imread(str(out))
    assert cropped is not None
    assert cropped.shape[0] >= 1 and cropped.shape[1] >= 1
