from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from nicegui import ui

from rrs.pipeline.engines import ALL_ENGINES, get_engine
from rrs.store.db import Database, Frame, Scene


def format_timecode(seconds: float) -> str:
    """Return `HH:MM:SS.mmm`."""
    millis = int(round((seconds - int(seconds)) * 1000))
    s_total = int(seconds)
    h, rem = divmod(s_total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{millis:03d}"


def file_url(path: str | Path, data_dir: Path) -> str:
    """Build a /_data/... URL for a file under `data_dir`."""
    rel = Path(path).resolve().relative_to(Path(data_dir).resolve())
    return "/_data/" + str(rel).replace("\\", "/")


def render_scene_card(
    db: Database,
    data_dir: Path,
    scene: Scene,
    total_scenes: int,
    on_open_frame_picker: Callable[[Scene], None],
    on_open_trim: Callable[[Scene], None],
    on_search_click: Callable[[Frame, str], None],
) -> None:
    """Render one scene card. Caller passes click handlers so this stays UI-only."""
    frames = db.list_frames(scene.id)
    selected = [f for f in frames if f.is_selected] or frames[:1]
    enabled_ids = json.loads(db.get_setting("enabled_engines") or "[]")

    with ui.element("div").classes("rrs-scene-card"):
        delta = scene.end_sec - scene.start_sec
        ui.html(
            f'<div class="rrs-scene-head">'
            f'  <span class="rrs-scene-idx">{scene.idx + 1:02d} / {total_scenes:02d}</span>'
            f'  <span class="rrs-scene-range rrs-timecode">'
            f'    {format_timecode(scene.start_sec)} — {format_timecode(scene.end_sec)}'
            f'  </span>'
            f'  <span class="rrs-scene-delta rrs-timecode">Δ {delta:.2f}s</span>'
            f'</div>'
        )
        _render_frame_strip(scene, selected, frames, data_dir, on_open_frame_picker)
        for f in selected:
            _render_engine_row(f, enabled_ids, on_search_click)
        _render_source_row(db, data_dir, scene, on_open_trim)


def _render_frame_strip(
    scene: Scene,
    selected: list[Frame],
    frames: list[Frame],
    data_dir: Path,
    on_open_frame_picker: Callable[[Scene], None],
) -> None:
    with ui.element("div").classes("rrs-frame-strip"):
        for ordinal, f in enumerate([fr for fr in frames if fr.is_selected]):
            sel_class = " selected"
            url = file_url(f.path, data_dir)
            html = (
                f'<div class="rrs-frame{sel_class}">'
                f'  <span class="rrs-ord">{ordinal+1:02d}</span>'
                f'  <img src="{url}" alt="frame {f.frame_number}">'
                f'</div>'
            )
            container = ui.html(html)
            container.on("click", lambda _, s=scene: on_open_frame_picker(s))
        add = ui.html('<div class="rrs-frame rrs-frame-add">+</div>')
        add.on("click", lambda _, s=scene: on_open_frame_picker(s))


def _render_engine_row(
    frame: Frame, enabled_ids: list[str],
    on_search_click: Callable[[Frame, str], None],
) -> None:
    with ui.element("div").classes("rrs-engines"):
        for eid in enabled_ids:
            engine = get_engine(eid)
            if engine is None:
                continue
            chip = ui.html(
                f'<button class="rrs-btn rrs-engine-chip" data-status="{engine.status}">'
                f'{engine.name.upper()}'
                f'</button>'
            )
            chip.on("click", lambda _, f=frame, e=eid: on_search_click(f, e))


def _render_source_row(
    db: Database, data_dir: Path, scene: Scene,
    on_open_trim: Callable[[Scene], None],
) -> None:
    src = db.get_source(scene.id)
    initial = src.url if src else ""
    with ui.element("div").classes("rrs-source-row"):
        inp = ui.input(value=initial, placeholder="source url").classes("rrs-input")

        async def on_download() -> None:
            from rrs.ui.pages import download_source_for_scene
            url = inp.value.strip()
            if not url:
                return
            await download_source_for_scene(db, data_dir, scene.id, url)
            ui.navigate.reload()

        ui.button("DOWNLOAD", on_click=on_download).classes("rrs-btn")
    src = db.get_source(scene.id)
    if src and src.path:
        with ui.element("div").classes("rrs-status-line"):
            ui.html(f'<span>source: {Path(src.path).name}</span>')
            ui.button("TRIM CLIP", on_click=lambda s=scene: on_open_trim(s)).classes("rrs-btn")
            if src.clip_path:
                clip_url = file_url(src.clip_path, data_dir)
                ui.html(f'<a class="rrs-btn" href="{clip_url}" target="_blank">OPEN CLIP</a>')
