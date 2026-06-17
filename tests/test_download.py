from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from rrs.pipeline.download import (
    DownloadError,
    DownloadResult,
    _ensure_playable,
    _format_duration,
    _probe_codecs,
    download_video,
)


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


def test_download_video_prefers_h264_aac(fake_ydl, tmp_path):
    # Regression: yt-dlp's bare "best" picks VP9/AV1 + Opus, which it muxes into
    # .mp4 to produce a file QuickTime plays as audio-only. The selector must
    # prefer H.264 video + AAC audio so native-H.264 sources need no re-encode.
    out = tmp_path / "source.mp4"
    download_video(url="x", out_path=out, max_height=None)
    fmt = fake_ydl["opts"]["format"]
    assert fmt.startswith("bv*[vcodec^=avc]+ba[acodec^=mp4a]")
    assert fmt.endswith("/b")  # still falls back to a best single stream


def test_download_video_height_cap_with_always_available_fallback(fake_ydl, tmp_path):
    out = tmp_path / "source.mp4"
    download_video(url="x", out_path=out, max_height=720)
    fmt = fake_ydl["opts"]["format"]
    # The cap constrains the preference clauses...
    assert "[height<=720]" in fmt
    # ...but the final clause is the unconstrained default so availability never
    # regresses (e.g. Instagram exposing only an out-of-cap format).
    assert fmt.endswith("/bv*+ba/b")  # uncapped, no codec filter


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


def _make_video(path: Path, vcodec: str, acodec: str | None) -> None:
    """Build a 1-second test clip with the given codecs via ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-t",
        "1",
        "-i",
        "color=c=red:s=64x64:r=10",
    ]
    if acodec:
        cmd += ["-f", "lavfi", "-t", "1", "-i", "sine=frequency=440"]
    cmd += ["-c:v", vcodec, "-pix_fmt", "yuv420p"]
    if acodec:
        cmd += ["-c:a", acodec, "-shortest"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True, capture_output=True)


pytestmark_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


@pytestmark_ffmpeg
def test_ensure_playable_reencodes_vp9_to_h264(tmp_path):
    # The Facebook/YouTube bug: VP9 video muxed into .mp4 plays audio-only in
    # QuickTime. _ensure_playable must transcode it to H.264.
    path = tmp_path / "vid.mp4"
    _make_video(path, "libvpx-vp9", "aac")
    assert _probe_codecs(path)[0] == "vp9"
    _ensure_playable(path)
    assert _probe_codecs(path) == ("h264", "aac")


@pytestmark_ffmpeg
def test_ensure_playable_transcodes_opus_audio(tmp_path):
    path = tmp_path / "vid.mp4"
    _make_video(path, "libx264", "libopus")
    assert _probe_codecs(path) == ("h264", "opus")
    _ensure_playable(path)
    assert _probe_codecs(path) == ("h264", "aac")


@pytestmark_ffmpeg
def test_ensure_playable_noop_for_h264_aac(tmp_path):
    # Native-H.264 downloads must not be re-encoded (lossless + fast path).
    path = tmp_path / "vid.mp4"
    _make_video(path, "libx264", "aac")
    before = path.read_bytes()
    _ensure_playable(path)
    assert path.read_bytes() == before  # byte-identical: no transcode happened


@pytestmark_ffmpeg
def test_ensure_playable_handles_video_without_audio(tmp_path):
    path = tmp_path / "vid.mp4"
    _make_video(path, "libvpx-vp9", None)
    _ensure_playable(path)
    assert _probe_codecs(path) == ("h264", None)


def test_probe_codecs_returns_none_for_garbage(tmp_path):
    path = tmp_path / "junk.mp4"
    path.write_bytes(b"\x00\x01\x02not a video")
    assert _probe_codecs(path) == (None, None)


def _fake_ydl_with_duration(monkeypatch, duration: float) -> dict:
    """Patch YoutubeDL with a mock whose metadata reports `duration` seconds.

    Honours the real `match_filter` from opts (the way yt-dlp does): a rejected
    clip yields metadata but no downloaded file, so a single extract_info pass
    covers both the limit check and the download. Records the extraction count."""
    calls = {"extractions": 0}

    class FakeYDL:
        def __init__(self, opts):
            self._filename = opts["outtmpl"].format(id="abc")
            self._match_filter = opts.get("match_filter")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            calls["extractions"] += 1
            info = {"title": "Long Vid", "duration": duration, "_filename": self._filename}
            rejected = (
                download and self._match_filter and self._match_filter(info, incomplete=False)
            )
            if download and not rejected:
                Path(self._filename).parent.mkdir(parents=True, exist_ok=True)
                Path(self._filename).write_bytes(b"\x00")
            return info

    monkeypatch.setattr("rrs.pipeline.download.YoutubeDL", FakeYDL)
    return calls


def test_download_video_rejects_clip_over_duration_limit(monkeypatch, tmp_path):
    calls = _fake_ydl_with_duration(monkeypatch, duration=600.0)
    out = tmp_path / "source.mp4"
    with pytest.raises(DownloadError, match="over the 3 min limit"):
        download_video(url="x", out_path=out, max_height=None, max_duration_sec=180)
    # A single extraction pass rejects the clip before any bytes are written.
    assert calls["extractions"] == 1
    assert not out.exists()


def test_download_video_allows_clip_within_duration_limit(monkeypatch, tmp_path):
    calls = _fake_ydl_with_duration(monkeypatch, duration=120.0)
    out = tmp_path / "source.mp4"
    result = download_video(url="x", out_path=out, max_height=None, max_duration_sec=180)
    assert result.duration_sec == 120.0
    assert calls["extractions"] == 1
    assert out.exists()


def test_format_duration_renders_minutes_and_seconds():
    assert _format_duration(180) == "3 min"
    assert _format_duration(75) == "1 min 15 sec"
    assert _format_duration(42) == "42 sec"
