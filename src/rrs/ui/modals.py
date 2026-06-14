from __future__ import annotations

from pathlib import Path
from typing import Callable

from nicegui import ui

from rrs.pipeline.frames import extract_evenly_spaced
from rrs.pipeline.jobs import job_paths
from rrs.store.db import Database, Scene
from rrs.ui.components import file_url

CANDIDATE_COUNT = 9


async def open_frame_picker(
    db: Database, data_dir: Path, job_id: int, scene: Scene,
    on_close: Callable[[], None],
) -> None:
    """Show modal grid of CANDIDATE_COUNT frames; click to toggle selection."""
    paths = job_paths(data_dir, job_id)
    cand_dir = paths.frames_dir / str(scene.idx) / "candidates"

    if not cand_dir.exists() or len(list(cand_dir.glob("cand_*.jpg"))) < CANDIDATE_COUNT:
        extract_evenly_spaced(
            video_path=paths.source,
            start_frame=scene.start_frame,
            end_frame=scene.end_frame,
            count=CANDIDATE_COUNT,
            out_dir=cand_dir,
        )

    candidates = sorted(cand_dir.glob("cand_*.jpg"))
    span = max(1, scene.end_frame - scene.start_frame)
    candidate_meta = [
        (scene.start_frame + int((i + 0.5) * span / CANDIDATE_COUNT), p)
        for i, p in enumerate(candidates)
    ]

    existing_frames = db.list_frames(scene.id)
    by_frame_number = {f.frame_number: f for f in existing_frames}

    with ui.dialog().props("persistent").classes("rrs-modal-backdrop") as dialog:
        with ui.element("div").classes("rrs-modal"):
            ui.html('<div class="rrs-label" style="margin-bottom:14px">SELECT FRAMES</div>')
            with ui.element("div").classes("rrs-grid-9"):
                for frame_number, path in candidate_meta:
                    existing = by_frame_number.get(frame_number)
                    selected = bool(existing and existing.is_selected)
                    url = file_url(path, data_dir)
                    sel_cls = " selected" if selected else ""
                    html = (
                        f'<div class="rrs-frame{sel_cls}" data-fn="{frame_number}">'
                        f'  <img src="{url}">'
                        f'</div>'
                    )
                    el = ui.html(html)

                    def _toggle(_, fn=frame_number, p=path):
                        _toggle_selection(db, scene, fn, p)
                        on_close()
                        dialog.close()
                        ui.navigate.reload()

                    el.on("click", _toggle)
            with ui.element("div").style("text-align:right; margin-top: 18px"):
                ui.button("CLOSE", on_click=lambda: (dialog.close(), on_close())).classes("rrs-btn")
    dialog.open()


def _toggle_selection(db: Database, scene: Scene, frame_number: int, path: Path) -> None:
    """Toggle is_selected for the candidate at frame_number. Inserts a frames row if new."""
    existing = [f for f in db.list_frames(scene.id) if f.frame_number == frame_number]
    if existing:
        f = existing[0]
        db.set_frame_selected(f.id, not f.is_selected)
        return
    next_ord = max((f.ordinal for f in db.list_frames(scene.id)), default=-1) + 1
    db.insert_frame(
        scene_id=scene.id, ordinal=next_ord, frame_number=frame_number,
        path=str(path), is_selected=True,
    )


async def open_trim_modal(
    db: Database, data_dir: Path, job_id: int, scene: Scene,
) -> None:
    src = db.get_source(scene.id)
    if src is None or not src.path:
        return

    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", src.path],
        capture_output=True, text=True,
    )
    try:
        source_duration = float(probe.stdout.strip())
    except ValueError:
        ui.notify("could not read source duration", type="negative")
        return

    scene_duration = scene.end_sec - scene.start_sec
    midpoint = source_duration / 2.0
    default_start = max(0.0, midpoint - scene_duration / 2.0)
    default_end = min(source_duration, midpoint + scene_duration / 2.0)

    initial_start = src.trim_start_sec if src.trim_start_sec is not None else default_start
    initial_end = src.trim_end_sec if src.trim_end_sec is not None else default_end

    video_url = file_url(src.path, data_dir)

    with ui.dialog().props("persistent").classes("rrs-modal-backdrop") as dialog:
        with ui.element("div").classes("rrs-modal"):
            ui.html('<div class="rrs-label" style="margin-bottom:14px">TRIM CLIP</div>')
            ui.html(
                f'<video controls src="{video_url}" '
                f'style="width:100%; max-height:50vh; background:black"></video>'
            )
            ui.html(
                f'<div class="rrs-meta rrs-timecode" style="margin-top:10px">'
                f'source duration: {source_duration:.2f}s  ·  scene Δ {scene_duration:.2f}s'
                f'</div>'
            )
            with ui.row().classes("w-full").style("gap:12px; margin-top:14px"):
                start_in = ui.number(label="START (s)", value=round(initial_start, 3), format="%.3f").classes("rrs-input")
                end_in = ui.number(label="END (s)", value=round(initial_end, 3), format="%.3f").classes("rrs-input")

            async def on_save() -> None:
                from rrs.pipeline.jobs import job_paths
                from rrs.pipeline.trim import TrimError, trim_clip
                import asyncio

                a = float(start_in.value)
                b = float(end_in.value)
                if b <= a:
                    ui.notify("END must be greater than START", type="negative")
                    return
                paths = job_paths(data_dir, job_id)
                paths.clips_dir.mkdir(parents=True, exist_ok=True)
                out = paths.clips_dir / f"{scene.idx}.mp4"
                try:
                    await asyncio.to_thread(trim_clip, Path(src.path), a, b, out)
                except TrimError as exc:
                    ui.notify(f"ffmpeg: {exc}", type="negative")
                    return
                db.set_source_clip(src.id, trim_start_sec=a, trim_end_sec=b, clip_path=str(out))
                ui.notify("clip saved", type="positive")
                dialog.close()
                ui.navigate.reload()

            with ui.row().style("justify-content: flex-end; gap: 10px; margin-top: 18px"):
                ui.button("CANCEL", on_click=dialog.close).classes("rrs-btn")
                ui.button("SAVE CLIP", on_click=on_save).classes("rrs-btn rrs-btn-primary")
    dialog.open()
