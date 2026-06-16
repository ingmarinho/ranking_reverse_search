from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    title: str
    duration_sec: float


ProgressHook = Callable[[float], None]

# Codecs that play in an MP4 container on Apple/QuickTime and import cleanly into
# editors. yt-dlp's "best" would otherwise pick VP9/AV1 video + Opus audio (which
# it happily muxes into .mp4), producing a file that decodes audio only — or not
# at all — in QuickTime. ffprobe reports avc1 as "h264".
_COMPATIBLE_VCODECS = {"h264"}
_COMPATIBLE_ACODECS = {"aac"}


def _format_string(max_height: int | None) -> str:
    """yt-dlp format selector that prefers H.264 video + AAC audio.

    Preferring compatible codecs at selection time means sources that offer
    native H.264 (e.g. YouTube) download without a re-encode. Sources that only
    serve VP9/AV1 (e.g. Facebook) fall through to the last clauses and are fixed
    up by `_ensure_playable` afterwards.

    The final clause is the unconstrained `bv*+ba/b` (no codec or height filter)
    so availability never regresses below yt-dlp's default: some sources (e.g.
    Instagram) intermittently expose only a single format that the preference
    filters would otherwise reject, yielding "Requested format is not available".
    """
    h = "" if max_height is None else f"[height<={max_height}]"
    return (
        f"bv*{h}[vcodec^=avc]+ba[acodec^=mp4a]/"  # ideal: H.264 + AAC, no re-encode
        f"bv*{h}[vcodec^=avc]+ba/"  # H.264 video, re-encode audio only
        f"bv*{h}+ba[acodec^=mp4a]/"  # AAC audio, re-encode video only
        f"bv*{h}+ba/"  # any video+audio at the height cap
        f"bv*+ba/b"  # always-available fallback (yt-dlp default)
    )


def _probe_codecs(path: Path) -> tuple[str | None, str | None]:
    """Return (video_codec, audio_codec) for `path`, or None for a missing stream.

    Returns (None, None) if ffprobe can't read the file at all — callers treat an
    unidentifiable file as "leave as-is" rather than crashing the whole download."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        streams = json.loads(out).get("streams", [])
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        logger.warning("ffprobe failed for %s: %s", path, exc)
        return (None, None)

    vcodec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "video"), None)
    acodec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), None)
    return (vcodec, acodec)


def _ensure_playable(path: Path) -> None:
    """Re-encode `path` in place to H.264/AAC MP4 if its codecs aren't compatible.

    No-op when the video is already H.264 and audio is already AAC (or absent),
    so native-H.264 downloads pay nothing. Otherwise the incompatible stream(s)
    are transcoded and the compatible ones are stream-copied."""
    vcodec, acodec = _probe_codecs(path)
    if vcodec is None:
        return  # couldn't identify the file; nothing safe to do

    video_ok = vcodec in _COMPATIBLE_VCODECS
    audio_ok = acodec is None or acodec in _COMPATIBLE_ACODECS
    if video_ok and audio_ok:
        return

    logger.info("Re-encoding %s (vcodec=%s, acodec=%s) to H.264/AAC", path, vcodec, acodec)
    tmp = Path(tempfile.mkstemp(dir=path.parent, prefix=f"{path.stem}-", suffix=".mp4")[1])
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(path)]
    if video_ok:
        cmd += ["-c:v", "copy"]
    else:
        # pix_fmt yuv420p forces 8-bit so a 10-bit VP9/AV1 source doesn't become
        # H.264 High 10, which QuickTime also refuses to play.
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "copy"] if audio_ok else ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart", str(tmp)]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        os.replace(tmp, path)
    except subprocess.CalledProcessError as exc:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"re-encode to H.264/AAC failed: {exc.stderr or exc}") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def download_video(
    url: str,
    out_path: Path,
    max_height: int | None,
    progress_hook: ProgressHook | None = None,
) -> DownloadResult:
    """Download a video via yt-dlp library."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _hook(d):
        if progress_hook is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                progress_hook(min(1.0, done / total))
        elif d.get("status") == "finished":
            progress_hook(1.0)

    opts = {
        "format": _format_string(max_height),
        "merge_output_format": "mp4",
        "outtmpl": str(out_path).replace("%", "%%").replace("%%(", "%("),
        "progress_hooks": [_hook],
        "quiet": True,
        "noprogress": True,
        # Permit yt-dlp to fetch the YouTube JS challenge-solver script. Recent
        # yt-dlp gates this behind remote_components; without it the solver (run
        # via Deno) is skipped, the nsig challenge fails, and downloads 403 even
        # when Deno is installed. "ejs:github" is yt-dlp's recommended source.
        "remote_components": ["ejs:github"],
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise DownloadError(f"yt-dlp failed: {exc}") from exc

    if not out_path.exists():
        raise DownloadError(f"yt-dlp finished but {out_path} is missing")

    # Guarantee a broadly-playable file: VP9/AV1/Opus muxed into .mp4 plays back
    # as audio-only (or not at all) in QuickTime and many editors.
    _ensure_playable(out_path)

    return DownloadResult(
        path=out_path,
        title=str(info.get("title") or "Untitled"),
        duration_sec=float(info.get("duration") or 0.0),
    )
