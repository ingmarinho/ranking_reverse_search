# Frame-picker & cropping UX — design

Date: 2026-06-16
Status: approved, ready for implementation plan
Scope: TODO Group A — items F1, F2, F5.

## Goal

Make the frame picker's cropping interaction smooth and capable (move + resize),
fix the frame image so it fits its container, and fix the source-URL input's
placeholder alignment. Pure UI/UX work in `ui/modals.py`, `ui/pages.py`, and
`ui/static/app.css`. No changes to the job/scene/frame data model or the commit
path.

## Items

- **F1** — frame-picker image scaling: the preview image renders at native pixel
  resolution, so large frames overflow with scrollbars and small frames float
  tiny in the middle.
- **F2** — cropping: today only supports drawing a fresh box
  (mousedown → drag → mouseup), with a server round-trip on every `mousemove`
  (jank). Want: move an existing box, resize it from its corners, and smooth
  interaction.
- **F5** — source URL input: border/padding sits on the Quasar `q-field` wrapper
  while the real `<input>` is nested, so the placeholder is not vertically
  centered in the box.

Out of scope (separate TODO groups): download management (Group B), imgbb key /
onboarding (Group C), bugs (Group D).

## Decisions

- **Crop interaction set:** move + **corner** handles only (4 corners, no
  mid-edge handles), **freeform** aspect ratio, no aspect-ratio lock.
- **Approach:** custom client-side overlay in vanilla JS (dependency-free), not a
  JS cropper library and not server-side `interactive_image` mouse events. All
  dragging/resizing happens in the browser; only the final rect is sent to the
  server. Chosen because it fixes smoothness at the root (no websocket
  round-trips mid-drag, including over the cloudflared tunnel), adds zero
  dependencies, matches the existing terminal/SVG aesthetic, and ships exactly
  the needed feature set.
- **URL field text alignment (F5):** left-aligned (it is a URL field).

## F2 — Architecture

### DOM structure

Keep `ui.interactive_image` for the frame so the existing scrub plumbing
(`img.set_source(...)` in `_show`) is untouched, but stop using its mouse events
and SVG content for cropping. Wrap it in a `position: relative` container that
shrink-wraps the displayed image, with a sibling crop-overlay layer absolutely
positioned over it:

```
.rrs-scrub-preview (position: relative; width: fit-content; max-width: 100%)
 ├─ <img>                       ← frame; fit via F1 CSS; defines the box size
 └─ .rrs-crop-overlay (position:absolute; inset:0)
     └─ .rrs-crop-box (left/top/width/height in %)
         ├─ corner handle ×4    (nw, ne, sw, se)
```

Because the container shrink-wraps the image, a crop box positioned in
**percentages** maps 1:1 to the normalized `CropRect` (`x, y, w, h` in [0,1]) —
no coordinate conversion drift, and no dependence on
`get_video_dimensions`-derived pixel scaling for the overlay.

### Where interaction lives

All pointer dragging/resizing happens client-side in vanilla JS (updates CSS
`left/top/width/height`, no network mid-drag → smooth). Three modes, dispatched
on `pointerdown`:

- **body of box** → move: record pointer-to-box offset; on `pointermove` set
  `left/top = clamp(pointer − offset)`, width/height fixed, box kept fully inside
  [0,1].
- **corner handle** → resize: the opposite corner is the fixed anchor; the
  dragged corner follows the pointer; recompute `x,y,w,h` from the two corners
  (same min/max logic as the current `_rect_from`). Enforce `w,h ≥ _MIN_CROP`;
  if the pointer crosses the anchor, clamp (no negative size, no flip).
- **empty area** → draw a new box: identical to corner-resize with the down-point
  as the anchor.

`setPointerCapture` keeps a drag tracking when it leaves the image;
`pointercancel` aborts cleanly. `pointerup` normalizes + clamps the rect and is
the only moment the client talks to the server.

### Python ↔ JS bridge (element-scoped, cleans up with the dialog)

- **JS → Python:** on `pointerup`, dispatch a `CustomEvent` on the overlay
  element; the server listens via `overlay.on('rrs-crop', handler)` and updates
  the authoritative `state["crop"]`. Element-scoped `.on(...)` (not a global
  `ui.on`) so the handler is torn down with the dialog and does not accumulate
  across opens.
- **Python → JS:** "RESET CROP" and initial-crop seeding call a small per-element
  JS API (`window.rrsCrop[id].set(rect | null)`) via `ui.run_javascript`.

### Preserved behaviors

- `state["crop"]` stays authoritative in Python; `_commit()` and the DB writes
  (`set_frame_image`, `set_frame_crop`) are unchanged.
- A sub-`_MIN_CROP` drag is treated as a stray click and does **not** wipe the
  existing crop (matches current `modals.py` line ~117).
- Crop persists across scrubbing frames (overlay is a sibling, untouched by
  `img.set_source`).
- Cancel / Esc / backdrop still revert; crop only commits via USE THIS FRAME.
- The live `crop W×H%` label updates in JS during drag for smoothness; Python
  re-syncs the authoritative value on the `rrs-crop` event.

### Visual

- Corner handles: small (~10px) squares with `--accent` border, matching the
  terminal aesthetic.
- Box: current translucent-white fill (`rgba(255,255,255,0.12)`) + white,
  non-scaling stroke look.
- Cursors reflect mode: `move` on the body, `nwse-resize`/`nesw-resize` on
  corners, `crosshair` on empty area.

## F1 — Image scaling

Constrain the frame image to fit its container while preserving aspect ratio:

```css
.rrs-scrub-preview { width: fit-content; max-width: 100%; margin: 0 auto; }
.rrs-scrub-preview img { max-width: 100%; max-height: 60vh; width: auto; height: auto; display: block; }
```

The container shrink-wraps the displayed image — no native-resolution overflow or
scrollbars, no tiny floating image — and the crop overlay stays pixel-aligned.
Drop the existing `overflow: auto` on `.rrs-scrub-preview`.

## F5 — URL input placeholder

The border/padding lives on the Quasar wrapper while the real `<input>` is nested
(`app.css` ~line 161). Give the native input a consistent line-height/padding so
the placeholder vertically centers within the box and the field height aligns
with the PROCESS VIDEO button. Targeted CSS on `.rrs-input input`; no structural
change. Text left-aligned.

## Testing

- **Python-side (unit-tested):** extract the rect validation/clamp/min-size logic
  into a pure helper, e.g. `crop_from_payload(payload) -> CropRect | None`, used
  by the `rrs-crop` event handler. Test: clamping to [0,1], min-size rejection,
  and that a rejected/empty payload leaves the existing crop unchanged. The
  `_commit` path follows existing test patterns.
- **JS / CSS (manual, via Playwright / Chrome DevTools MCP):** drag-move,
  corner-resize, sub-min stray click preserves crop, crop persists across
  scrubbing, RESET CROP clears, F1 fit at both large and small frames, F5
  placeholder alignment.

## Files touched

- `src/rrs/ui/modals.py` — replace `_on_mouse`/SVG-based cropping with the
  overlay + JS bridge; add the `crop_from_payload` helper and the `rrs-crop`
  handler; wire RESET CROP / initial seeding to the JS API.
- `src/rrs/ui/static/app.css` — F1 preview/img sizing, crop overlay + handle
  styles, F5 input fix.
- `src/rrs/ui/pages.py` — only if the URL input needs a structural tweak; expected
  to be CSS-only.
- `tests/` — unit tests for `crop_from_payload`.
