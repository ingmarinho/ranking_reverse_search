"""Centralized tunable constants for rrs.

These are values that are *reasonable to tweak* — quality knobs, timeouts,
size caps, UI cadences — pulled out of the code so there's one place to adjust
them. This is deliberately the lowest layer: it imports nothing from the rest
of the package, so any module may import it without risking a cycle.

Out of scope (left inline where they're used): pure-math expressions, protocol
or container contracts that would break compatibility if changed (codec sets,
``mp4`` muxing, ``yuv420p``, ``+faststart``), and HTTP-standard values.

A handful of these double as the *defaults* for env-overridable settings
(see ``config.py``); the env var still wins at runtime.
"""

from __future__ import annotations

# ---- Download / re-encoding ----

# Resolution cap (max height in px) for the source ranking-video download.
DOWNLOAD_MAX_HEIGHT = 1080

# libx264 knobs used only when a download must be re-encoded to H.264/AAC.
# Preset trades encode speed for size; CRF trades quality for size (lower =
# better/larger). Passed to ffmpeg as strings.
REENCODE_X264_PRESET = "veryfast"
REENCODE_X264_CRF = "20"
# AAC bitrate when transcoding an incompatible audio stream.
REENCODE_AUDIO_BITRATE = "192k"

# ---- Scene detection ----

# Default PySceneDetect ContentDetector threshold (env: SCENE_THRESHOLD).
SCENE_THRESHOLD_DEFAULT = 27.0

# ---- Clip / server defaults (env-overridable in config.py) ----

# Max initial clip length in seconds before download is refused; rrs targets
# shorts, not full videos (env: MAX_CLIP_DURATION_SEC, <=0 disables the cap).
MAX_CLIP_DURATION_SEC_DEFAULT = 180.0

# HTTP port for the local NiceGUI server (env: PORT).
PORT_DEFAULT = 8080

# ---- Frame extraction ----

# cv2 JPEG encode quality (0-100) for extracted/cropped frames.
JPEG_QUALITY = 88

# lru_cache size for memoized video-dimension probes (one entry per source).
VIDEO_DIMENSIONS_CACHE_SIZE = 32

# Fallback (width, height) aspect when a video's real dimensions can't be probed.
DEFAULT_ASPECT_RATIO = (16, 9)

# ---- imgbb hosting ----

# Request timeouts (seconds) for uploading frames vs. validating a key.
IMGBB_UPLOAD_TIMEOUT_SEC = 30.0
IMGBB_VALIDATE_TIMEOUT_SEC = 15.0

# Hosted frames are only needed for the duration of a search session; expire
# them after a week so they don't linger on imgbb indefinitely.
IMGBB_FRAME_EXPIRATION_SEC = 7 * 24 * 60 * 60

# The key-validation probe upload self-expires almost immediately (guaranteed
# cleanup even if the best-effort delete fails).
IMGBB_PROBE_EXPIRATION_SEC = 60

# How many chars of an imgbb error body to surface in an error message.
IMGBB_ERROR_SNIPPET_LEN = 200

# ---- Filesystem ----

# Max length of a title-derived download folder name before truncation.
MAX_DOWNLOAD_DIRNAME_LEN = 120

# ---- UI ----

# How often the wizard poller ticks to advance pipeline progress (seconds).
PROGRESS_POLL_INTERVAL_SEC = 1.0

# Throttle (seconds) on the frame-picker slider's live scrub updates.
SCRUB_THROTTLE_SEC = 0.15

# A drag smaller than this fraction of the frame (in either dimension) is
# treated as a stray click, not a crop — so a click never wipes an existing crop.
MIN_CROP_FRACTION = 0.01
