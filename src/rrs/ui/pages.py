from __future__ import annotations

import asyncio
from typing import Callable

from nicegui import ui

from rrs.config import Config
from rrs.pipeline.jobs import run_pre_interactive_pipeline
from rrs.store.db import Database, Job, JobStatus, Scene

GetDb = Callable[[], Database]
GetCfg = Callable[[], Config]


def register_pages(get_db: GetDb, get_cfg: GetCfg) -> None:
    @ui.page("/")
    async def index() -> None:
        db = get_db()
        cfg = get_cfg()
        active = _find_active_job(db)
        _render_wizard(db, cfg, active)


def _find_active_job(db: Database) -> Job | None:
    """Return the most recent non-deleted job, or None."""
    row = db._conn.execute(
        "SELECT id FROM jobs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return db.get_job(row["id"]) if row else None


def _render_wizard(db: Database, cfg: Config, job: Job | None) -> None:
    with ui.element("div").classes("rrs-wrap"):
        ui.html('<div class="rrs-title">Ranking Reverse Search</div>')
        if job is None:
            _render_url_input(db, cfg)
            return
        _render_for_status(db, cfg, job)


def _render_url_input(db: Database, cfg: Config) -> None:
    ui.html('<div class="rrs-label" style="margin-bottom:8px">Paste ranking video URL</div>')
    with ui.row().classes("w-full"):
        url_input = ui.input(placeholder="https://...").classes("rrs-input").style("flex:1")

        async def on_click() -> None:
            url = url_input.value.strip()
            if not url:
                return
            job_id = db.create_job(url=url)
            asyncio.create_task(_run_pipeline(db, cfg, job_id))
            ui.navigate.reload()

        ui.button("PROCESS VIDEO", on_click=on_click).props("flat").classes("rrs-btn rrs-btn-primary")


async def _run_pipeline(db: Database, cfg: Config, job_id: int) -> None:
    try:
        await run_pre_interactive_pipeline(
            db=db, job_id=job_id, data_dir=cfg.data_dir,
            scene_threshold=cfg.scene_threshold,
        )
    except Exception:
        pass


def _render_for_status(db: Database, cfg: Config, job: Job) -> None:
    status = job.status
    if status == JobStatus.FAILED:
        ui.html(f'<div class="rrs-error">{(job.error or "Unknown error")}</div>')
        ui.button("START OVER", on_click=lambda: _start_over(db, job.id)).classes("rrs-btn")
        return
    if status in (
        JobStatus.DOWNLOADING,
        JobStatus.DETECTING_SCENES,
        JobStatus.EXTRACTING_FRAMES,
    ):
        _render_progress(job)
        ui.timer(1.0, lambda: ui.navigate.reload(), once=True)
        return
    if status == JobStatus.INTERACTIVE:
        _render_scene_list(db, cfg, job)
        return


def _render_scene_list(db: Database, cfg: Config, job: Job) -> None:
    from rrs.ui.components import render_scene_card

    with ui.element("div").classes("rrs-meta"):
        ui.html(
            f'<div>{(job.title or "Untitled")} — '
            f'{(job.duration_sec or 0):.1f}s</div>'
        )
    ui.button("START OVER", on_click=lambda: _start_over(db, job.id)).classes("rrs-btn")

    scenes = db.list_scenes(job.id)
    for scene in scenes:
        render_scene_card(
            db=db, data_dir=cfg.data_dir, scene=scene, total_scenes=len(scenes),
            on_open_frame_picker=lambda s: _open_frame_picker(db, cfg, s),
            on_open_trim=lambda s: _open_trim(db, cfg, s),
            on_search_click=lambda f, eid: _do_reverse_search(db, cfg, f, eid),
        )


# Placeholder handlers — filled in by later tasks.
def _open_frame_picker(db: Database, cfg: Config, scene: Scene) -> None:
    from rrs.ui.modals import open_frame_picker

    job = _find_active_job(db)
    if job is None:
        return
    asyncio.create_task(
        open_frame_picker(db, cfg.data_dir, job.id, scene, on_close=lambda: None)
    )


def _open_trim(db, cfg, scene):
    ui.notify("trim modal — Task 17", type="warning")


def _do_reverse_search(db, cfg, frame, engine_id):
    ui.notify("reverse search — Task 16", type="warning")


async def download_source_for_scene(db, data_dir, scene_id, url):
    ui.notify("source download — Task 16", type="warning")


def _render_progress(job: Job) -> None:
    labels = {
        JobStatus.DOWNLOADING: "DOWNLOADING RANKING VIDEO",
        JobStatus.DETECTING_SCENES: "DETECTING SCENES",
        JobStatus.EXTRACTING_FRAMES: "EXTRACTING FRAMES",
    }
    label = labels.get(job.status, str(job.status))
    ui.html(f'<div class="rrs-top-progress indet"><span></span></div>')
    ui.html(f'<div class="rrs-stage-label">{label}</div>')


def _start_over(db: Database, job_id: int) -> None:
    import shutil
    from rrs.pipeline.jobs import job_paths
    from rrs.main import get_cfg
    paths = job_paths(get_cfg().data_dir, job_id)
    if paths.root.exists():
        shutil.rmtree(paths.root, ignore_errors=True)
    db.delete_job(job_id)
    ui.navigate.to("/")
