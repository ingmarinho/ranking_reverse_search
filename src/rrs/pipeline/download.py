from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    title: str
    duration_sec: float


ProgressHook = Callable[[float], None]


def _format_string(max_height: int | None) -> str:
    if max_height is None:
        return "bv*+ba/b"
    return f"bv*[height<={max_height}]+ba/b[height<={max_height}]"


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
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise DownloadError(f"yt-dlp failed: {exc}") from exc

    if not out_path.exists():
        raise DownloadError(f"yt-dlp finished but {out_path} is missing")

    return DownloadResult(
        path=out_path,
        title=str(info.get("title") or "Untitled"),
        duration_sec=float(info.get("duration") or 0.0),
    )
