# CLAUDE.md

`rrs` (ranking reverse search) — a local NiceGUI app for sourcing video clips
out of compilation/ranking videos via reverse image search.

## Commands

```sh
pip install -e ".[dev]"      # setup (Python 3.11+, ffmpeg + ffprobe on PATH)
rrs                          # run (or: python -m rrs.main) → http://localhost:8080
pytest                       # tests
```

Also needs **Deno ≥2.0 on PATH** (recommended JS runtime) for full YouTube
support — yt-dlp (≥2025.11.12) runs it to solve YouTube's signature/nsig JS
challenges. Missing it is non-fatal (soft warning + UI banner), but format
availability degrades. Install via `brew install deno` or https://deno.com/.

Required/optional env vars: `IMGBB_API_KEY` (seeds the imgbb key, but it can also
be entered in-app — see below), `DATA_DIR` (default `./data`), `PORT` (default 8080),
`SCENE_THRESHOLD` (default 27.0), `MAX_CLIP_DURATION_SEC` (default 180 — initial clips
longer than this are refused before download; `0` disables the cap. rrs targets
shorts, not full videos). Tunable defaults live in `constants.py`.

## Architecture

Layered, single-process:

`constants.py` → `config.py` → `store/` (sqlite) → `pipeline/` → `ui/`, wired in
`main.py`.

- **`constants.py`** — the lowest layer: tunable knobs (quality, timeouts, size
  caps, UI cadences) pulled out of the code. Imports nothing from the package, so
  any module may import it without a cycle. Some entries double as the defaults
  for env-overridable settings in `config.py` (env still wins at runtime).
- **`main.py`** — boots config + DB, registers pages, runs NiceGUI. Holds
  module-level `_DB`/`_CFG` singletons exposed via `get_db()` / `get_cfg()`,
  which are passed into the UI layer as callables. Guards both `__main__` and
  `__mp_main__` (NiceGUI multiprocessing).
- **`store/db.py` + `store/schema.sql`** — `Database` wraps a sqlite connection;
  schema is applied on every open (idempotent `CREATE TABLE IF NOT EXISTS`).
  Tables: `jobs`, `scenes`, `frames`, `sources`, `settings`. Row → frozen
  dataclass (`Job`, `Scene`, `Frame`, `Source`). The imgbb key and per-job
  `download_dir` live here; new columns are added via idempotent `ALTER TABLE`
  migrations in `Database._migrate`.
- **`pipeline/`** — `download` (yt-dlp), `scenes` (PySceneDetect), `frames`
  (ffmpeg frame extraction), `hosting` (imgbb upload + key validation/resolution),
  `engines/`, `jobs` (orchestration).
- **`ui/`** — `pages.py` (wizard / index page), `components.py` (scene cards),
  `modals.py` (frame picker, trim modal), `onboarding.py` (imgbb-key gate +
  settings dialog).

## Key patterns

- **Job state machine** (`store/db.py` `JobStatus`):
  `downloading → detecting_scenes → extracting_frames → interactive`, or
  `failed`. `pipeline/jobs.py::run_pre_interactive_pipeline` drives it; on any
  exception it calls `db.fail_job` and re-raises. Blocking work (download, scene
  detect, frame extract) runs via `asyncio.to_thread` to keep the UI responsive.
- **Engine registry** (`pipeline/engines/`): each engine is a frozen `Engine`
  dataclass with `status` (`"ready"` | `"todo"`) and a `url_template`.
  `search_url()` returns `None` for `todo`/stub engines. `ALL_ENGINES` aggregates
  them; the enabled-engine set is persisted as JSON in the `settings` table
  (seeded from `default_enabled_ids()` on first run). Add an engine by creating a
  module exporting `ENGINE` and registering it in `engines/__init__.py`.
- **Data layout**: per-job files under `DATA_DIR/jobs/<id>/`
  (`source.mp4`, `frames/<scene>/<ordinal>.jpg`, `sources/`); sqlite at
  `DATA_DIR/app.db`. Served read-only at `/_data`; static assets at `/_static`.

## Gotchas

- `ffmpeg` **and** `ffprobe` must be on PATH — probed at startup
  (`MissingDependencyError`), except when `load_config(probe_ffmpeg=False)`.
- Reverse search needs an imgbb key: frames are uploaded to imgbb to get a public
  URL fed to engine `url_template`s. The key resolves via
  `hosting.effective_imgbb_key(db, cfg)` — the DB-stored key (set in-app, see
  `ui/onboarding.py`) takes precedence over the `IMGBB_API_KEY` env var. With no
  key, `pages.py` gates the whole app behind the onboarding screen. Uploaded
  frames carry an `expiration` so imgbb auto-deletes them (frames after a week,
  validation probes after 60s — `IMGBB_*_EXPIRATION_SEC` in `constants.py`).
- NiceGUI 3.x: `ui.add_head_html(...)` must pass `shared=True` (see commit
  `a7b4184`).
- `pages.py` occasionally reaches into `db._conn` directly for ad-hoc queries.

## Packaging & distribution

Two ways to get rrs to people (full docs in README):

- **Desktop bundle (`scripts/pack.py`; Unix wrapper `scripts/rrs-pack`)** —
  cross-platform PyInstaller `--onedir` build. PyInstaller can't cross-compile,
  so build on the target OS. Bundles `schema.sql`, `ui/static`, and the
  ffmpeg/ffprobe/deno binaries on PATH into `_internal/bin/`. ~220–360 MB (deno
  alone is ~138 MB).
- **CI release (`.github/workflows/build.yml`)** — tag `v*` → builds
  windows-x64 / macos-arm64 / linux-x64 on native runners and attaches zips to a
  GitHub Release; `workflow_dispatch` → run artifacts only (requires the workflow
  on the default branch). Each job installs Deno + a static ffmpeg, then runs
  `pack.py`. Windows uses `setup-ffmpeg`; macos-arm64 and linux-x64 download
  portable builds straight from ffmpeg.martin-riedl.de (`setup-ffmpeg` has no
  arm64, and its Linux source — johnvansickle.com — periodically goes down).

**Frozen-app rules — don't regress these; they only bite in a bundle, never in
`python -m rrs.main`:**
- `main.py` calls `multiprocessing.freeze_support()` before `main()`, else the
  frozen binary fork-bombs on startup (each spawned worker re-runs `main()`).
- Resolve bundled resources via `importlib.resources`, not `__file__`-relative
  paths (`main.py::_static_dir`); the entry script is relocated when frozen.
- `config._activate_bundled_binaries()` prepends `_MEIPASS/bin` to PATH so the
  frozen app finds bundled ffmpeg/ffprobe/deno.

Caveats: bundles are unsigned (Gatekeeper/SmartScreen warn); a dynamically-linked
system ffmpeg won't run elsewhere (use a static build). When `DATA_DIR` is unset,
a frozen bundle defaults `data/` to the directory holding the binary
(`sys.executable`'s parent), not the launch CWD (`config._default_data_dir`); a
source run still defaults to `./data` relative to the CWD. The env var wins in
both cases.

## Testing

- `tests/conftest.py` provides `synthetic_video` (an ffmpeg-built 3-scene clip,
  so no binary fixtures are checked in) and `isolated_data_dir` (temp `DATA_DIR`).
- ffmpeg-dependent tests `pytest.skip` when ffmpeg is absent.
- httpx calls (imgbb) are mocked with `respx`. `asyncio_mode = "auto"`.

## Docs

Design spec: `docs/superpowers/specs/2026-06-14-ranking-reverse-search-design.md`.
