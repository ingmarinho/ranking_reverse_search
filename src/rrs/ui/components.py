from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import ui

from rrs.pipeline.engines import get_engine
from rrs.store.db import Database, Frame, Scene


def html_button(label: str, on_click: Callable, classes: str = "rrs-btn"):
    """Render a plain HTML button styled by our CSS.

    NiceGUI's ``ui.button`` is a Quasar QBtn whose color classes (bg-primary /
    text-primary) resist our theme overrides, so action buttons use a raw
    ``<button>`` — the same element the engine chips already use successfully.
    NiceGUI handles arg count and awaits coroutine handlers, matching ui.button.
    """
    btn = ui.html(f'<button class="{classes}">{label}</button>')
    btn.on("click", on_click)
    return btn


def format_timecode(seconds: float) -> str:
    """Return `HH:MM:SS.mmm`."""
    millis = int(round((seconds - int(seconds)) * 1000))
    s_total = int(seconds)
    h, rem = divmod(s_total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{millis:03d}"


def file_url(path: str | Path, data_dir: Path) -> str:
    """Build a /_data/... URL for a file under `data_dir`. Appends ?v=<mtime> so
    that browsers refetch when the file on disk changes — protects against
    cross-job image caching when a path is reused."""
    p = Path(path).resolve()
    rel = p.relative_to(Path(data_dir).resolve())
    try:
        version = int(p.stat().st_mtime)
    except OSError:
        version = 0
    return f"/_data/{str(rel).replace(chr(92), '/')}?v={version}"


def render_scene_card(
    db: Database,
    data_dir: Path,
    scene: Scene,
    total_scenes: int,
    aspect: tuple[int, int],
    on_open_frame_picker: Callable[[Scene], None],
    on_search_click: Callable[[Scene, str], None],
    on_download: Callable[[int, str], Awaitable[str]],
    on_open_folder: Callable[[], None],
    enabled_ids: list[str],
) -> None:
    """Render one scene card.

    `aspect` is (width, height) of the source video, used for thumbnail sizing.
    `on_download(scene_id, url)` downloads the source clip and returns its filename.
    `on_open_folder()` reveals the job's downloads folder.
    `enabled_ids` is the enabled-engine id list (read once by the caller).
    """
    selected = [f for f in db.list_frames(scene.id) if f.is_selected]

    with ui.element("div").classes("rrs-scene-card"):
        delta = scene.end_sec - scene.start_sec
        ui.html(
            f'<div class="rrs-scene-head">'
            f'  <span class="rrs-scene-idx">{scene.idx + 1:02d} / {total_scenes:02d}</span>'
            f'  <span class="rrs-scene-range rrs-timecode">'
            f"    {format_timecode(scene.start_sec)} — {format_timecode(scene.end_sec)}"
            f"  </span>"
            f'  <span class="rrs-scene-delta rrs-timecode">Δ {delta:.2f}s</span>'
            f"</div>"
        )
        # Two columns: thumbnail on the left, engines + download stacked on the
        # right so they fill the space beside the thumbnail (no dead space).
        with ui.element("div").classes("rrs-scene-body"):
            _render_frame_strip(scene, selected, data_dir, aspect, on_open_frame_picker)
            with ui.element("div").classes("rrs-scene-main"):
                _render_engine_row(scene, enabled_ids, on_search_click)
                _render_download_row(db, scene, on_download, on_open_folder)


def _render_frame_strip(
    scene: Scene,
    selected: list[Frame],
    data_dir: Path,
    aspect: tuple[int, int],
    on_open_frame_picker: Callable[[Scene], None],
) -> None:
    """The scene's single selected frame; clicking it opens the scrubber picker."""
    w, h = aspect
    aspect_style = f"aspect-ratio: {w} / {h}"
    with ui.element("div").classes("rrs-frame-strip"):
        if selected:
            f = selected[0]
            url = file_url(f.path, data_dir)
            # Full frame thumbnail; if a crop is set, mark the region with an overlay.
            overlay = ""
            if f.crop is not None:
                c = f.crop
                overlay = (
                    f'<div class="rrs-crop-overlay" style="'
                    f"left:{c.x * 100:.2f}%;top:{c.y * 100:.2f}%;"
                    f'width:{c.w * 100:.2f}%;height:{c.h * 100:.2f}%"></div>'
                )
            frame = ui.element("div").classes("rrs-frame selected").style(aspect_style)
            with frame:
                ui.html(f'<img src="{url}" alt="frame {f.frame_number}">{overlay}')
            frame.on("click", lambda _, s=scene: on_open_frame_picker(s))
        else:
            add = ui.html(f'<div class="rrs-frame rrs-frame-add" style="{aspect_style}">+</div>')
            add.on("click", lambda _, s=scene: on_open_frame_picker(s))


def _render_engine_row(
    scene: Scene,
    enabled_ids: list[str],
    on_search_click: Callable[[Scene, str], None],
) -> None:
    """One engine row per scene. Clicking an engine searches the selected frame."""
    with ui.element("div").classes("rrs-engines"):
        for eid in enabled_ids:
            engine = get_engine(eid)
            if engine is None:
                continue
            chip = ui.html(
                f'<button class="rrs-btn rrs-engine-chip" data-status="{engine.status}">'
                f"{engine.name.upper()}"
                f"</button>"
            )
            chip.on("click", lambda _, s=scene, e=eid: on_search_click(s, e))


def _render_download_row(
    db: Database,
    scene: Scene,
    on_download: Callable[[int, str], Awaitable[str]],
    on_open_folder: Callable[[], None],
) -> None:
    """Per-card source-url input + download/open buttons + a status line below."""
    src = db.get_source(scene.id)
    with ui.element("div").classes("rrs-download"):

        async def _go(_=None) -> None:
            url = inp.value.strip()
            if not url:
                return
            status.set_content('<span class="rrs-download-busy">downloading…</span>')
            try:
                name = await on_download(scene.id, url)
            except Exception as exc:  # noqa: BLE001 — surface any failure inline
                msg = html.escape(str(exc))
                status.set_content(
                    f'<span class="rrs-download-err" title="{msg}">✗ failed: {msg}</span>'
                )
                return
            status.set_content(_download_status_html(name))

        with ui.element("div").classes("rrs-download-row"):
            inp = ui.input(value=(src.url if src else ""), placeholder="source url").classes(
                "rrs-input"
            )
            html_button("DOWNLOAD", _go)
            html_button("OPEN FOLDER", on_open_folder)

        status = ui.html(_download_status_html(src.path if src else None)).classes(
            "rrs-download-status"
        )


def _download_status_html(path: str | None) -> str:
    if not path:
        return ""
    name = html.escape(Path(path).name)
    full = html.escape(path)
    return f'<span class="rrs-download-done" title="{full}">✓ downloaded: {name}</span>'


def render_extra_downloader(on_download: Callable[[str], Awaitable[str]]) -> None:
    """Bottom-of-page box to download any extra clip into the active job's folder.

    `on_download(url)` downloads the clip and returns its saved filename, or raises.
    """
    with ui.element("div").classes("rrs-download rrs-extra-download"):
        ui.html('<div class="rrs-label">Download an extra clip</div>')

        async def _go(_=None) -> None:
            url = inp.value.strip()
            if not url:
                return
            status.set_content('<span class="rrs-download-busy">downloading…</span>')
            try:
                name = await on_download(url)
            except Exception as exc:  # noqa: BLE001 — surface any failure inline
                msg = html.escape(str(exc))
                status.set_content(
                    f'<span class="rrs-download-err" title="{msg}">✗ failed: {msg}</span>'
                )
                return
            inp.value = ""
            status.set_content(_download_status_html(name))

        with ui.element("div").classes("rrs-download-row"):
            inp = ui.input(placeholder="clip url").classes("rrs-input")
            html_button("DOWNLOAD", _go)

        status = ui.html("").classes("rrs-download-status")
