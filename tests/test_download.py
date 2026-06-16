from __future__ import annotations

from pathlib import Path

import pytest

from rrs.pipeline.download import DownloadResult, download_video


@pytest.fixture
def fake_ydl(monkeypatch):
    """Replace yt_dlp.YoutubeDL with a context-manager mock and capture init opts."""
    calls = {}

    class FakeYDL:
        def __init__(self, opts):
            calls["opts"] = opts
            self._info = {
                "title": "My Vid",
                "duration": 12.5,
                "_filename": opts["outtmpl"].format(id="abc"),
            }

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            calls["url"] = url
            calls["download"] = download
            Path(self._info["_filename"]).parent.mkdir(parents=True, exist_ok=True)
            Path(self._info["_filename"]).write_bytes(b"\x00")
            return self._info

    monkeypatch.setattr("rrs.pipeline.download.YoutubeDL", FakeYDL)
    return calls


def test_download_video_with_1080p_cap(fake_ydl, tmp_path):
    out = tmp_path / "source.mp4"
    result = download_video(
        url="https://youtu.be/xyz",
        out_path=out,
        max_height=1080,
    )
    assert isinstance(result, DownloadResult)
    assert result.title == "My Vid"
    assert result.duration_sec == 12.5
    assert result.path == out
    assert "height<=1080" in fake_ydl["opts"]["format"]
    assert fake_ydl["opts"]["merge_output_format"] == "mp4"
    assert fake_ydl["opts"]["outtmpl"].startswith(str(tmp_path))


def test_download_video_best_when_max_height_none(fake_ydl, tmp_path):
    out = tmp_path / "source.mp4"
    download_video(url="x", out_path=out, max_height=None)
    assert fake_ydl["opts"]["format"] == "bv*+ba/b"


def test_download_enables_ejs_remote_components(fake_ydl, tmp_path):
    # Regression for B2: yt-dlp gates the YouTube JS challenge solver script
    # behind remote_components; without ejs:github the solver is skipped and
    # downloads 403 even with deno installed.
    out = tmp_path / "source.mp4"
    download_video(url="x", out_path=out, max_height=None)
    assert "ejs:github" in fake_ydl["opts"]["remote_components"]


def test_download_video_progress_hook_invoked(fake_ydl, tmp_path):
    received = []

    def on_progress(p):
        received.append(p)

    out = tmp_path / "source.mp4"
    download_video(url="x", out_path=out, max_height=1080, progress_hook=on_progress)

    hooks = fake_ydl["opts"]["progress_hooks"]
    assert len(hooks) == 1
    hooks[0]({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
    assert received and 0.0 <= received[-1] <= 1.0
    assert received[-1] == pytest.approx(0.5)
