from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class MissingDependencyError(RuntimeError):
    """Raised when a required external binary is missing at startup."""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int
    scene_threshold: float
    imgbb_api_key: str | None
    has_deno: bool


def load_config(probe_ffmpeg: bool = True) -> Config:
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    if probe_ffmpeg:
        for binary in ("ffmpeg", "ffprobe"):
            if shutil.which(binary) is None:
                raise MissingDependencyError(
                    f"{binary} not found on PATH. Install ffmpeg (e.g. `brew install ffmpeg`)."
                )

    # yt-dlp uses an external JS runtime (Deno) to solve YouTube's signature/nsig
    # challenges. Without one, format availability degrades. Soft check only.
    has_deno = shutil.which("deno") is not None
    if not has_deno:
        logger.warning(
            "deno not found on PATH — YouTube downloads may be limited. "
            "Install Deno (https://deno.com/) for full support."
        )

    return Config(
        data_dir=data_dir,
        port=int(os.environ.get("PORT", "8080")),
        scene_threshold=float(os.environ.get("SCENE_THRESHOLD", "27.0")),
        imgbb_api_key=os.environ.get("IMGBB_API_KEY") or None,
        has_deno=has_deno,
    )
