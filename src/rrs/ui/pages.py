from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from nicegui import ui

from rrs.config import Config
from rrs.pipeline.jobs import run_pre_interactive_pipeline
from rrs.store.db import Database, Job, JobStatus, Scene

GetDb = Callable[[], Database]
GetCfg = Callable[[], Config]

_INFLIGHT: set[int] = set()


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
    _INFLIGHT.add(job_id)
    try:
        await run_pre_interactive_pipeline(
            db=db, job_id=job_id, data_dir=cfg.data_dir,
            scene_threshold=cfg.scene_threshold,
        )
    except Exception:
        pass
    finally:
        _INFLIGHT.discard(job_id)


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
        if job.id in _INFLIGHT:
            _render_progress(job)
            ui.timer(1.0, lambda: ui.navigate.reload(), once=True)
        else:
            _render_progress(job)
            ui.html('<div class="rrs-meta" style="margin-top:14px">no worker running for this stage</div>')
            # NOTE: resume re-runs the current stage from scratch. If the prior
            # worker died mid-write (rare), the user should START OVER instead.
            def _resume():
                import asyncio
                asyncio.create_task(_run_pipeline(db, cfg, job.id))
                ui.navigate.reload()
            ui.button("RESUME", on_click=_resume).classes("rrs-btn rrs-btn-primary")
            ui.button("START OVER", on_click=lambda: _start_over(db, job.id)).classes("rrs-btn")
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

    if cfg.imgbb_api_key is None:
        ui.html('<div class="rrs-error">IMGBB_API_KEY not set — engine buttons disabled</div>')

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


def _open_trim(db: Database, cfg: Config, scene: Scene) -> None:
    from rrs.ui.modals import open_trim_modal
    job = _find_active_job(db)
    if job is None:
        return
    asyncio.create_task(open_trim_modal(db, cfg.data_dir, job.id, scene))


def _active_job_id(db) -> int | None:
    job = _find_active_job(db)
    return job.id if job else None


def _do_reverse_search(db: Database, cfg: Config, frame, engine_id: str) -> None:
    from rrs.pipeline.engines import get_engine
    from rrs.pipeline.hosting import ImgbbError, upload_image

    engine = get_engine(engine_id)
    if engine is None or engine.status != "ready":
        ui.notify(f"{engine_id} is not implemented yet", type="warning")
        return
    if cfg.imgbb_api_key is None:
        ui.notify("IMGBB_API_KEY not set", type="negative")
        return

    async def _go() -> None:
        fresh = next((f for f in db.list_frames(frame.scene_id) if f.id == frame.id), None)
        if fresh is None:
            ui.notify("frame missing", type="negative")
            return
        if fresh.imgbb_url:
            image_url = fresh.imgbb_url
        else:
            try:
                image_url = await asyncio.to_thread(
                    upload_image, Path(fresh.path), cfg.imgbb_api_key
                )
            except ImgbbError as exc:
                ui.notify(f"imgbb: {exc}", type="negative")
                return
            db.set_frame_imgbb_url(fresh.id, image_url)
        url = engine.search_url(image_url)
        if url is None:
            ui.notify(f"{engine_id} not searchable", type="warning")
            return
        ui.run_javascript(f"window.open({url!r}, '_blank')")

    asyncio.create_task(_go())


async def download_source_for_scene(db: Database, data_dir, scene_id: int, url: str) -> None:
    from rrs.pipeline.download import DownloadError, download_video
    from rrs.pipeline.jobs import job_paths

    scene = next((s for s in db.list_scenes(_active_job_id(db) or -1) if s.id == scene_id), None)
    if scene is None:
        ui.notify("scene not found", type="negative")
        return
    paths = job_paths(data_dir, scene.job_id)
    paths.sources_dir.mkdir(parents=True, exist_ok=True)
    out = paths.sources_dir / f"{scene.idx}.mp4"

    src_id = db.upsert_source(scene_id=scene.id, url=url)
    try:
        result = await asyncio.to_thread(
            download_video, url, out, None
        )
    except DownloadError as exc:
        ui.notify(f"yt-dlp: {exc}", type="negative")
        return
    db.set_source_downloaded(src_id, path=str(result.path))
    ui.notify("source downloaded", type="positive")


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
