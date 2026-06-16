"""Shared pytest fixtures. The synthetic_video fixture builds a small
multi-scene video with ffmpeg so scene detection / frame extraction tests
have a real file to work on without checking in binary fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from rrs.store.db import Database, open_db


@pytest.fixture
def db() -> Database:
    """A fresh in-memory database for a test."""
    return open_db(":memory:")


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory) -> Path:
    """A 6-second 320x180 video with 3 hard cuts (red, green, blue blocks of 2s each).
    PySceneDetect will reliably split this into 3 scenes."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    out = tmp_path_factory.mktemp("fix") / "synthetic.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-t",
        "2",
        "-i",
        "color=c=red:s=320x180:r=24",
        "-f",
        "lavfi",
        "-t",
        "2",
        "-i",
        "color=c=green:s=320x180:r=24",
        "-f",
        "lavfi",
        "-t",
        "2",
        "-i",
        "color=c=blue:s=320x180:r=24",
        "-filter_complex",
        "[0:v][1:v][2:v]concat=n=3:v=1[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    assert out.exists()
    return out


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch) -> Path:
    """Point DATA_DIR at a temp dir for the test."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("DATA_DIR", str(d))
    return d
