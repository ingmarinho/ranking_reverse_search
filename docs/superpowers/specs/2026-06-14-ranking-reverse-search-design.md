# Ranking Reverse Search — Design

A locally-run NiceGUI app for sourcing video clips out of compilation/ranking videos via reverse image search. Single user, localhost, no hosting.

## Goal

Paste a ranking video URL → app downloads it → detects scenes → user picks representative frames per scene → clicks engine buttons that open reverse-image searches in new tabs → user pastes back source URLs → app downloads the original sources → user trims the relevant clip out of each source.

## Stack

- Python 3.11+
- NiceGUI (bundled FastAPI/uvicorn) — the only UI/server layer
- `yt-dlp` used as a library (`from yt_dlp import YoutubeDL`), never shelled out
- PySceneDetect with `ContentDetector` (threshold 27.0 default)
- `opencv-python` for frame extraction
- `ffmpeg` system binary on `PATH`, surfaced as a startup error if missing
- `sqlite3` stdlib for persistence
- `imgbb` HTTP API for hosting frames (so engine URLs can prefill an image URL)

No separate web framework. No headless browser. No keypoint matching, no perceptual hashing.

## High-level architecture

A single Python process serving NiceGUI on `localhost:8080`. The same process runs background work as `asyncio` tasks and offloads CPU/IO-heavy steps via `run_in_executor`.

Modules:

- `ui/` — NiceGUI page(s), components, modals
- `pipeline/` — per-stage pure functions: `download.py`, `scenes.py`, `frames.py`, `hosting.py`, `engines/`, `trim.py`
- `store/` — SQLite schema + a thin DAL
- `config.py` — env-var config, startup probes (ffmpeg, imgbb key)

One concurrent job at a time. The UI is a wizard for one video at a time per UX call below; the schema and storage are structured per-job so reload mid-pipeline rehydrates cleanly.

## UX shape

Single-page wizard. State-driven view selection off `jobs.status`:

| `status` | View |
|---|---|
| (no job) | URL input + "Process video" button |
| `downloading` | Progress bar driven by yt-dlp progress hooks |
| `detecting_scenes` | Spinner + label |
| `extracting_frames` | Spinner + scene count |
| `interactive` | Scene list (main working view) |
| `failed` | Error + retry / new-job |

Status stays `interactive` for the lifetime of the wizard — there is no terminal `done` state. The user just stops when they're satisfied. "Start over" tears the job down.

Scene list view (the main working surface) — top shows ranking video title/duration + "Start over" (deletes job folder and rows). Below: a scrollable list of scene cards. Each card has:

- The currently-selected frame thumbnail on the left. Click → frame picker modal.
- Timestamp range, scene index, total scene count.
- Row of engine buttons (one per enabled, `status="ready"` engine). Disabled / TODO engines live in a "More" popover.
- Source URL input + "Download source" button. After download: "Trim clip" button → trim modal. After trim: small video preview + "Open folder" link.

Frame picker modal: 9 candidate frames evenly spaced through the scene, extracted lazily on first open. Click to swap the default selection; "+" / cmd-click to add an additional selected frame (multiple selections per scene supported). The scene card then renders one engine-button row per selected frame.

Trim modal: HTML5 `<video>` loaded from the local source file via a NiceGUI route scoped to `data/`. Dual-thumb slider over the source duration + two numeric inputs for `start_sec` / `end_sec`. Default window: `[source_mid − scene_dur/2, source_mid + scene_dur/2]`, clamped to source length. "Save clip" runs ffmpeg stream-copy.

## Visual design

The aesthetic is "editing bay / contact sheet" — a film editor's review surface, not a generic web dashboard. The user is alone at their desk combing footage; the UI should feel like a workshop tool, dense and functional, with character.

**Typography:** IBM Plex Mono everywhere. Weights 400 / 500 / 700, with letter-spacing variations carrying the typographic hierarchy (tracked-out uppercase for labels, tight for body). Loaded once from the bundled `nicegui` static assets path. No other typefaces.

**Palette (CSS variables):**

```
--bg:         #0d0c0a   /* paper-black, slight warm tint */
--surface:    #161513   /* warm graphite, lifted surfaces */
--border:     #2a2826   /* hairline */
--text:       #e8e6e1   /* warm off-white */
--text-dim:   #7a7771   /* meta, timecodes when secondary */
--accent:     #ff8a3d   /* cinema marker amber — selection, progress, primary action */
--danger:     #c14a3d   /* failed states only */
```

Amber accent is the only color besides grayscale + danger. Used sparingly: selected frames, primary buttons, progress fills, the active scene's left border.

**Corners & borders:** 0 radius everywhere. 1px hairline borders in `--border`. Selected / active states swap to 2px solid `--accent`. No drop shadows.

**Scene card layout:**

```
┌──────────────────────────────────────────────────────────────┐
│ 07 / 42        00:01:23.456 — 00:01:31.812        Δ 8.36s   │
│                                                              │
│ ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐                  │
│ │ 01  │  │     │  │     │  │     │  │  +  │   ← strip of    │
│ │ ▓▓▓ │  │ ▓▓▓ │  │ ▓▓▓ │  │ ▓▓▓ │  │     │     selected    │
│ └─────┘  └─────┘  └─────┘  └─────┘  └─────┘     frames       │
│  amber                                                       │
│                                                              │
│ ▸ GOOGLE LENS   ▸ YANDEX   ▸ BING   ▸ TINEYE   ▸ SAUCENAO    │
│                                                              │
│ source url ▕ https://...                       [ DOWNLOAD ]  │
│                                                              │
│ ─ source.mp4  · 04:12  ──────────────────  [ TRIM ]          │
└──────────────────────────────────────────────────────────────┘
```

- Top row: scene index `07 / 42` (left, weight 700, tracked +0.05em), in/out timecodes (centered, mono), scene duration (right, dimmed, `Δ 8.36s` notation).
- Frame strip: square thumbnails, sharp corners, hairline border. The currently-selected frame(s) get a 2px amber border and a tiny `01`, `02`, ... ordinal tag in the upper-left (white-on-amber, mono, weight 700). Last cell is a `+` adder that opens the frame picker.
- Engine button row: small mono chips, uppercase, tracked. Leading `▸` glyph. Hairline border on idle; amber border + amber text on hover. Disabled (TODO-status) engines render dimmed without the `▸`.
- Source URL field: hairline-bordered input, mono. After download, collapses into the bottom "source.mp4 · 04:12" status line.
- "DOWNLOAD" and "TRIM" actions are mono uppercase buttons, amber fill when primary.

**Frame picker modal:** dark backdrop (90% opacity over the page). 3×3 grid of candidates from the scene. Each candidate has the same square + hairline treatment as the scene strip. Clicking toggles selection; selected candidates show the amber border + ordinal tag immediately. A subtle scrubber underneath shows where in the scene each candidate sits.

**Trim modal:** the source video centered, 60% viewport width. Below it: a single horizontal timeline with two amber thumbs and dim duration ticks every 10 seconds. Numeric inputs to the side, mono. `[ SAVE CLIP ]` button bottom right in amber.

**Progress / status indicators:**

- Top-level progress bar (download / scene detect): 1px tall, full-width across the top of the wizard, amber fill on `--border` track. Indeterminate state pulses opacity 40%↔100% at 1.2s cycles.
- Stage label sits left-justified below the bar in tracked uppercase: `DOWNLOADING RANKING VIDEO · 47%`.

**Atmosphere:**

- A single SVG `<feTurbulence>` filter applied as a fixed-position overlay at ~3% opacity gives surfaces the look of fine film grain. Pointer-events: none.
- Optional: a thin amber `1px` vertical rule down the very edge of the viewport when a job is active — like a frame leader strip.

**Motion (restrained):**

- Page-load: scene cards fade + translateY(8px) into place with 40ms stagger.
- Engine chip hover: 120ms border-color transition.
- Selection toggle on a frame: 80ms border swap, no scale or bounce.
- Progress bar fill: linear `width` transition, 200ms.
- Modal open: 120ms fade + 4px translateY on the modal body. Backdrop is instant.

No spring easings, no playful bounces. The motion should feel mechanical and confident, like a tape transport.

**Implementation notes for NiceGUI:**

- All visual styling lives in a single injected CSS file (`ui/static/app.css`) loaded once via `app.add_static_files` and `ui.add_head_html('<link rel="stylesheet" ...>')`.
- Components use `ui.element('div').classes(...)` with named utility classes from `app.css` rather than inline Tailwind soup — keeps the aesthetic centralized.
- Plex Mono served from `ui/static/fonts/` (self-hosted woff2, two weights bundled) — no Google Fonts CDN call.

## Pipeline stages

Each stage updates `jobs.status` and is checkpointed in SQLite so a crash mid-pipeline doesn't lose progress.

1. **Download ranking video** (`pipeline/download.py`) — yt-dlp library call. Format: `bv*[height<=1080]+ba/b[height<=1080]`, `merge_output_format=mp4`, output to `data/jobs/<id>/source.mp4`. Writes `jobs.title`, `jobs.duration_sec`, `jobs.source_path`.

2. **Scene detect** (`pipeline/scenes.py`) — PySceneDetect `SceneManager` + `ContentDetector(threshold=27.0)`. Persist each detected scene as a `scenes` row. If no scenes are detected (very short / static video), fall back to one synthetic scene spanning the whole video.

3. **Extract default frames** (`pipeline/frames.py`) — for each scene, extract the first frame via OpenCV `VideoCapture.set(CAP_PROP_POS_FRAMES, start_frame)`, write to `frames/<scene_idx>/0.jpg`, insert `frames` row with `ordinal=0`, `is_selected=1`. Additional frames are extracted lazily by the frame picker modal.

4. **Interactive — reverse search** — on first reverse-search click for a frame, upload to imgbb, cache `frames.imgbb_url`; the clicked button shows a spinner during upload. Subsequent clicks on any engine button for the same frame reuse the cached URL and open instantly. Each engine button opens that engine's search URL (with `image_url` prefilled) in a new tab.

5. **Source download (per scene)** — user pastes source URL → yt-dlp called with `format="bv*+ba/b"` (best available, no resolution cap) into `sources/<scene_idx>.<ext>`. Writes a `sources` row.

6. **Trim** — user opens trim modal, adjusts thumbs, saves → `ffmpeg -ss A -to B -i <source> -c copy <out>` writes `clips/<scene_idx>.mp4`. Stream copy = fast, snaps to keyframe (fine for this use case).

## Engine adapter registry

Each engine is one module under `pipeline/engines/` exporting an `Engine` instance:

```python
@dataclass(frozen=True)
class Engine:
    id: str                    # "google_lens", "yandex", ...
    name: str                  # "Google Lens"
    category: str              # "western" | "chinese" | "regional" | "specialized"
    enabled_by_default: bool
    status: str                # "ready" | "todo"

    def search_url(self, image_url: str) -> str:
        ...
```

`pipeline/engines/__init__.py` collects all instances into a list. The UI renders toggle checkboxes and per-frame button rows from the registry filtered by `settings.enabled_engines` (JSON list in the `settings` table). On first run, `settings.enabled_engines` is seeded from every engine with `enabled_by_default=True AND status="ready"`.

MVP engines (`status="ready"`, verified URL-prefill):

| Engine | URL template |
|---|---|
| Google Lens | `https://lens.google.com/uploadbyurl?url={image_url}` |
| Yandex Images | `https://yandex.com/images/search?rpt=imageview&url={image_url}` |
| Bing Visual Search | `https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{image_url}` |
| TinEye | `https://tineye.com/search?url={image_url}` |
| SauceNAO | `https://saucenao.com/search.php?url={image_url}` |

Exact URL strings must be verified during build; the spec authoritatively says "one module per engine, URL is the only quirk." When an engine breaks, you patch one file.

Stubbed (`status="todo"`, not enabled, shown disabled in settings): Baidu, Sogou, Qihoo 360, Naver, Lenso.ai, PimEyes, Karma Decay. They need form POST / cookies / login and are out of MVP scope.

## Data model

SQLite, schema applied on startup with `CREATE TABLE IF NOT EXISTS`:

```sql
CREATE TABLE jobs (
  id              INTEGER PRIMARY KEY,
  url             TEXT NOT NULL,
  title           TEXT,
  duration_sec    REAL,
  source_path     TEXT,
  status          TEXT NOT NULL,   -- downloading|detecting_scenes|extracting_frames|interactive|failed
  error           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE scenes (
  id              INTEGER PRIMARY KEY,
  job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  idx             INTEGER NOT NULL,
  start_frame     INTEGER NOT NULL,
  end_frame       INTEGER NOT NULL,
  start_sec       REAL NOT NULL,
  end_sec         REAL NOT NULL,
  UNIQUE(job_id, idx)
);

CREATE TABLE frames (
  id              INTEGER PRIMARY KEY,
  scene_id        INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
  ordinal         INTEGER NOT NULL,   -- 0 = default first frame; >0 = user-added extras
  frame_number    INTEGER NOT NULL,   -- absolute frame in ranking video
  path            TEXT NOT NULL,
  imgbb_url       TEXT,               -- cached upload URL (NULL until first reverse-search click)
  is_selected     INTEGER NOT NULL DEFAULT 0,
  UNIQUE(scene_id, ordinal)
);

CREATE TABLE sources (
  id              INTEGER PRIMARY KEY,
  scene_id        INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
  url             TEXT NOT NULL,
  path            TEXT,
  trim_start_sec  REAL,
  trim_end_sec    REAL,
  clip_path       TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE settings (
  key             TEXT PRIMARY KEY,
  value           TEXT NOT NULL
);
```

`settings` holds: `enabled_engines` (JSON list of engine ids), `scene_detect_threshold` (float override).

Filesystem layout under `<DATA_DIR>/jobs/<job_id>/` (where `DATA_DIR` defaults to `./data`):

```
source.mp4                  # ranking video, 1080p
frames/<scene_idx>/0.jpg    # default first frame
frames/<scene_idx>/<n>.jpg  # additional user-picked frames
sources/<scene_idx>.<ext>   # downloaded source video
clips/<scene_idx>.mp4       # final trimmed clip
```

The job folder is the unit of cleanup: delete folder + cascade rows.

`sources` is 1:1 with `scenes` for MVP. If multi-source-per-scene is ever wanted, drop the implicit 1:1 and let the UI pick one.

## Threading & concurrency

UI on the main asyncio loop. Heavy work (yt-dlp download, scene detect, frame extraction, ffmpeg trim) runs via `loop.run_in_executor` so the UI stays responsive. Progress is pushed to the UI by mutating NiceGUI reactive vars from the worker via `app.add_static_files` or `ui.run_javascript`-style updates as appropriate to NiceGUI's reactive model.

In-flight async tasks are tracked in an in-memory dict keyed by job id. On page reload, if `jobs.status` indicates an in-progress stage but no task is alive in that dict, the UI shows a "Resume" button rather than silently re-running the stage.

## Configuration

Read from env at startup (`config.py`):

- `IMGBB_API_KEY` — required for reverse-search buttons; missing → buttons disabled with tooltip, rest of app still runs
- `DATA_DIR` — defaults to `./data`
- `PORT` — defaults to `8080`
- `SCENE_THRESHOLD` — defaults to `27.0` (also overridable per-instance in `settings` table)

Startup probes:

- `shutil.which("ffmpeg")` — missing → full-page error, app refuses to render wizard.
- imgbb key check — missing → log warning, set internal flag that disables engine buttons.

## Error handling

| Failure | Behaviour |
|---|---|
| Missing ffmpeg at startup | Full-page error, no wizard |
| Missing imgbb key | Wizard runs, engine buttons disabled with tooltip |
| yt-dlp ranking download fails | `jobs.status='failed'`, `jobs.error` set; UI shows message + "Try again" (re-runs the stage) |
| No scenes detected | Synthesise one scene covering whole video |
| imgbb upload fails on click | Retry once, then toast error and skip opening the tab |
| yt-dlp source download fails | Scoped to the scene's source row; UI shows error + retry on that card |
| ffmpeg trim fails | Toast stderr, leave `sources.clip_path` NULL |
| Page reload mid-pipeline | UI rehydrates from `jobs.status`; orphaned in-progress state shows "Resume" button |

## Testing

- **Unit:** each `pipeline/*` module against small (~10s) fixture videos in `tests/fixtures/`. Engine adapters: assert URL output for known inputs.
- **DB:** in-memory SQLite, apply schema, exercise DAL CRUD.
- **Integration:** one end-to-end test against a checked-in ~30s fixture video — yt-dlp mocked to copy the fixture; scenes, frame extraction, trim run for real; imgbb/engines mocked.
- **No UI tests in MVP.** Manual smoke testing the wizard is sufficient for a single-user localhost tool.

## Out of scope for MVP

- Multi-job history / job list UI (schema supports it; UI deferred)
- Auto-trim via pHash or ORB matching (decided manual-only — overlay text on ranking videos makes automatic matching unreliable)
- Headless-browser engine adapters (Baidu / Sogou / Naver / etc) — stubbed as TODO
- Frame-accurate (re-encoding) trim — stream copy is good enough
- Auth / multi-user — localhost only
