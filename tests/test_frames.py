from __future__ import annotations

from pathlib import Path

from rrs.pipeline.frames import extract_evenly_spaced, extract_frame


def test_extract_frame_writes_jpeg(synthetic_video: Path, tmp_path: Path):
    out = tmp_path / "f.jpg"
    extract_frame(video_path=synthetic_video, frame_number=12, out_path=out)
    assert out.exists()
    assert out.stat().st_size > 0
    assert out.read_bytes()[:2] == b"\xff\xd8"


def test_extract_evenly_spaced_returns_n_frames(synthetic_video: Path, tmp_path: Path):
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    results = extract_evenly_spaced(
        video_path=synthetic_video,
        start_frame=0,
        end_frame=48,
        count=9,
        out_dir=out_dir,
    )
    assert len(results) == 9
    for frame_number, path in results:
        assert 0 <= frame_number < 48
        assert path.exists()
