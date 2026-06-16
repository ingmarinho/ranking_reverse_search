# imgbb API key & onboarding (TODO Group C / F4)

**Status:** Design approved, ready for implementation plan
**Date:** 2026-06-16
**Branch:** `feat/group-c-imgbb-onboarding`

## Problem

The imgbb API key is required for reverse search (frames are uploaded to imgbb
to get a public URL). Today it can only be supplied via the `IMGBB_API_KEY`
environment variable, read once at startup into a frozen `Config`. A
non-technical tester has no way to provide it, and the app silently degrades to
a banner ("IMGBB_API_KEY not set — engine buttons disabled") while still letting
them wander through the wizard.

Group C / F4 wants to:

1. Let the user set the key inside the web app.
2. Make it easier to use.
3. Make the app unusable without a key.
4. Persist the key (chosen: on disk, in the existing settings store).
5. (Added constraint) Let a non-technical user view/change the key later.

## Decisions (from brainstorming)

- **Storage:** the `settings` table in `app.db` (same pattern as
  `enabled_engines`). Not browser storage, not a bespoke file.
- **Gating:** a full onboarding gate — the wizard does not render until a key
  is available.
- **Edit-later:** a persistent settings affordance so the key can be
  viewed (masked) / changed / cleared anytime.
- **Validation:** live validation via a test upload on save; delete the test
  image immediately (with `expiration=60` as the guaranteed fallback cleanup).
- **Env precedence:** the in-app (DB) value overrides `IMGBB_API_KEY`; the env
  var remains a fallback for tunnel/CI deploys.

## Architecture

`Config` stays a frozen dataclass; `Config.imgbb_api_key` remains the env-derived
fallback. Runtime mutability is achieved not by mutating `Config` but by routing
all key reads through a resolver that prefers the DB value.

```
settings table (imgbb_api_key)  ──┐
                                  ├──> effective_imgbb_key(db, cfg) ──> call sites
Config.imgbb_api_key (env)      ──┘
```

### 1. Storage & resolution

**`store/db.py`** — three thin convenience methods over the existing generic
`get_setting`/`set_setting` (`SETTINGS_IMGBB_KEY = "imgbb_api_key"`):

- `get_imgbb_key() -> str | None` — returns the stored value, or `None` if unset
  or empty.
- `set_imgbb_key(key: str) -> None` — persists a (stripped, non-empty) value.
- `clear_imgbb_key() -> None` — deletes the setting row (or sets it empty).

**Key resolver** — a small pure function (location: `pipeline/hosting.py`,
beside the imgbb code, or a tiny `pipeline/imgbb.py`; implementer's call):

```python
def effective_imgbb_key(db: Database, cfg: Config) -> str | None:
    return db.get_imgbb_key() or cfg.imgbb_api_key
```

DB value wins; env is the fallback; `None` only when neither is present. This is
the single decision point for "is the app usable / should we gate?", which keeps
the gate logic testable without rendering UI.

### 2. Validation — `pipeline/hosting.py`

```python
def validate_imgbb_key(api_key: str, timeout: float = 15.0) -> None:
    """Raise ImgbbError if the key is rejected by imgbb; return on success."""
```

- imgbb has **no key-check endpoint**, so validation is a real upload of a
  module-level 1×1-pixel PNG constant (no file I/O), POSTed with
  `params={"key": api_key, "expiration": 60}`.
- HTTP ≥ 400 → `ImgbbError` (imgbb returns 400 for an invalid key). Network
  error → `ImgbbError` (reuse the existing wrapping in `upload_image`).
- On success, read `data.delete_url` and fire a **best-effort** request to it to
  delete the test image immediately; swallow any error from that delete. The
  `expiration=60` guarantees cleanup even if the delete call fails.
- Blocking `httpx` call → callers wrap in `asyncio.to_thread`.

**Known limitation:** imgbb's minimum `expiration` is 60s and `delete_url` is not
a documented programmatic API, so in the worst case (delete call fails) a 1×1
test pixel can linger up to ~60s. Acceptable.

### 3. Onboarding gate & settings dialog — `ui/onboarding.py` (new)

A shared key-entry form, used in two surfaces.

**Onboarding gate** — rendered by `_render_wizard` *before* the URL input or any
job, when `effective_imgbb_key(db, cfg)` is empty:

- Title + short explainer, a link to imgbb's API-key page
  (`https://api.imgbb.com/`), a password-style `ui.input`, a "Save & continue"
  button.
- On save: strip input; reject empty inline; show a brief "Checking…" state; run
  `validate_imgbb_key` via `asyncio.to_thread`.
  - Success → `db.set_imgbb_key(...)` then `_render_wizard.refresh()` (the wizard
    now renders).
  - Failure → inline error ("That key didn't work — check it and try again");
    stay on the gate.

**Settings dialog** — a small persistent affordance (gear / "API key"
`html_button`) in the wizard header, available once past the gate:

- `ui.dialog` reusing the same entry form, pre-showing the current key **masked**
  (e.g. `••••••1234`, last 4 chars) with a reveal toggle.
- **Save** — validates then writes (same flow as the gate).
- **Clear** — `clear_imgbb_key()`; on next render the gate reappears unless an
  env var still supplies a key.
- Edge case: when the effective key comes only from the env var (DB empty), the
  dialog labels it "set via environment"; Save writes a DB override, Clear
  removes only the DB override.

### 4. Wiring — `ui/pages.py`

- `_render_wizard`: add the gate check at the top; render `render_onboarding(...)`
  and return when the effective key is empty.
- Add the settings button to the wizard header.
- Replace the three `cfg.imgbb_api_key` reads with `effective_imgbb_key(db, cfg)`:
  - `:127` banner — **removed** (the gate guarantees a key); a defensive
    `ui.notify` remains only at the search guard.
  - `:165` search guard — uses the resolver.
  - `:203` upload — uses the resolver.
- `hosting.upload_image` signature is unchanged; it still takes an explicit
  `api_key`, now sourced from the resolver.

## Error handling

- Invalid/empty key on save → inline message, no state change, retry in place.
- imgbb/network failure during validation → treated as "key didn't work" (we
  cannot distinguish a bad key from a transient outage; the user retries).
- Existing real-search imgbb error path (`ui.notify(f"imgbb: {exc}")`) is
  retained as the runtime safety net.

## Testing

- `validate_imgbb_key` (respx): success asserts the `expiration` param is sent
  and `delete_url` is hit; 400/invalid-key → `ImgbbError`; network error →
  `ImgbbError`.
- `Database` key methods: set/get/clear round-trip in an `isolated_data_dir` DB.
- `effective_imgbb_key`: DB value wins over env; falls back to env; `None` when
  neither is set.
- Gate decision stays a pure-function test via the resolver; UI rendering stays
  thin.

## Out of scope (YAGNI)

- Per-user / per-browser keys.
- Encryption of the key at rest (the key already lives in `app.db` on a local
  machine).
- A general-purpose settings page (only the imgbb key gets an affordance now;
  `enabled_engines` remains seed-only).
```
