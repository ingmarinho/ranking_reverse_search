from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scenedetect import ContentDetector, SceneManager, open_video

from rrs.constants import SCENE_THRESHOLD_DEFAULT


@dataclass(frozen=True)
class SceneRow:
    idx: int
    start_frame: int
    end_frame: int
    start_sec: float
    end_sec: float


def last_selectable_frame(start_frame: int, end_frame: int) -> int:
    """The last frame index that actually belongs to a scene.

    PySceneDetect scene boundaries are half-open: ``end_frame`` is the *first*
    frame of the next scene, and for the final scene it equals the video's frame
    count — i.e. one past the last decodable frame. The highest index the frame
    picker may request (and the slider's max) is therefore ``end_frame - 1``,
    never ``end_frame`` itself. Clamped so a degenerate scene never drops below
    its start frame."""
    return max(start_frame, end_frame - 1)


def detect_scenes(video_path: Path, threshold: float = SCENE_THRESHOLD_DEFAULT) -> list[SceneRow]:
    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold))
    sm.detect_scenes(video=video, show_progress=False)
    scenes = sm.get_scene_list()

    if not scenes:
        duration_seconds = video.duration.seconds
        end_frame = int(video.duration.frame_num)
        return [
            SceneRow(
                idx=0,
                start_frame=0,
                end_frame=end_frame,
                start_sec=0.0,
                end_sec=duration_seconds,
            )
        ]

    rows: list[SceneRow] = []
    for i, (start, end) in enumerate(scenes):
        rows.append(
            SceneRow(
                idx=i,
                start_frame=int(start.frame_num),
                end_frame=int(end.frame_num),
                start_sec=float(start.seconds),
                end_sec=float(end.seconds),
            )
        )
    return rows
