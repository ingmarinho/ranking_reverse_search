# imgbb API key & onboarding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users set/change the imgbb API key inside the web app, gate the
whole app behind having a key, and persist it on disk in the settings table.

**Architecture:** `Config` stays frozen with `imgbb_api_key` as the env fallback.
The key is stored in the `settings` table and all reads go through a resolver
`effective_imgbb_key(db, cfg)` that prefers the DB value. An onboarding gate
renders before the wizard when no key is available; a settings dialog lets a
non-technical user view (masked) / change / clear the key afterward. Keys are
validated on save with a self-expiring 1×1 test upload.

**Tech Stack:** Python 3.11+, NiceGUI 3.x, httpx, sqlite, pytest + respx.

Spec: `docs/superpowers/specs/2026-06-16-imgbb-key-onboarding-design.md`

## File Structure

- **Modify** `src/rrs/store/db.py` — add `SETTINGS_IMGBB_KEY` constant and
  `get_imgbb_key` / `set_imgbb_key` / `clear_imgbb_key` over the existing
  generic settings methods.
- **Modify** `src/rrs/pipeline/hosting.py` — add the 1×1 test-PNG constant,
  `validate_imgbb_key`, and the `effective_imgbb_key(db, cfg)` resolver
  (duck-typed, no runtime db/config import — stays NiceGUI-free for testing).
- **Create** `src/rrs/ui/onboarding.py` — the onboarding gate render, the
  settings dialog, and the `_mask_key` helper.
- **Modify** `src/rrs/ui/pages.py` — gate check in `_render_wizard`, settings
  button in the header, swap the three `cfg.imgbb_api_key` reads for the
  resolver, drop the startup "not set" banner.
- **Create** `tests/test_onboarding.py` — `_mask_key` unit test.
- **Modify** `tests/test_db.py`, `tests/test_hosting.py` — new behavior tests.

---

### Task 1: DB key accessors

**Files:**
- Modify: `src/rrs/store/db.py` (settings section, around `:246-258`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_imgbb_key_set_get_clear(db: Database):
    assert db.get_imgbb_key() is None
    db.set_imgbb_key("  key123  ")
    assert db.get_imgbb_key() == "key123"  # stripped
    db.clear_imgbb_key()
    assert db.get_imgbb_key() is None


def test_imgbb_key_empty_reads_as_none(db: Database):
    db.set_setting("imgbb_api_key", "   ")
    assert db.get_imgbb_key() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -k imgbb_key -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'get_imgbb_key'`

- [ ] **Step 3: Write minimal implementation**

In `src/rrs/store/db.py`, add a module-level constant near the top (after imports):

```python
SETTINGS_IMGBB_KEY = "imgbb_api_key"
```

In the `# ---- settings ----` section, after `set_setting`:

```python
def get_imgbb_key(self) -> str | None:
    value = (self.get_setting(SETTINGS_IMGBB_KEY) or "").strip()
    return value or None

def set_imgbb_key(self, key: str) -> None:
    self.set_setting(SETTINGS_IMGBB_KEY, key.strip())

def clear_imgbb_key(self) -> None:
    self._conn.execute("DELETE FROM settings WHERE key = ?", (SETTINGS_IMGBB_KEY,))
    self._conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -k imgbb_key -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/rrs/store/db.py tests/test_db.py
git commit -m "feat: imgbb key accessors on Database"
```

---

### Task 2: Key validation in hosting.py

**Files:**
- Modify: `src/rrs/pipeline/hosting.py`
- Test: `tests/test_hosting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hosting.py` (imports `validate_imgbb_key` — update the import
line to `from rrs.pipeline.hosting import ImgbbError, upload_image, validate_imgbb_key`):

```python
@respx.mock
def test_validate_imgbb_key_success_sends_expiration_and_deletes():
    upload = respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"url": "https://i.ibb.co/x.png",
                           "delete_url": "https://ibb.co/del/abc"}},
        )
    )
    delete = respx.get("https://ibb.co/del/abc").mock(return_value=httpx.Response(200))
    validate_imgbb_key("good")  # must not raise
    assert "expiration=60" in str(upload.calls.last.request.url)
    assert delete.called


@respx.mock
def test_validate_imgbb_key_invalid_raises():
    respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(400, text="invalid api key")
    )
    with pytest.raises(ImgbbError):
        validate_imgbb_key("bad")


@respx.mock
def test_validate_imgbb_key_network_error_raises():
    respx.post("https://api.imgbb.com/1/upload").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ImgbbError):
        validate_imgbb_key("any")


@respx.mock
def test_validate_imgbb_key_delete_failure_is_swallowed():
    respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"url": "https://i.ibb.co/x.png",
                           "delete_url": "https://ibb.co/del/abc"}},
        )
    )
    respx.get("https://ibb.co/del/abc").mock(side_effect=httpx.ConnectError("nope"))
    validate_imgbb_key("good")  # delete failure must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hosting.py -k validate -v`
Expected: FAIL with `ImportError: cannot import name 'validate_imgbb_key'`

- [ ] **Step 3: Write minimal implementation**

In `src/rrs/pipeline/hosting.py`, add near the top (after imports):

```python
# A 1x1 transparent PNG, base64-encoded. Used as a throwaway probe to validate an
# imgbb API key without uploading anything meaningful.
_TEST_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
```

Add this function:

```python
def validate_imgbb_key(api_key: str, timeout: float = 15.0) -> None:
    """Validate an imgbb key by uploading a self-expiring 1x1 probe image.

    Raises ImgbbError if imgbb rejects the key (or the request fails). On success
    the probe is deleted best-effort; expiration=60 guarantees cleanup regardless.
    """
    try:
        resp = httpx.post(
            "https://api.imgbb.com/1/upload",
            params={"key": api_key, "expiration": 60},
            data={"image": _TEST_PNG_B64},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise ImgbbError(f"imgbb request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise ImgbbError(f"imgbb {resp.status_code}: {resp.text[:200]}")

    try:
        delete_url = resp.json()["data"].get("delete_url")
    except (KeyError, ValueError) as exc:
        raise ImgbbError(f"imgbb malformed response: {resp.text[:200]}") from exc

    if delete_url:
        try:
            httpx.get(delete_url, timeout=timeout)
        except httpx.HTTPError:
            pass  # best-effort; expiration=60 is the guaranteed cleanup
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hosting.py -k validate -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/hosting.py tests/test_hosting.py
git commit -m "feat: validate_imgbb_key with self-expiring probe upload"
```

---

### Task 3: effective_imgbb_key resolver

**Files:**
- Modify: `src/rrs/pipeline/hosting.py`
- Test: `tests/test_hosting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hosting.py` (add imports at top of file:
`from rrs.config import Config`, `from rrs.store.db import open_db`,
`from rrs.pipeline.hosting import effective_imgbb_key`):

```python
def _cfg(env_key):
    return Config(data_dir=Path("."), port=8080, scene_threshold=27.0,
                  imgbb_api_key=env_key, has_deno=False)


def test_effective_imgbb_key_prefers_db_over_env():
    db = open_db(":memory:")
    db.set_imgbb_key("db_key")
    assert effective_imgbb_key(db, _cfg("env_key")) == "db_key"


def test_effective_imgbb_key_falls_back_to_env():
    db = open_db(":memory:")
    assert effective_imgbb_key(db, _cfg("env_key")) == "env_key"


def test_effective_imgbb_key_none_when_unset():
    db = open_db(":memory:")
    assert effective_imgbb_key(db, _cfg(None)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hosting.py -k effective -v`
Expected: FAIL with `ImportError: cannot import name 'effective_imgbb_key'`

- [ ] **Step 3: Write minimal implementation**

In `src/rrs/pipeline/hosting.py`, add a typing guard at the top (under the
existing `from __future__ import annotations`):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rrs.config import Config
    from rrs.store.db import Database
```

Add the resolver (duck-typed at runtime — no runtime import of db/config, so no
import cycle):

```python
def effective_imgbb_key(db: "Database", cfg: "Config") -> str | None:
    """The key actually in effect: the in-app (DB) value wins over the env var."""
    return db.get_imgbb_key() or cfg.imgbb_api_key
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hosting.py -k effective -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/hosting.py tests/test_hosting.py
git commit -m "feat: effective_imgbb_key resolver (DB overrides env)"
```

---

### Task 4: Onboarding gate & settings dialog module

**Files:**
- Create: `src/rrs/ui/onboarding.py`
- Test: `tests/test_onboarding.py`

The rendering functions are thin NiceGUI wrappers; the testable logic is the
`_mask_key` helper. Gate/dialog behavior is verified manually in Task 5.

- [ ] **Step 1: Write the failing test**

Create `tests/test_onboarding.py`:

```python
from __future__ import annotations

from rrs.ui.onboarding import _mask_key


def test_mask_key_shows_last_four():
    assert _mask_key("abcdef1234") == "••••••1234"


def test_mask_key_short_key_fully_masked():
    assert _mask_key("abc") == "•••"


def test_mask_key_empty():
    assert _mask_key("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_onboarding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rrs.ui.onboarding'`

- [ ] **Step 3: Write minimal implementation**

Create `src/rrs/ui/onboarding.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import Callable

from nicegui import ui

from rrs.config import Config
from rrs.pipeline.hosting import ImgbbError, effective_imgbb_key, validate_imgbb_key
from rrs.store.db import Database

_IMGBB_KEY_URL = "https://api.imgbb.com/"


def _mask_key(key: str) -> str:
    """Mask all but the last 4 chars: 'abcdef1234' -> '••••••1234'."""
    if len(key) <= 4:
        return "•" * len(key)
    return "•" * (len(key) - 4) + key[-4:]


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
            key_input = ui.input(placeholder="Paste your imgbb API key").props(
                "type=password"
            ).classes("rrs-input").style("flex:1")

        async def on_save() -> None:
            await _save_key(db, key_input.value, on_ready)

        from rrs.ui.components import html_button

        html_button("SAVE & CONTINUE", on_save, classes="rrs-btn rrs-btn-primary")


def open_imgbb_settings(db: Database, cfg: Config, on_change: Callable[[], None]) -> None:
    """Dialog to view (masked) / change / clear the imgbb key."""
    from rrs.ui.components import html_button

    current = effective_imgbb_key(db, cfg)
    from_env = db.get_imgbb_key() is None and current is not None

    with ui.dialog() as dialog, ui.element("div").classes("rrs-modal-backdrop"):
        with ui.element("div").classes("rrs-wrap"):
            ui.html('<div class="rrs-title">imgbb API key</div>')
            if current:
                label = _mask_key(current) + (" (set via environment)" if from_env else "")
                ui.html(f'<div class="rrs-meta" style="margin-bottom:8px">Current: {label}</div>')
            key_input = ui.input(placeholder="Enter a new key to replace it").props(
                "type=password"
            ).classes("rrs-input").style("flex:1")

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_onboarding.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/rrs/ui/onboarding.py tests/test_onboarding.py
git commit -m "feat: onboarding gate + imgbb settings dialog"
```

---

### Task 5: Wire gate, settings button, and resolver into pages.py

**Files:**
- Modify: `src/rrs/ui/pages.py` (`:43-52`, `:121-133`, `:165-166`, `:182-208`)
- Test: full suite + manual app run

- [ ] **Step 1: Add the gate check to `_render_wizard`**

In `src/rrs/ui/pages.py`, add the import near the others (around `:22`):

```python
from rrs.pipeline.hosting import ImgbbError, effective_imgbb_key, upload_image
from rrs.ui.onboarding import open_imgbb_settings, render_onboarding
```

(The first line replaces the existing
`from rrs.pipeline.hosting import ImgbbError, upload_image`.)

Change `_render_wizard` (`:42-52`) to gate before rendering anything else:

```python
@ui.refreshable
def _render_wizard(db: Database, cfg: Config) -> None:
    job = _find_active_job(db)
    # Gate the whole app behind having a key. render_onboarding opens its own
    # rrs-wrap, so return before opening ours to avoid double-nesting.
    if effective_imgbb_key(db, cfg) is None:
        render_onboarding(db, cfg, on_ready=_render_wizard.refresh)
        return
    with ui.element("div").classes("rrs-wrap"):
        with ui.row().classes("w-full items-center").style("justify-content:space-between"):
            ui.html('<div class="rrs-title">Ranking Reverse Search</div>')
            html_button(
                "API KEY",
                lambda: open_imgbb_settings(db, cfg, on_change=_render_wizard.refresh),
                classes="rrs-btn",
            )
        if job is None:
            _render_url_input(db, cfg)
            return
        _render_for_status(db, cfg, job)
```

- [ ] **Step 2: Remove the obsolete startup banner and swap reads**

In `_render_scene_list` (`:127-128`), delete these two lines (the gate now
guarantees a key):

```python
    if cfg.imgbb_api_key is None:
        ui.html('<div class="rrs-error">IMGBB_API_KEY not set — engine buttons disabled</div>')
```

In `_do_reverse_search` (`:165-166`), change the guard to use the resolver:

```python
    if effective_imgbb_key(db, cfg) is None:
        ui.notify("imgbb key not set", type="negative")
        return
```

In `_engine_url_for_frame` (`:203`), change the upload call to source the key
from the resolver:

```python
            key = effective_imgbb_key(db, cfg)
            image_url = await asyncio.to_thread(upload_image, upload_path, key)
```

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: PASS — all prior tests plus the new ones (no regressions).

- [ ] **Step 4: Manual verification**

Run the app with **no** key configured:

```bash
env -u IMGBB_API_KEY DATA_DIR=/tmp/rrs-manual rrs
```

Verify in the browser (http://localhost:8080):
1. The onboarding gate appears instead of the URL input.
2. Entering a bad key shows "That key didn't work" and stays on the gate.
3. Entering a valid key advances to the wizard (URL input visible).
4. Restarting the app (`rrs` again, same DATA_DIR) skips the gate — key persisted.
5. The "API KEY" button opens the dialog; the current key shows masked; CLEAR
   returns to the gate on next render.

Stop the app (Ctrl-C) when done.

- [ ] **Step 5: Commit**

```bash
git add src/rrs/ui/pages.py
git commit -m "feat: gate app behind imgbb key, add settings button, route key reads through resolver"
```

---

## Self-Review notes

- **Spec coverage:** in-app set (Task 4/5), easier to use / onboarding gate
  (Task 5 step 1), unusable without key (gate returns early), persistence (Task 1
  DB), edit-later (settings dialog Task 4), live validation + delete (Task 2),
  env precedence (Task 3). All spec sections map to a task.
- **Type consistency:** `validate_imgbb_key`, `effective_imgbb_key`,
  `get_imgbb_key`/`set_imgbb_key`/`clear_imgbb_key`, `render_onboarding`,
  `open_imgbb_settings`, `_mask_key`, `_save_key` are referenced with the same
  signatures across tasks.
- **No placeholders:** every code step shows complete code.
```
