from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from rrs.pipeline.download import DownloadError
from rrs.pipeline.jobs import (
    downloads_dir,
    job_paths,
    run_pre_interactive_pipeline,
    safe_dirname,
)
from rrs.store.db import JobStatus, open_db


@pytest.fixture
def db():
    return open_db(":memory:")


@pytest.mark.asyncio
async def test_run_pre_interactive_pipeline_happy_path(db, tmp_path, synthetic_video: Path):
    job_id = db.create_job(url="x")
    statuses: list[JobStatus] = []

    def fake_download(url, out_path, max_height, progress_hook=None):
        import shutil

        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(synthetic_video, out_path)
        from rrs.pipeline.download import DownloadResult

        return DownloadResult(path=out_path, title="t", duration_sec=6.0)

    def on_status(s: JobStatus) -> None:
        statuses.append(s)

    with patch("rrs.pipeline.jobs.download_video", side_effect=fake_download):
        await run_pre_interactive_pipeline(
            db=db,
            job_id=job_id,
            data_dir=tmp_path,
            scene_threshold=27.0,
            on_status=on_status,
        )

    assert statuses == [
        JobStatus.DOWNLOADING,
        JobStatus.DETECTING_SCENES,
        JobStatus.EXTRACTING_FRAMES,
        JobStatus.INTERACTIVE,
    ]
    job = db.get_job(job_id)
    assert job.status == JobStatus.INTERACTIVE
    assert job.title == "t"
    assert job.duration_sec == 6.0
    scenes = db.list_scenes(job_id)
    assert len(scenes) == 3
    for s in scenes:
        frames = db.list_frames(s.id)
        assert len(frames) == 1
        assert frames[0].is_selected is True
        assert Path(frames[0].path).exists()


@pytest.mark.asyncio
async def test_run_pre_interactive_pipeline_download_failure_marks_failed(
    db,
    tmp_path,
):
    job_id = db.create_job(url="x")

    def boom(*a, **k):
        raise DownloadError("boom")

    with patch("rrs.pipeline.jobs.download_video", side_effect=boom):
        with pytest.raises(DownloadError):
            await run_pre_interactive_pipeline(
                db=db,
                job_id=job_id,
                data_dir=tmp_path,
                scene_threshold=27.0,
            )
    assert db.get_job(job_id).status == JobStatus.FAILED
    assert "boom" in db.get_job(job_id).error


def test_job_paths_layout(tmp_path):
    paths = job_paths(tmp_path, job_id=42)
    assert paths.root == tmp_path / "jobs" / "42"
    assert paths.source == paths.root / "source.mp4"
    assert paths.frames_dir == paths.root / "frames"
    assert paths.sources_dir == paths.root / "sources"


def test_safe_dirname_sanitizes_and_falls_back():
    assert (
        safe_dirname("Ranking Best Cheetah Moments #usa", 1) == "Ranking Best Cheetah Moments #usa"
    )
    # illegal characters are replaced, whitespace collapsed, trailing dots stripped
    assert safe_dirname('a/b:c*d?e."', 1) == "a b c d e"
    assert safe_dirname("   ", 7) == "job-7"
    assert safe_dirname(None, 9) == "job-9"


def test_downloads_dir_layout(tmp_path):
    d = downloads_dir(tmp_path, "My Video", 3)
    assert d == tmp_path / "downloads" / "My Video"
    assert downloads_dir(tmp_path, None, 3) == tmp_path / "downloads" / "job-3"
