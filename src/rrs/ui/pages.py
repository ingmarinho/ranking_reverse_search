from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from rrs.config import Config
from rrs.pipeline.download import download_video
from rrs.pipeline.engines import get_engine
from rrs.pipeline.frames import crop_image, get_video_dimensions
from rrs.pipeline.hosting import ImgbbError, effective_imgbb_key, upload_image
from rrs.pipeline.jobs import downloads_dir, job_paths, run_pre_interactive_pipeline
from rrs.store.db import Database, Frame, Job, JobStatus, Scene
from rrs.ui.components import html_button, render_scene_card
from rrs.ui.modals import open_frame_picker
from rrs.ui.onboarding import open_imgbb_settings, render_onboarding

GetDb = Callable[[], Database]
GetCfg = Callable[[], Config]

_INFLIGHT: set[int] = set()


def register_pages(get_db: GetDb, get_cfg: GetCfg) -> None:
    @ui.page("/")
    async def index() -> None:
        _render_wizard(get_db(), get_cfg())


def _find_active_job(db: Database) -> Job | None:
    """Return the most recent non-deleted job, or None."""
    row = db._conn.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
    return db.get_job(row["id"]) if row else None


@ui.refreshable
def _render_wizard(db: Database, cfg: Config) -> None:
    # Re-fetch the active job on every (re)render so `.refresh()` reflects the
    # latest DB state in place — no full page reload, scroll position preserved.
    job = _find_active_job(db)
    # Gate the whole app behind having a key. render_onboarding opens its own
    # rrs-wrap, so return before opening ours to avoid double-nesting.
    if effective_imgbb_key(db, cfg) is None:
        render_onboarding(db, cfg, on_ready=_render_wizard.refresh)
        return
    with ui.element("div").classes("rrs-wrap"):
        with ui.row().classes("w-full items-center").style("justify-content:space-between"):
            ui.html('<div class="rrs-title">Ranking Reverse Search</div>')
            html_button(
                "API KEY",
                lambda: open_imgbb_settings(db, cfg, on_change=_render_wizard.refresh),
                classes="rrs-btn",
            )
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
            _render_wizard.refresh()

        html_button("PROCESS VIDEO", on_click, classes="rrs-btn rrs-btn-primary")


async def _run_pipeline(db: Database, cfg: Config, job_id: int) -> None:
    _INFLIGHT.add(job_id)
    try:
        await run_pre_interactive_pipeline(
            db=db,
            job_id=job_id,
            data_dir=cfg.data_dir,
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
        html_button("START OVER", lambda: _start_over(db, cfg.data_dir, job.id))
        return
    if status in (
        JobStatus.DOWNLOADING,
        JobStatus.DETECTING_SCENES,
        JobStatus.EXTRACTING_FRAMES,
    ):
        if job.id in _INFLIGHT:
            _render_progress(job)
            ui.timer(1.0, _render_wizard.refresh, once=True)
        else:
            _render_progress(job)
            ui.html(
                '<div class="rrs-meta" style="margin-top:14px">'
                "no worker running for this stage</div>"
            )

            # NOTE: resume re-runs the current stage from scratch. If the prior
            # worker died mid-write (rare), the user should START OVER instead.
            def _resume():
                asyncio.create_task(_run_pipeline(db, cfg, job.id))
                _render_wizard.refresh()

            html_button("RESUME", _resume, classes="rrs-btn rrs-btn-primary")
            html_button("START OVER", lambda: _start_over(db, cfg.data_dir, job.id))
        return
    if status == JobStatus.INTERACTIVE:
        _render_scene_list(db, cfg, job)
        return


def _render_scene_list(db: Database, cfg: Config, job: Job) -> None:
    with ui.element("div").classes("rrs-scene-list-head"):
        with ui.element("div").classes("rrs-meta"):
            ui.html(f"<div>{(job.title or 'Untitled')} — {(job.duration_sec or 0):.1f}s</div>")
        html_button("START OVER", lambda: _start_over(db, cfg.data_dir, job.id))

    if not cfg.has_deno:
        ui.html(
            '<div class="rrs-error">deno not on PATH — YouTube downloads may be '
            "limited. Install Deno (https://deno.com/) for full support.</div>"
        )

    aspect = get_video_dimensions(Path(job.source_path)) if job.source_path else (16, 9)
    scenes = db.list_scenes(job.id)
    enabled_ids = json.loads(db.get_setting("enabled_engines") or "[]")
    for scene in scenes:
        render_scene_card(
            db=db,
            data_dir=cfg.data_dir,
            scene=scene,
            total_scenes=len(scenes),
            aspect=aspect,
            on_open_frame_picker=lambda s: _open_frame_picker(db, cfg, s),
            on_search_click=lambda s, eid: _do_reverse_search(db, cfg, s, eid),
            on_download=lambda sid, url: download_source_for_scene(db, cfg.data_dir, sid, url),
            on_open_folder=lambda: _open_downloads_folder(cfg.data_dir, job),
            enabled_ids=enabled_ids,
        )


async def _open_frame_picker(db: Database, cfg: Config, scene: Scene) -> None:
    job = _find_active_job(db)
    if job is None:
        return
    await open_frame_picker(db, cfg.data_dir, job.id, scene, on_close=_render_wizard.refresh)


async def _do_reverse_search(db: Database, cfg: Config, scene: Scene, engine_id: str) -> None:
    engine = get_engine(engine_id)
    if engine is None or engine.status != "ready":
        ui.notify(f"{engine_id} is not implemented yet", type="warning")
        return
    if effective_imgbb_key(db, cfg) is None:
        ui.notify("imgbb key not set", type="negative")
        return

    selected = [f for f in db.list_frames(scene.id) if f.is_selected]
    if not selected:
        ui.notify("no frames selected", type="warning")
        return

    # Each selected frame is an alternate candidate for the same source clip, so
    # one engine click opens that engine for every selected frame.
    for frame in selected:
        url = await _engine_url_for_frame(db, cfg, engine, frame)
        if url is not None:
            ui.run_javascript(f"window.open({url!r}, '_blank')")


async def _engine_url_for_frame(db: Database, cfg: Config, engine, frame: Frame) -> str | None:
    if frame.imgbb_url:
        image_url = frame.imgbb_url
    else:
        upload_path = Path(frame.path)
        if frame.crop is not None:
            # Search the cropped region: write a sidecar next to the full frame,
            # upload that instead. imgbb_url is cleared whenever the crop changes.
            sidecar = upload_path.with_name("0_crop.jpg")
            try:
                await asyncio.to_thread(
                    crop_image,
                    upload_path,
                    (frame.crop.x, frame.crop.y, frame.crop.w, frame.crop.h),
                    sidecar,
                )
            except Exception as exc:  # noqa: BLE001 — surface crop failure inline
                ui.notify(f"crop failed: {exc}", type="negative")
                return None
            upload_path = sidecar
        try:
            key = effective_imgbb_key(db, cfg)
            image_url = await asyncio.to_thread(upload_image, upload_path, key)
        except ImgbbError as exc:
            ui.notify(f"imgbb: {exc}", type="negative")
            return None
        db.set_frame_imgbb_url(frame.id, image_url)
    return engine.search_url(image_url)


async def download_source_for_scene(db: Database, data_dir: Path, scene_id: int, url: str) -> str:
    """Download the source clip for a scene; return the saved filename.

    Raises (e.g. DownloadError) on failure so the caller can show it inline."""
    job = _find_active_job(db)
    scene = next((s for s in db.list_scenes(job.id) if s.id == scene_id), None) if job else None
    if scene is None or job is None:
        raise RuntimeError("scene not found")
    out_dir = downloads_dir(data_dir, job.title, job.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"scene-{scene.idx + 1:02d}.mp4"

    src_id = db.upsert_source(scene_id=scene.id, url=url)
    result = await asyncio.to_thread(download_video, url, out, None)
    db.set_source_downloaded(src_id, path=str(result.path))
    return Path(result.path).name


def _open_downloads_folder(data_dir: Path, job: Job) -> None:
    """Reveal the job's downloads folder in the OS file manager (local app)."""
    folder = downloads_dir(data_dir, job.title, job.id)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except OSError as exc:
        ui.notify(f"could not open folder: {exc}", type="negative")


def _render_progress(job: Job) -> None:
    labels = {
        JobStatus.DOWNLOADING: "DOWNLOADING RANKING VIDEO",
        JobStatus.DETECTING_SCENES: "DETECTING SCENES",
        JobStatus.EXTRACTING_FRAMES: "EXTRACTING FRAMES",
    }
    label = labels.get(job.status, str(job.status))
    ui.html('<div class="rrs-top-progress indet"><span></span></div>')
    ui.html(f'<div class="rrs-stage-label">{label}</div>')


def _start_over(db: Database, data_dir: Path, job_id: int) -> None:
    paths = job_paths(data_dir, job_id)
    if paths.root.exists():
        shutil.rmtree(paths.root, ignore_errors=True)
    db.delete_job(job_id)
    _render_wizard.refresh()
