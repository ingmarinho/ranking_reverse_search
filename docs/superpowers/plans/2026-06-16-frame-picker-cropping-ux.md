# Frame-picker & Cropping UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the frame-picker crop interaction smooth and capable (move + corner-resize), fit the preview image to its container, and fix the source-URL placeholder alignment.

**Architecture:** Replace the server-round-trip SVG cropping in `ui/modals.py` with a dependency-free client-side overlay: a `position:relative` wrapper shrink-wraps the frame `<img>`, an absolutely-positioned overlay layer hosts the crop box + 4 corner handles, and all dragging happens in vanilla JS. Only the final normalized rect crosses the wire (on `pointerup`) via an element-scoped custom event; `state["crop"]` stays authoritative in Python and the commit/DB path is unchanged.

**Tech Stack:** Python 3.11+, NiceGUI 3.x, vanilla JS (pointer events), CSS. Spec: `docs/superpowers/specs/2026-06-16-frame-picker-cropping-ux-design.md`.

---

## File Structure

- `src/rrs/ui/modals.py` — frame picker. Remove `_on_mouse` / SVG-based crop; add the `_CROP_JS` client module, the DOM wrapper+overlay, the `crop_from_payload` pure helper, the `rrs-crop` event handler, and RESET/seed wiring to the JS API.
- `src/rrs/ui/static/app.css` — F1 preview sizing, crop overlay/box/handle styles, F5 input fix.
- `tests/test_modals.py` — new; unit tests for `crop_from_payload`.

Order: Task 1 (pure helper, TDD) → Task 2 (F1 CSS) → Task 3 (F2 overlay, depends on 1+2) → Task 4 (F5 CSS).

---

## Task 1: `crop_from_payload` validation helper

Pure function that turns the client's pointer-up payload into a clamped `CropRect | None`. This is the testable seam for F2 (the JS itself is verified manually).

**Files:**
- Modify: `src/rrs/ui/modals.py` (add `crop_from_payload` near the top, after `_MIN_CROP`)
- Test: `tests/test_modals.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_modals.py`:

```python
from __future__ import annotations

from rrs.store.db import CropRect
from rrs.ui.modals import crop_from_payload


def test_none_payload_returns_none():
    assert crop_from_payload(None) is None


def test_empty_dict_returns_none():
    assert crop_from_payload({}) is None


def test_valid_payload_returns_croprect():
    r = crop_from_payload({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})
    assert r == CropRect(0.1, 0.2, 0.3, 0.4)


def test_sub_min_size_returns_none():
    # w below _MIN_CROP (0.01) is a stray click, not a crop.
    assert crop_from_payload({"x": 0.1, "y": 0.1, "w": 0.005, "h": 0.5}) is None


def test_out_of_range_is_clamped():
    r = crop_from_payload({"x": -0.2, "y": 0.5, "w": 5.0, "h": 5.0})
    assert r is not None
    assert r.x == 0.0 and r.y == 0.5
    # w/h clamped so the box stays inside the frame.
    assert abs(r.x + r.w - 1.0) < 1e-9
    assert abs(r.y + r.h - 1.0) < 1e-9


def test_non_numeric_returns_none():
    assert crop_from_payload({"x": "a", "y": 0.1, "w": 0.5, "h": 0.5}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_modals.py -v`
Expected: FAIL — `ImportError: cannot import name 'crop_from_payload'`.

- [ ] **Step 3: Implement the helper**

In `src/rrs/ui/modals.py`, directly below the `_MIN_CROP = 0.01` definition, add:

```python
def crop_from_payload(payload: object) -> CropRect | None:
    """Validate a client pointer-up crop payload into a clamped CropRect.

    Returns None for a missing/empty payload, non-numeric fields, or a box
    smaller than `_MIN_CROP` in either dimension (a stray click). The rect is
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
    if w <= _MIN_CROP or h <= _MIN_CROP:
        return None
    return CropRect(x, y, w, h)
```

`CropRect` is already imported in `modals.py` (`from rrs.store.db import CropRect, Database, Scene`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_modals.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_modals.py src/rrs/ui/modals.py
git commit -m "feat: crop_from_payload validation helper for frame picker"
```

---

## Task 2: F1 — fit the preview image to its container

Constrain the frame image so it fits (no native-resolution overflow, no tiny floating image) and introduce the `position:relative` wrapper the overlay (Task 3) sits in.

**Files:**
- Modify: `src/rrs/ui/static/app.css:331-341` (the `.rrs-scrub-preview` block)

- [ ] **Step 1: Replace the preview CSS**

In `src/rrs/ui/static/app.css`, replace this block (currently around lines 331–341):

```css
.rrs-scrub-preview {
  width: 100%;
  max-height: 60vh;
  background: var(--surface);
  border: 1px solid var(--border);
  overflow: auto;
  cursor: crosshair;
}
.rrs-scrub-preview img { display: block; margin: 0 auto; }
```

with:

```css
/* Wrapper shrink-wraps the displayed image so the crop overlay (absolute,
   inset:0) is pixel-aligned with it. */
.rrs-crop-wrap {
  position: relative;
  width: fit-content;
  max-width: 100%;
  margin: 0 auto;
  background: var(--surface);
  border: 1px solid var(--border);
}
/* The interactive_image root must also shrink-wrap its <img> so the wrapper's
   width equals the displayed image width and the overlay (inset:0) aligns. */
.rrs-scrub-preview { display: block; width: fit-content; max-width: 100%; }
.rrs-scrub-preview img {
  display: block;
  max-width: 100%;
  max-height: 60vh;
  width: auto;
  height: auto;
}
/* The interactive_image SVG layer is unused for cropping now. */
.rrs-scrub-preview svg { pointer-events: none; }
```

- [ ] **Step 2: Verify CSS is syntactically valid**

Run: `python -c "import pathlib; t = pathlib.Path('src/rrs/ui/static/app.css').read_text(); assert t.count('{') == t.count('}'), (t.count('{'), t.count('}'))"`
Expected: no output (braces balanced).

- [ ] **Step 3: Commit**

```bash
git add src/rrs/ui/static/app.css
git commit -m "fix: fit frame-picker preview image to its container (F1)"
```

Visual confirmation happens at the end of Task 3 (the wrapper is only exercised once the overlay DOM exists).

---

## Task 3: F2 — client-side crop overlay (move + corner resize)

Replace the SVG/`_on_mouse` cropping with the JS overlay. This is the core task.

**Files:**
- Modify: `src/rrs/ui/modals.py` (remove `_crop_svg`, `_render_crop`, `_on_mouse`, `_rect_from`; add `_CROP_JS`, the DOM wrapper/overlay, the event handler, RESET/seed wiring)
- Modify: `src/rrs/ui/static/app.css` (add overlay/box/handle styles)

- [ ] **Step 1: Add the overlay CSS**

Append to `src/rrs/ui/static/app.css` (after the `.rrs-scrub-preview svg` rule from Task 2):

```css
/* Client-side crop overlay (move + corner-resize). */
.rrs-crop-overlay {
  position: absolute; inset: 0; z-index: 2;
  cursor: crosshair; touch-action: none;
}
.rrs-crop-box {
  position: absolute; box-sizing: border-box;
  border: 1px solid #fff;
  background: rgba(255, 255, 255, 0.12);
  cursor: move; display: none;
}
.rrs-crop-handle {
  position: absolute; width: 10px; height: 10px;
  background: var(--bg); border: 1px solid var(--accent);
  box-sizing: border-box;
}
.rrs-crop-handle[data-handle="nw"] { left: -5px; top: -5px; cursor: nwse-resize; }
.rrs-crop-handle[data-handle="ne"] { right: -5px; top: -5px; cursor: nesw-resize; }
.rrs-crop-handle[data-handle="sw"] { left: -5px; bottom: -5px; cursor: nesw-resize; }
.rrs-crop-handle[data-handle="se"] { right: -5px; bottom: -5px; cursor: nwse-resize; }
.rrs-crop-size {
  position: absolute; left: 2px; bottom: 2px;
  font-size: 10px; color: #fff; background: rgba(0, 0, 0, 0.5);
  padding: 0 3px; pointer-events: none;
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 2: Add the client-side JS module**

In `src/rrs/ui/modals.py`, after the imports and the `_MIN_CROP` / `crop_from_payload` definitions, add the JS module as a module-level constant. It is idempotent (`window.rrsCrop || {...}`), so re-sending it on every picker open is cheap and safe. It measures the overlay's own bounding rect (which equals the image rect, since the wrapper shrink-wraps the image and the overlay is `inset:0`), so it needs no image selector.

```python
# Vanilla-JS crop overlay. All pointer dragging/resizing happens client-side
# (no websocket round-trip mid-drag). On pointer-up it dispatches an `rrs-crop`
# CustomEvent on the overlay element; Python listens via an element-scoped
# `.on(...)`. Idempotent: guarded by `window.rrsCrop ||`.
_CROP_JS = """
window.rrsCrop = window.rrsCrop || {
  instances: {},
  set(id, rect) { const i = this.instances[id]; if (i) i.set(rect); },
  init(elId, initial) {
    const overlay = document.getElementById('c' + elId);
    if (!overlay) return;
    const box = overlay.querySelector('.rrs-crop-box');
    const size = overlay.querySelector('.rrs-crop-size');
    const MIN = 0.01;
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
```

- [ ] **Step 3: Remove the old SVG crop code**

In `src/rrs/ui/modals.py`, delete these now-unused pieces inside `open_frame_picker`:
- the `_crop_svg(rect)` function (currently ~lines 55–64)
- the `_render_crop(live=...)` function (~lines 66–67)
- the `_rect_from(p0, p1)` function (~lines 98–105)
- the `_on_mouse(e)` function (~lines 107–120)

Also remove the now-unused import on line 10: change

```python
from nicegui.events import KeyEventArguments, MouseEventArguments
```

to

```python
from nicegui.events import KeyEventArguments
```

In `_show` (~line 89) remove the `_render_crop()` call (the overlay renders itself client-side). The `state["drag"]` key is no longer used — remove it from the `state` dict initializer (~line 51).

- [ ] **Step 4: Update `_reset_crop` and `_render_label`, add the event handler**

`open_frame_picker` builds elements before the handlers can reference `overlay`, so define the overlay element first (Step 5) and reference it here. Replace the existing `_reset_crop` (~lines 122–125) with the version below, and add `_on_crop_event`. Keep `_render_label` as-is (it already renders the `crop W×H%` text from `state["crop"]`).

```python
    def _on_crop_event(e) -> None:
        detail = e.args
        if isinstance(detail, dict) and "detail" in detail:
            detail = detail["detail"]
        state["crop"] = crop_from_payload(detail)
        _render_label()

    def _reset_crop() -> None:
        state["crop"] = None
        ui.run_javascript(f"window.rrsCrop.set({overlay.id}, null)")
        _render_label()
```

- [ ] **Step 5: Restructure the DOM (wrapper + overlay) and wire the bridge**

Replace the `ui.interactive_image(...)` block (currently ~lines 154–162) with the wrapper + overlay structure. The interactive_image is kept only as the frame `<img>` (no mouse events, no SVG content):

```python
            initial = f"{file_url(out_path, data_dir)}" if out_path.exists() else ""
            with ui.element("div").classes("rrs-crop-wrap"):
                img = ui.interactive_image(initial, cross=False).classes("rrs-scrub-preview")
                with ui.element("div").classes("rrs-crop-overlay") as overlay:
                    with ui.element("div").classes("rrs-crop-box"):
                        for h in ("nw", "ne", "sw", "se"):
                            ui.element("div").classes("rrs-crop-handle").props(f'data-handle={h}')
                        ui.element("div").classes("rrs-crop-size")
            overlay.on("rrs-crop", _on_crop_event, args=["detail"])
            label = ui.html(
                f"frame {state['fn']} / scene {start}–{end}"
            ).classes("rrs-scrub-label")
            err_label = ui.html("").classes("rrs-scrub-err-row")
```

Note: `_reset_crop` and `_on_crop_event` are defined above (Step 4) but only *called* later, so referencing `overlay` inside them is fine — Python resolves the closure at call time, after `overlay` exists.

- [ ] **Step 6: Install + initialize the JS after the dialog opens**

At the end of `open_frame_picker`, the function currently ends with:

```python
    dialog.open()
    await _show(state["fn"])
```

Change it to install the JS module, seed the initial crop, then show the first frame:

```python
    dialog.open()
    ui.run_javascript(_CROP_JS)
    initial_crop = (
        "null"
        if state["crop"] is None
        else (
            f'{{"x":{state["crop"].x},"y":{state["crop"].y},'
            f'"w":{state["crop"].w},"h":{state["crop"].h}}}'
        )
    )
    ui.run_javascript(f"window.rrsCrop.init({overlay.id}, {initial_crop})")
    await _show(state["fn"])
```

- [ ] **Step 7: Run the existing + new test suite**

Run: `pytest tests/test_modals.py tests/test_main.py -v`
Expected: PASS. (`test_main.py` imports the UI layer; this confirms `modals.py` still imports cleanly after the edits.)

- [ ] **Step 8: Manual verification in the running app**

Start the app (`rrs`, or `python -m rrs.main`) with a processed job that has scenes, open a scene's frame picker, and confirm:
- The frame image fits the modal — no scrollbars on large frames, not tiny on small frames (F1).
- Drag on empty area draws a crop box; the live `W×H%` label updates smoothly with no lag.
- Dragging the box body moves it; it stays fully inside the frame.
- Dragging each corner resizes from that corner (opposite corner stays put); cursors match (`move` on body, resize on corners).
- A tiny click (no real drag) does **not** wipe an existing crop.
- Scrubbing frames (slider / ‹ › / arrows) keeps the crop box in place.
- RESET CROP clears the box.
- USE THIS FRAME persists the crop (reopen the picker → box reappears at the same place; the scene card reflects it).

If the crop box is offset from the image (overlay/image misalignment), the cause is the `interactive_image` root not shrink-wrapping its `<img>`. Inspect the rendered DOM in devtools and confirm `.rrs-crop-wrap` and `.rrs-scrub-preview` are both exactly the image's width; if the root has extra width, add `.rrs-scrub-preview .q-img, .rrs-scrub-preview > div { width: fit-content; }` (match the actual wrapper class NiceGUI emits) so the root collapses to the image box.

- [ ] **Step 9: Commit**

```bash
git add src/rrs/ui/modals.py src/rrs/ui/static/app.css
git commit -m "feat: smooth client-side crop overlay with move + corner resize (F2)"
```

---

## Task 4: F5 — center the URL input placeholder

The border/padding sits on the Quasar wrapper while the real `<input>` is nested, so the placeholder isn't vertically centered.

**Files:**
- Modify: `src/rrs/ui/static/app.css:161-166` (the `.rrs-input input` block)

- [ ] **Step 1: Update the nested-input CSS**

In `src/rrs/ui/static/app.css`, replace the `.rrs-input input` block (currently ~lines 161–166):

```css
.rrs-input input {
  background: transparent !important;
  color: var(--text) !important;
  font-family: inherit !important;
  font-size: 14px !important;
}
```

with:

```css
.rrs-input input {
  background: transparent !important;
  color: var(--text) !important;
  font-family: inherit !important;
  font-size: 14px !important;
  /* Center the placeholder/text vertically within our bordered box and align
     its height with the PROCESS VIDEO button. Left-aligned (it's a URL). */
  height: 28px !important;
  line-height: 28px !important;
  padding: 0 !important;
  text-align: left;
}
```

- [ ] **Step 2: Verify CSS is syntactically valid**

Run: `python -c "import pathlib; t = pathlib.Path('src/rrs/ui/static/app.css').read_text(); assert t.count('{') == t.count('}'), (t.count('{'), t.count('}'))"`
Expected: no output (braces balanced).

- [ ] **Step 3: Manual verification**

Reload the index page; the `https://...` placeholder is vertically centered in the input box and the field height lines up with the PROCESS VIDEO button.

- [ ] **Step 4: Commit**

```bash
git add src/rrs/ui/static/app.css
git commit -m "fix: vertically center source URL input placeholder (F5)"
```

---

## Final verification

- [ ] Run the full suite: `pytest` — expected: all pass (existing + `tests/test_modals.py`).
- [ ] Confirm all three TODO Group A items are covered: F1 (Task 2), F2 (Tasks 1+3), F5 (Task 4).
