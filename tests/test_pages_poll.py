from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from rrs.config import Config
from rrs.store.db import JobStatus
from rrs.ui import pages
from rrs.ui.pages import _poll_progress


def _cfg(imgbb_api_key: str | None) -> Config:
    return Config(
        data_dir=Path("."),
        port=8080,
        scene_threshold=27.0,
        imgbb_api_key=imgbb_api_key,
        has_deno=False,
    )


def test_poll_does_not_refresh_while_onboarding_gate_is_up(db):
    """With no effective key the onboarding gate is showing; the poller must not
    refresh, otherwise it rebuilds the key input every tick and steals focus."""
    job_id = db.create_job(url="ranking")
    db.update_job_status(job_id, JobStatus.INTERACTIVE)
    pages._RENDERED_STATUS.clear()

    with patch.object(pages._render_wizard, "refresh") as refresh:
        _poll_progress(db, _cfg(None))

    refresh.assert_not_called()


def test_poll_refreshes_on_status_change_when_key_present(db):
    job_id = db.create_job(url="ranking")
    db.update_job_status(job_id, JobStatus.INTERACTIVE)
    pages._RENDERED_STATUS.clear()

    with patch.object(pages._render_wizard, "refresh") as refresh:
        _poll_progress(db, _cfg("a-key"))

    refresh.assert_called_once()
