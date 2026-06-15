from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from nicegui import ui
from nicegui.events import KeyEventArguments

from rrs.pipeline.frames import extract_frame, get_video_dimensions
from rrs.pipeline.jobs import job_paths
from rrs.store.db import Database, Scene
from rrs.ui.components import file_url, html_button


async def open_frame_picker(
    db: Database,
    data_dir: Path,
    job_id: int,
    scene: Scene,
    on_close: Callable[[], None],
) -> None:
    """Scrub the scene to pick the single frame to reverse-search.

    A slider (one step = one frame), ‹ › buttons and ← → arrow keys move through
    the scene's frame range; the preview is the exact frame extracted at that
    position. USE THIS FRAME (or Esc/backdrop) confirms the current frame as the
    scene's selected frame and reloads the page."""
    paths = job_paths(data_dir, job_id)
    aspect_w, aspect_h = get_video_dimensions(paths.source)

    frames = db.list_frames(scene.id)
    if not frames:
        return
    frame_row = frames[0]
    start, end = scene.start_frame, scene.end_frame
    # Scrub straight into the scene's canonical selected-frame file: the preview
    # the user sees IS the frame that gets saved, so confirm needs no re-extract.
    out_path = paths.frames_dir / str(scene.idx) / "0.jpg"
    portrait = aspect_h > aspect_w
    state = {"fn": max(start, min(end, frame_row.frame_number)), "zoom": 1.0}
    pending: list[asyncio.Task] = []  # most recent in-flight extraction, awaited on confirm

    def _img_html() -> str:
        url = file_url(out_path, data_dir) if out_path.exists() else ""
        z = state["zoom"]
        # Full frame ("contain") at 1×; sized along the limiting axis so zoom>1
        # overflows the scroll container for panning. Portrait fits to height.
        size = f"height: calc({z} * 60vh); width: auto;" if portrait else f"width: {z * 100}%;"
        return f'<img class="rrs-scrub-img" style="{size}" src="{url}">'

    def _render_preview() -> None:
        preview.set_content(_img_html())
        label.set_content(
            f"frame {state['fn']} / scene {start}–{end} &nbsp;·&nbsp; {round(state['zoom'] * 100)}%"
        )

    async def _show(fn: int) -> None:
        fn = max(start, min(end, int(fn)))
        state["fn"] = fn
        await asyncio.to_thread(extract_frame, paths.source, fn, out_path)
        _render_preview()
        slider.value = fn  # programmatic set: keeps the handle in sync, no event

    def _scrub(fn: int) -> None:
        pending.append(asyncio.create_task(_show(fn)))

    def _step(delta: int) -> None:
        _scrub(state["fn"] + delta)

    def _zoom(delta: float) -> None:
        state["zoom"] = max(1.0, min(5.0, round(state["zoom"] + delta, 2)))
        _render_preview()

    def _on_key(e: KeyEventArguments) -> None:
        if not dialog.value or not e.action.keydown:
            return
        if e.key.arrow_left:
            _step(-1)
        elif e.key.arrow_right:
            _step(1)
        elif e.key == "+" or e.key == "=":
            _zoom(0.25)
        elif e.key == "-":
            _zoom(-0.25)

    with ui.dialog().classes("rrs-modal-backdrop") as dialog:
        with ui.element("div").classes("rrs-modal"):
            ui.html('<div class="rrs-label" style="margin-bottom:14px">PICK FRAME</div>')

            preview = ui.html(_img_html()).classes("rrs-scrub-preview")
            label = ui.html(f"frame {state['fn']} / scene {start}–{end}").classes("rrs-scrub-label")

            with ui.element("div").classes("rrs-scrub-row"):
                html_button("‹", lambda: _step(-1), classes="rrs-btn rrs-scrub-step")
                slider = ui.slider(min=start, max=end, step=1, value=state["fn"]).classes(
                    "rrs-scrub-slider"
                )
                slider.on(
                    "update:model-value",
                    lambda e: _scrub(e.args),
                    throttle=0.15,
                )
                html_button("›", lambda: _step(1), classes="rrs-btn rrs-scrub-step")
                html_button("−", lambda: _zoom(-0.25), classes="rrs-btn rrs-scrub-step")
                html_button("+", lambda: _zoom(0.25), classes="rrs-btn rrs-scrub-step")

            # ignore=[] so arrows fire even when a ‹/› button has focus; the
            # handler itself no-ops unless this picker dialog is open.
            ui.keyboard(on_key=_on_key, ignore=[])

            with ui.element("div").style("text-align:right; margin-top: 18px"):
                html_button("USE THIS FRAME", dialog.close, classes="rrs-btn rrs-btn-primary")

    async def _confirm() -> None:
        # Wait for the last in-flight extraction so out_path matches state["fn"],
        # then point the frames row at it (which also clears the stale imgbb_url).
        if pending:
            await pending[-1]
        db.set_frame_image(frame_row.id, state["fn"], str(out_path))
        on_close()
        ui.navigate.reload()

    # Pass the coroutine directly so NiceGUI awaits it inside the client/slot
    # context; a detached create_task would lose context and break navigate.reload.
    dialog.on("hide", _confirm)
    dialog.open()
    await _show(state["fn"])
