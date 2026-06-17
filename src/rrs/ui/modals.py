from __future__ import annotations

import asyncio
import html
import json
import shutil
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from nicegui import ui
from nicegui.events import GenericEventArguments, KeyEventArguments

from rrs.constants import MIN_CROP_FRACTION, SCRUB_THROTTLE_SEC
from rrs.pipeline.frames import FrameExtractError, extract_frame
from rrs.pipeline.jobs import job_paths
from rrs.pipeline.scenes import last_selectable_frame
from rrs.store.db import CropRect, Database, Scene
from rrs.ui.components import file_url, html_button


def crop_from_payload(payload: object) -> CropRect | None:
    """Validate a client pointer-up crop payload into a clamped CropRect.

    Returns None for a missing/empty payload, non-numeric fields, or a box
    smaller than `MIN_CROP_FRACTION` in either dimension (a stray click). The rect is
    clamped to stay fully inside the [0,1] frame."""
    if not isinstance(payload, dict):
        return None
    try:
        x = float(payload["x"])
        y = float(payload["y"])
        w = float(payload["w"])
        h = float(payload["h"])
    except (KeyError, TypeError, ValueError):
        return None
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    w = min(max(w, 0.0), 1.0 - x)
    h = min(max(h, 0.0), 1.0 - y)
    if w <= MIN_CROP_FRACTION or h <= MIN_CROP_FRACTION:
        return None
    return CropRect(x, y, w, h)


# Vanilla-JS crop overlay. All pointer dragging/resizing happens client-side
# (no websocket round-trip mid-drag). On pointer-up it dispatches an `rrs-crop`
# CustomEvent on the overlay element; Python listens via an element-scoped
# `.on(...)`. Idempotent: guarded by `window.rrsCrop ||`.
_CROP_JS = """
window.rrsCrop = window.rrsCrop || {
  instances: {},
  set(id, rect) { const i = this.instances[id]; if (i) i.set(rect); },
  init(elId, initial, minCrop) {
    const overlay = document.getElementById('c' + elId);
    if (!overlay) return;
    const box = overlay.querySelector('.rrs-crop-box');
    const size = overlay.querySelector('.rrs-crop-size');
    const MIN = minCrop;
    const clamp01 = (v) => Math.max(0, Math.min(1, v));
    const inst = { rect: initial || null, drag: null };
    this.instances[elId] = inst;

    const render = () => {
      const r = inst.rect;
      if (!r) { box.style.display = 'none'; return; }
      box.style.display = 'block';
      box.style.left = (r.x * 100) + '%';
      box.style.top = (r.y * 100) + '%';
      box.style.width = (r.w * 100) + '%';
      box.style.height = (r.h * 100) + '%';
      size.textContent = Math.round(r.w * 100) + '\\u00d7' + Math.round(r.h * 100) + '%';
    };
    inst.set = (rect) => { inst.rect = rect; render(); };

    const pos = (e) => {
      const b = overlay.getBoundingClientRect();
      return { x: clamp01((e.clientX - b.left) / b.width),
               y: clamp01((e.clientY - b.top) / b.height) };
    };
    const rectFrom = (a, c) => {
      const x = Math.min(a.x, c.x), y = Math.min(a.y, c.y);
      let w = Math.abs(c.x - a.x), h = Math.abs(c.y - a.y);
      w = Math.min(w, 1 - x); h = Math.min(h, 1 - y);
      return { x, y, w, h };
    };
    const inside = (r, p) => r && p.x >= r.x && p.x <= r.x + r.w
                              && p.y >= r.y && p.y <= r.y + r.h;

    overlay.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      overlay.setPointerCapture(e.pointerId);
      const p = pos(e);
      const prev = inst.rect ? { ...inst.rect } : null;
      const handle = e.target.dataset ? e.target.dataset.handle : null;
      if (handle && inst.rect) {
        const r = inst.rect;
        const anchor = { x: handle.includes('w') ? r.x + r.w : r.x,
                         y: handle.includes('n') ? r.y + r.h : r.y };
        inst.drag = { mode: 'resize', anchor, prev };
      } else if (inside(inst.rect, p)) {
        inst.drag = { mode: 'move', prev,
                      off: { x: p.x - inst.rect.x, y: p.y - inst.rect.y } };
      } else {
        inst.drag = { mode: 'resize', anchor: p, prev };
        inst.rect = { x: p.x, y: p.y, w: 0, h: 0 };
        render();
      }
    });
    overlay.addEventListener('pointermove', (e) => {
      if (!inst.drag) return;
      const p = pos(e);
      if (inst.drag.mode === 'move') {
        const r = inst.drag.prev;
        const nx = Math.min(clamp01(p.x - inst.drag.off.x), 1 - r.w);
        const ny = Math.min(clamp01(p.y - inst.drag.off.y), 1 - r.h);
        inst.rect = { x: nx, y: ny, w: r.w, h: r.h };
      } else {
        inst.rect = rectFrom(inst.drag.anchor, p);
      }
      render();
    });
    const end = () => {
      if (!inst.drag) return;
      const prev = inst.drag.prev;
      inst.drag = null;
      const r = inst.rect;
      // Sub-min drag = stray click: keep the previous crop untouched.
      if (!r || r.w <= MIN || r.h <= MIN) inst.rect = prev;
      render();
      overlay.dispatchEvent(new CustomEvent('rrs-crop', { detail: inst.rect }));
    };
    overlay.addEventListener('pointerup', end);
    overlay.addEventListener('pointercancel', end);

    render();
  }
};
"""


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

    frames = db.list_frames(scene.id)
    if not frames:
        return
    frame_row = frames[0]
    # `end` is the last *selectable* frame: scene.end_frame is exclusive (the
    # first frame of the next scene, and one past EOF for the final scene), so
    # scrubbing to it would request an undecodable frame. See last_selectable_frame.
    start = scene.start_frame
    end = last_selectable_frame(scene.start_frame, scene.end_frame)
    # Canonical selected-frame file (what the scene card shows). We never write it
    # while scrubbing — previews go to a temp file — so cancel reverts cleanly.
    out_path = paths.frames_dir / str(scene.idx) / "0.jpg"
    scrub_path = paths.frames_dir / str(scene.idx) / "_scrub.jpg"
    state: dict = {
        "fn": max(start, min(end, frame_row.frame_number)),
        "crop": frame_row.crop,  # CropRect | None
    }
    pending: list[asyncio.Task] = []  # most recent in-flight extraction, awaited on commit

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
        _render_label()

    def _scrub(fn: int) -> None:
        pending.append(asyncio.create_task(_show(fn)))

    def _step(delta: int) -> None:
        _scrub(state["fn"] + delta)

    def _on_crop_event(e: GenericEventArguments) -> None:
        detail = e.args
        if isinstance(detail, dict) and "detail" in detail:
            detail = detail["detail"]
        state["crop"] = crop_from_payload(detail)
        _render_label()

    def _reset_crop() -> None:
        state["crop"] = None
        ui.run_javascript(f"window.rrsCrop.set({overlay.id}, null)")
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
            with ui.element("div").classes("rrs-crop-wrap"):
                img = ui.interactive_image(initial, cross=False).classes("rrs-scrub-preview")
                with ui.element("div").classes("rrs-crop-layer") as overlay:
                    with ui.element("div").classes("rrs-crop-box"):
                        for h in ("nw", "ne", "sw", "se"):
                            ui.element("div").classes("rrs-crop-handle").props(f"data-handle={h}")
                        ui.element("div").classes("rrs-crop-size")
            overlay.on("rrs-crop", _on_crop_event, args=["detail"])
            label = ui.html(f"frame {state['fn']} / scene {start}–{end}").classes("rrs-scrub-label")
            err_label = ui.html("").classes("rrs-scrub-err-row")

            with ui.element("div").classes("rrs-scrub-row"):
                html_button("‹", lambda: _step(-1), classes="rrs-btn rrs-scrub-step")
                slider = ui.slider(min=start, max=end, step=1, value=state["fn"]).classes(
                    "rrs-scrub-slider"
                )
                slider.on(
                    "update:model-value", lambda e: _scrub(e.args), throttle=SCRUB_THROTTLE_SEC
                )
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
    c = state["crop"]
    initial_crop = "null" if c is None else json.dumps(asdict(c))
    # Send the module (idempotent) and init in one round-trip so the guard and
    # init always run in the same microtask. MIN_CROP_FRACTION is the single source of
    # truth for the stray-click threshold, passed through to the overlay.
    ui.run_javascript(
        f"{_CROP_JS}\nwindow.rrsCrop.init({overlay.id}, {initial_crop}, {MIN_CROP_FRACTION})"
    )
    await _show(state["fn"])
