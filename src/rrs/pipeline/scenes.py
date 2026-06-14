from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scenedetect import ContentDetector, SceneManager, open_video


@dataclass(frozen=True)
class SceneRow:
    idx: int
    start_frame: int
    end_frame: int
    start_sec: float
    end_sec: float


def detect_scenes(video_path: Path, threshold: float = 27.0) -> list[SceneRow]:
    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold))
    sm.detect_scenes(video=video, show_progress=False)
    scenes = sm.get_scene_list()

    if not scenes:
        duration_seconds = video.duration.seconds
        end_frame = int(video.duration.frame_num)
        return [SceneRow(
            idx=0, start_frame=0, end_frame=end_frame,
            start_sec=0.0, end_sec=duration_seconds,
        )]

    rows: list[SceneRow] = []
    for i, (start, end) in enumerate(scenes):
        rows.append(SceneRow(
            idx=i,
            start_frame=int(start.frame_num),
            end_frame=int(end.frame_num),
            start_sec=float(start.seconds),
            end_sec=float(end.seconds),
        ))
    return rows
