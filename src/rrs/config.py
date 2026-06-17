from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from rrs.constants import (
    MAX_CLIP_DURATION_SEC_DEFAULT,
    PORT_DEFAULT,
    SCENE_THRESHOLD_DEFAULT,
)

logger = logging.getLogger(__name__)


class MissingDependencyError(RuntimeError):
    """Raised when a required external binary is missing at startup."""


# Subdir of the PyInstaller bundle where ffmpeg/ffprobe/deno are shipped. This is
# a producer/consumer contract: scripts/pack.py writes the binaries here and
# _activate_bundled_binaries() reads them — keep it as one source of truth.
BUNDLED_BIN_SUBDIR = "bin"


def _activate_bundled_binaries() -> None:
    """Prepend the PyInstaller-bundled binary dir to PATH, if present.

    When frozen, PyInstaller sets `sys._MEIPASS` to the dir holding bundled
    resources. scripts/pack.py drops ffmpeg/ffprobe/deno under BUNDLED_BIN_SUBDIR
    there; putting it on PATH lets `shutil.which` (and yt-dlp's deno lookup) find
    the bundled copies. No-op in a normal source run, so testers without a global
    ffmpeg install still work. Safe to call more than once."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        return
    bin_dir = Path(base) / BUNDLED_BIN_SUBDIR
    if bin_dir.is_dir():
        os.environ["PATH"] = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int
    scene_threshold: float
    max_clip_duration_sec: float | None
    imgbb_api_key: str | None
    has_deno: bool


def load_config(probe_ffmpeg: bool = True) -> Config:
    _activate_bundled_binaries()

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

    # Cap on the initial clip length: rrs is built for shorts, not full-length
    # videos to split. A value <= 0 disables the limit.
    max_clip_duration_sec = float(
        os.environ.get("MAX_CLIP_DURATION_SEC", str(MAX_CLIP_DURATION_SEC_DEFAULT))
    )
    if max_clip_duration_sec <= 0:
        max_clip_duration_sec = None

    return Config(
        data_dir=data_dir,
        port=int(os.environ.get("PORT", str(PORT_DEFAULT))),
        scene_threshold=float(os.environ.get("SCENE_THRESHOLD", str(SCENE_THRESHOLD_DEFAULT))),
        max_clip_duration_sec=max_clip_duration_sec,
        imgbb_api_key=os.environ.get("IMGBB_API_KEY") or None,
        has_deno=has_deno,
    )
