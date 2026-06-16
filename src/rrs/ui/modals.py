from __future__ import annotations

import asyncio
import html
import shutil
from collections.abc import Callable
from pathlib import Path

from nicegui import ui
from nicegui.events import KeyEventArguments, MouseEventArguments

from rrs.pipeline.frames import FrameExtractError, extract_frame, get_video_dimensions
from rrs.pipeline.jobs import job_paths
from rrs.store.db import CropRect, Database, Scene
from rrs.ui.components import file_url, html_button

# A drag smaller than this fraction of the frame is treated as a stray click, not
# a crop — so a single click never wipes an existing crop.
_MIN_CROP = 0.01


async def open_frame_picker(
    db: Database,
    data_dir: Path,
    job_id: int,
    scene: Scene,
    on_close: Callable[[], None],
) -> None:
    """Scrub the scene to pick the frame (and optional crop) to reverse-search.

    A slider (one step = one frame), ‹ › buttons and ← → arrow keys move through
    the scene's frame range; dragging a box on the preview marks a crop region.
    Only USE THIS FRAME commits — clicking the backdrop or pressing Esc cancels
    and leaves the previously-selected frame/crop untouched. `on_close` then
    refreshes the scene list in place."""
    paths = job_paths(data_dir, job_id)
    aspect_w, aspect_h = get_video_dimensions(paths.source)

    frames = db.list_frames(scene.id)
    if not frames:
        return
    frame_row = frames[0]
    start, end = scene.start_frame, scene.end_frame
    # Canonical selected-frame file (what the scene card shows). We never write it
    # while scrubbing — previews go to a temp file — so cancel reverts cleanly.
    out_path = paths.frames_dir / str(scene.idx) / "0.jpg"
    scrub_path = paths.frames_dir / str(scene.idx) / "_scrub.jpg"
    state: dict = {
        "fn": max(start, min(end, frame_row.frame_number)),
        "crop": frame_row.crop,  # CropRect | None
        "drag": None,  # (x0, y0) normalized while dragging, else None
    }
    pending: list[asyncio.Task] = []  # most recent in-flight extraction, awaited on commit

    def _crop_svg(rect: CropRect | None) -> str:
        if rect is None:
            return ""
        x, y = rect.x * aspect_w, rect.y * aspect_h
        w, h = rect.w * aspect_w, rect.h * aspect_h
        return (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="rgba(255,255,255,0.12)" stroke="#fff" stroke-width="2" '
            f'vector-effect="non-scaling-stroke" />'
        )

    def _render_crop(live: CropRect | None = None) -> None:
        img.set_content(_crop_svg(live if live is not None else state["crop"]))

    def _render_label() -> None:
        crop = state["crop"]
        crop_txt = (
            f" &nbsp;·&nbsp; crop {round(crop.w * 100)}×{round(crop.h * 100)}%" if crop else ""
        )
        label.set_content(f"frame {state['fn']} / scene {start}–{end}{crop_txt}")

    async def _show(fn: int) -> None:
        fn = max(start, min(end, int(fn)))
        state["fn"] = fn
        try:
            await asyncio.to_thread(extract_frame, paths.source, fn, scrub_path)
        except FrameExtractError as exc:
            # Keep the previous preview rather than crashing the task (some frames
            # near the end of a scene are undecodable).
            err_label.set_content(f'<span class="rrs-scrub-err">{html.escape(str(exc))}</span>')
            return
        err_label.set_content("")
        img.set_source(f"{file_url(scrub_path, data_dir)}&fn={fn}")
        slider.value = fn  # programmatic set: keeps the handle in sync, no event
        _render_crop()
        _render_label()

    def _scrub(fn: int) -> None:
        pending.append(asyncio.create_task(_show(fn)))

    def _step(delta: int) -> None:
        _scrub(state["fn"] + delta)

    def _rect_from(p0: tuple[float, float], p1: tuple[float, float]) -> CropRect:
        x0, y0 = p0
        x1, y1 = p1
        x, y = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        # Clamp to the frame.
        w, h = min(w, 1.0 - x), min(h, 1.0 - y)
        return CropRect(x, y, w, h)

    def _on_mouse(e: MouseEventArguments) -> None:
        nx = max(0.0, min(1.0, e.image_x / aspect_w))
        ny = max(0.0, min(1.0, e.image_y / aspect_h))
        if e.type == "mousedown":
            state["drag"] = (nx, ny)
        elif e.type == "mousemove" and state["drag"] is not None:
            _render_crop(live=_rect_from(state["drag"], (nx, ny)))
        elif e.type == "mouseup" and state["drag"] is not None:
            rect = _rect_from(state["drag"], (nx, ny))
            state["drag"] = None
            if rect.w > _MIN_CROP and rect.h > _MIN_CROP:
                state["crop"] = rect
            _render_crop()
            _render_label()

    def _reset_crop() -> None:
        state["crop"] = None
        _render_crop()
        _render_label()

    def _on_key(e: KeyEventArguments) -> None:
        if not dialog.value or not e.action.keydown:
            return
        if e.key.arrow_left:
            _step(-1)
        elif e.key.arrow_right:
            _step(1)

    async def _commit() -> None:
        # Wait for the last in-flight extraction so scrub_path matches state["fn"],
        # then promote it to the canonical frame and persist frame + crop.
        if pending:
            await pending[-1]
        if scrub_path.exists():
            shutil.copyfile(scrub_path, out_path)
        db.set_frame_image(frame_row.id, state["fn"], str(out_path))
        db.set_frame_crop(frame_row.id, state["crop"])
        dialog.close()
        on_close()

    with ui.dialog().classes("rrs-modal-backdrop") as dialog:
        with ui.element("div").classes("rrs-modal"):
            ui.html('<div class="rrs-label" style="margin-bottom:14px">PICK FRAME</div>')

            # Start on the current committed frame so the modal isn't blank; the
            # awaited _show() below swaps in the scrub preview.
            initial = f"{file_url(out_path, data_dir)}" if out_path.exists() else ""
            img = ui.interactive_image(
                initial,
                events=["mousedown", "mousemove", "mouseup"],
                on_mouse=_on_mouse,
                cross=False,
                sanitize=False,
            ).classes("rrs-scrub-preview")
            label = ui.html(f"frame {state['fn']} / scene {start}–{end}").classes("rrs-scrub-label")
            err_label = ui.html("").classes("rrs-scrub-err-row")

            with ui.element("div").classes("rrs-scrub-row"):
                html_button("‹", lambda: _step(-1), classes="rrs-btn rrs-scrub-step")
                slider = ui.slider(min=start, max=end, step=1, value=state["fn"]).classes(
                    "rrs-scrub-slider"
                )
                slider.on("update:model-value", lambda e: _scrub(e.args), throttle=0.15)
                # The throttled live event can drop the final drag-release value
                # (why clicking the track "fixes" it); `change` fires on release
                # un-throttled, guaranteeing the landed frame always renders.
                slider.on("change", lambda e: _scrub(e.args))
                html_button("›", lambda: _step(1), classes="rrs-btn rrs-scrub-step")

            # ignore=[] so arrows fire even when a ‹/› button has focus; the
            # handler itself no-ops unless this picker dialog is open.
            ui.keyboard(on_key=_on_key, ignore=[])

            with ui.element("div").classes("rrs-modal-actions"):
                html_button("RESET CROP", _reset_crop)
                html_button("USE THIS FRAME", _commit, classes="rrs-btn rrs-btn-primary")

    dialog.open()
    await _show(state["fn"])
