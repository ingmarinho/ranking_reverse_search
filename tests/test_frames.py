from __future__ import annotations

from pathlib import Path

from rrs.pipeline.frames import extract_frame


def test_extract_frame_writes_jpeg(synthetic_video: Path, tmp_path: Path):
    out = tmp_path / "f.jpg"
    extract_frame(video_path=synthetic_video, frame_number=12, out_path=out)
    assert out.exists()
    assert out.stat().st_size > 0
    assert out.read_bytes()[:2] == b"\xff\xd8"
