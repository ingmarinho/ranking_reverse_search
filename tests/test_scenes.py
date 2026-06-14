from __future__ import annotations

from pathlib import Path

from rrs.pipeline.scenes import SceneRow, detect_scenes


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
