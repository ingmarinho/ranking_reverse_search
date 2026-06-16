from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rrs.pipeline.download import download_video
from rrs.pipeline.frames import extract_frame
from rrs.pipeline.scenes import detect_scenes
from rrs.store.db import Database, Job, JobStatus

StatusHook = Callable[[JobStatus], None]
ProgressHook = Callable[[float], None]


@dataclass(frozen=True)
class JobPaths:
    root: Path
    source: Path
    frames_dir: Path
    sources_dir: Path


def job_paths(data_dir: Path, job_id: int) -> JobPaths:
    root = Path(data_dir) / "jobs" / str(job_id)
    return JobPaths(
        root=root,
        source=root / "source.mp4",
        frames_dir=root / "frames",
        sources_dir=root / "sources",
    )


def safe_dirname(title: str | None, job_id: int) -> str:
    """Filesystem-safe folder name from a video title; falls back to job-<id>."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(". ")
    return cleaned[:120] if cleaned else f"job-{job_id}"


def resolve_download_dir(db: Database, data_dir: Path, job: Job) -> Path:
    """Return the job's download folder, assigning + persisting it on first call.

    Prefers the clean title-based name; appends ' (2)', ' (3)', … only when that
    name is already taken by another job — taken meaning it exists on disk (e.g. a
    leftover from a deleted job) or another job's row claims it. The choice is
    stored on the job so OPEN FOLDER and the download writers always agree."""
    if job.download_dir:
        return Path(job.download_dir)

    root = Path(data_dir) / "downloads"
    base = safe_dirname(job.title, job.id)
    claimed = db.claimed_download_dirs(exclude_job_id=job.id)

    candidate = root / base
    n = 2
    while str(candidate) in claimed or candidate.exists():
        candidate = root / f"{base} ({n})"
        n += 1

    db.set_download_dir(job.id, str(candidate))
    return candidate


def next_extra_path(folder: Path) -> Path:
    """Return the next free `extra-NN.mp4` in `folder` (numbering past the highest
    existing index, so gaps are never reused)."""
    highest = 0
    if folder.exists():
        for p in folder.glob("extra-*.mp4"):
            m = re.fullmatch(r"extra-(\d+)", p.stem)
            if m:
                highest = max(highest, int(m.group(1)))
    return folder / f"extra-{highest + 1:02d}.mp4"


def _set_status(db: Database, job_id: int, status: JobStatus, hook: StatusHook | None):
    db.update_job_status(job_id, status)
    if hook:
        hook(status)


async def run_pre_interactive_pipeline(
    db: Database,
    job_id: int,
    data_dir: Path,
    scene_threshold: float,
    on_status: StatusHook | None = None,
    on_download_progress: ProgressHook | None = None,
) -> None:
    """Run download → scene detect → first-frame extraction, then mark interactive.

    On any failure, mark the job failed (db.fail_job) and re-raise."""
    job = db.get_job(job_id)
    assert job is not None
    paths = job_paths(data_dir, job_id)
    paths.root.mkdir(parents=True, exist_ok=True)

    try:
        _set_status(db, job_id, JobStatus.DOWNLOADING, on_status)
        result = await asyncio.to_thread(
            download_video, job.url, paths.source, 1080, on_download_progress
        )
        db.set_job_source(
            job_id,
            title=result.title,
            duration_sec=result.duration_sec,
            source_path=str(result.path),
        )

        _set_status(db, job_id, JobStatus.DETECTING_SCENES, on_status)
        scenes = await asyncio.to_thread(detect_scenes, paths.source, scene_threshold)
        db.insert_scenes(
            job_id,
            [(s.idx, s.start_frame, s.end_frame, s.start_sec, s.end_sec) for s in scenes],
        )
        scene_rows = db.list_scenes(job_id)

        _set_status(db, job_id, JobStatus.EXTRACTING_FRAMES, on_status)
        out_paths = [paths.frames_dir / str(s.idx) / "0.jpg" for s in scenes]
        await asyncio.gather(
            *(
                asyncio.to_thread(extract_frame, paths.source, s.start_frame, out)
                for s, out in zip(scenes, out_paths, strict=True)
            )
        )
        for s, row, out in zip(scenes, scene_rows, out_paths, strict=True):
            db.insert_frame(
                scene_id=row.id,
                ordinal=0,
                frame_number=s.start_frame,
                path=str(out),
                is_selected=True,
            )

        _set_status(db, job_id, JobStatus.INTERACTIVE, on_status)
    except Exception as exc:
        db.fail_job(job_id, str(exc))
        raise
