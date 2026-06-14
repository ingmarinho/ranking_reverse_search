from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class MissingDependencyError(RuntimeError):
    """Raised when a required external binary is missing at startup."""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int
    scene_threshold: float
    imgbb_api_key: str | None


def load_config(probe_ffmpeg: bool = True) -> Config:
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    if probe_ffmpeg and shutil.which("ffmpeg") is None:
        raise MissingDependencyError(
            "ffmpeg not found on PATH. Install it (e.g. `brew install ffmpeg`)."
        )

    return Config(
        data_dir=data_dir,
        port=int(os.environ.get("PORT", "8080")),
        scene_threshold=float(os.environ.get("SCENE_THRESHOLD", "27.0")),
        imgbb_api_key=os.environ.get("IMGBB_API_KEY") or None,
    )
