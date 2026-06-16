from __future__ import annotations

from unittest.mock import patch

import pytest

from rrs.pipeline.download import DownloadResult
from rrs.store.db import JobStatus
from rrs.ui.pages import download_extra_clip


@pytest.mark.asyncio
async def test_download_extra_clip_numbers_into_job_folder(db, tmp_path):
    job_id = db.create_job(url="ranking")
    db.set_job_source(job_id, title="My Video", duration_sec=1.0, source_path="/s.mp4")
    db.update_job_status(job_id, JobStatus.INTERACTIVE)  # _find_active_job picks the newest job

    def fake_download(url, out_path, max_height, progress_hook=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.touch()
        return DownloadResult(path=out_path, title="clip", duration_sec=3.0)

    with patch("rrs.ui.pages.download_video", side_effect=fake_download):
        name1 = await download_extra_clip(db, tmp_path, "https://clip/1")
        name2 = await download_extra_clip(db, tmp_path, "https://clip/2")

    folder = tmp_path / "downloads" / "My Video"
    assert name1 == "extra-01.mp4"
    assert name2 == "extra-02.mp4"
    assert (folder / "extra-01.mp4").exists()
    assert (folder / "extra-02.mp4").exists()


@pytest.mark.asyncio
async def test_download_extra_clip_raises_without_active_job(db, tmp_path):
    with pytest.raises(RuntimeError):
        await download_extra_clip(db, tmp_path, "https://clip/1")
