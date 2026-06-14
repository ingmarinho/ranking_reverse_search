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
