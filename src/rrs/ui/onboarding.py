from __future__ import annotations

import asyncio
from collections.abc import Callable

from nicegui import ui

from rrs.config import Config
from rrs.pipeline.hosting import ImgbbError, effective_imgbb_key, validate_imgbb_key
from rrs.store.db import Database
from rrs.ui.components import html_button

_IMGBB_KEY_URL = "https://api.imgbb.com/"


def _mask_key(key: str) -> str:
    """Mask all but the last 4 chars: 'abcdef1234' -> '••••••1234'."""
    if len(key) <= 4:
        return "•" * len(key)
    return "•" * (len(key) - 4) + key[-4:]


def _key_input(placeholder: str):
    """A masked, full-width text field for entering an imgbb key."""
    return (
        ui.input(placeholder=placeholder)
        .props("type=password")
        .classes("rrs-input")
        .style("flex:1")
    )


async def _save_key(db: Database, raw: str, on_done: Callable[[], None]) -> bool:
    """Validate and persist a key. Returns True on success, notifies on failure."""
    key = raw.strip()
    if not key:
        ui.notify("Enter a key first", type="warning")
        return False
    try:
        await asyncio.to_thread(validate_imgbb_key, key)
    except ImgbbError:
        ui.notify("That key didn't work — check it and try again", type="negative")
        return False
    db.set_imgbb_key(key)
    on_done()
    return True


def render_onboarding(db: Database, cfg: Config, on_ready: Callable[[], None]) -> None:
    """Full-screen gate shown when no imgbb key is in effect."""
    with ui.element("div").classes("rrs-wrap"):
        ui.html('<div class="rrs-title">Welcome to Ranking Reverse Search</div>')
        ui.html(
            '<div class="rrs-label" style="margin-bottom:8px">'
            "This app needs a free imgbb API key to host frames for reverse search.</div>"
        )
        ui.html(
            f'<div class="rrs-meta" style="margin-bottom:12px">'
            f'Get one at <a href="{_IMGBB_KEY_URL}" target="_blank">{_IMGBB_KEY_URL}</a> '
            "(sign in → About → Get API key).</div>"
        )
        with ui.row().classes("w-full"):
            key_input = _key_input("Paste your imgbb API key")

        async def on_save() -> None:
            await _save_key(db, key_input.value, on_ready)

        html_button("SAVE & CONTINUE", on_save, classes="rrs-btn rrs-btn-primary")


def open_imgbb_settings(db: Database, cfg: Config, on_change: Callable[[], None]) -> None:
    """Dialog to view (masked) / change / clear the imgbb key."""
    current = effective_imgbb_key(db, cfg)
    from_env = db.get_imgbb_key() is None and current is not None

    with ui.dialog() as dialog, ui.element("div").classes("rrs-modal-backdrop"):
        with ui.element("div").classes("rrs-wrap"):
            ui.html('<div class="rrs-title">imgbb API key</div>')
            if current:
                label = _mask_key(current) + (" (set via environment)" if from_env else "")
                ui.html(f'<div class="rrs-meta" style="margin-bottom:8px">Current: {label}</div>')
            key_input = _key_input("Enter a new key to replace it")

            async def on_save() -> None:
                if await _save_key(db, key_input.value, on_change):
                    dialog.close()

            def on_clear() -> None:
                db.clear_imgbb_key()
                dialog.close()
                on_change()

            with ui.row():
                html_button("SAVE", on_save, classes="rrs-btn rrs-btn-primary")
                html_button("CLEAR", on_clear, classes="rrs-btn")
    dialog.open()
