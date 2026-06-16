from __future__ import annotations

from pathlib import Path

import pytest

from rrs.pipeline.frames import FrameExtractError, extract_frame
from rrs.pipeline.scenes import SceneRow, detect_scenes, last_selectable_frame


def test_detect_scenes_finds_three_in_synthetic(synthetic_video: Path):
    scenes = detect_scenes(synthetic_video, threshold=27.0)
    assert len(scenes) == 3
    assert isinstance(scenes[0], SceneRow)
    assert scenes[0].idx == 0
    assert scenes[0].start_sec == 0.0
    assert scenes[-1].end_sec > 5.0


def test_detect_scenes_falls_back_to_single_scene_for_static(tmp_path):
    import subprocess

    out = tmp_path / "static.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-t",
            "1",
            "-i",
            "color=c=black:s=160x90:r=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
    )
    scenes = detect_scenes(out, threshold=27.0)
    assert len(scenes) >= 1
    assert scenes[0].start_sec == 0.0


def test_last_selectable_frame_excludes_exclusive_end():
    # PySceneDetect scene boundaries are half-open: end_frame is the first frame
    # of the next scene, so the last real frame of the scene is end_frame - 1.
    assert last_selectable_frame(521, 657) == 656
    # Degenerate ranges never drop below the start frame.
    assert last_selectable_frame(10, 10) == 10
    assert last_selectable_frame(0, 0) == 0


def test_final_scene_end_frame_is_past_eof(synthetic_video: Path, tmp_path: Path):
    # Regression for B1: the final scene's end_frame equals the video's frame
    # count (one past the last decodable frame). Requesting it errors; the last
    # *selectable* frame must stay in range so the picker can read it.
    scenes = detect_scenes(synthetic_video, threshold=27.0)
    last = scenes[-1]
    out = tmp_path / "f.jpg"

    with pytest.raises(FrameExtractError):
        extract_frame(synthetic_video, last.end_frame, out)

    extract_frame(synthetic_video, last_selectable_frame(last.start_frame, last.end_frame), out)
    assert out.exists()
