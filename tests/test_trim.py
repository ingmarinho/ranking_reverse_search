from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rrs.pipeline.trim import TrimError, trim_clip


def _duration_seconds(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


def test_trim_clip_writes_subclip(synthetic_video: Path, tmp_path: Path):
    out = tmp_path / "clip.mp4"
    trim_clip(source=synthetic_video, start_sec=1.0, end_sec=3.5, out_path=out)
    assert out.exists()
    dur = _duration_seconds(out)
    assert 0.5 < dur <= 4.0


def test_trim_clip_rejects_inverted_range(synthetic_video: Path, tmp_path: Path):
    with pytest.raises(TrimError):
        trim_clip(source=synthetic_video, start_sec=3.0, end_sec=1.0, out_path=tmp_path / "x.mp4")


def test_trim_clip_rejects_missing_source(tmp_path: Path):
    with pytest.raises(TrimError):
        trim_clip(source=tmp_path / "nope.mp4", start_sec=0, end_sec=1, out_path=tmp_path / "x.mp4")
