from __future__ import annotations

import subprocess
from pathlib import Path


class TrimError(RuntimeError):
    pass


def trim_clip(source: Path, start_sec: float, end_sec: float, out_path: Path) -> Path:
    source = Path(source)
    if not source.exists():
        raise TrimError(f"source does not exist: {source}")
    if end_sec <= start_sec:
        raise TrimError(f"end_sec ({end_sec}) must be > start_sec ({start_sec})")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        f"{start_sec:.3f}",
        "-to",
        f"{end_sec:.3f}",
        "-i",
        str(source),
        "-c",
        "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise TrimError(f"ffmpeg failed: {result.stderr[:500]}")
    return out_path
