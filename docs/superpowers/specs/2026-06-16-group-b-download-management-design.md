# Group B — Download management

Design for TODO.txt Group B (F3, F6, F7): give downloaded clips a convenient,
collision-safe home and add a general-purpose "download any extra clip" box.

## Background

Today, downloads land in `DATA_DIR/downloads/<safe-title>/scene-NN.mp4`, where
`<safe-title>` comes from the ranking video's title (`jobs.py::downloads_dir` +
`safe_dirname`), falling back to `job-<id>` only when the title is empty. Per-scene
source clips are downloaded from the URL bar in each scene card
(`pages.py::download_source_for_scene`) and named `scene-01.mp4`, `scene-02.mp4`, …
An "OPEN FOLDER" button reveals the folder in the OS file manager (meaningful only
for a locally-run app, not a tunnel tester).

There is effectively one "active job" (the newest `jobs` row); no job-history UI.
The `data/downloads/` tree persists across jobs — START OVER wipes only
`data/jobs/<id>/`.

### Problems

- **F3** — the download path should be a clear, self-contained, stable location.
- **F7** — two ranking videos with the *same title* map to the *same*
  `downloads/<title>/` folder, so a new job silently overwrites a past job's
  downloads.
- **F6** — there is no way to download an arbitrary clip that isn't tied to a
  scene's reverse-search result.

## Decisions

These were settled during brainstorming:

- **Download location:** keep clips self-contained under `DATA_DIR/downloads/`
  (not the OS Downloads folder), so the layout works identically for a local app
  and a tunnel tester.
- **Folder disambiguation:** prefer clean `<title>/` names; only fall back to
  `<title> (2)/`, `<title> (3)/`, … when that name already belongs to a different
  job.
- **Extra clips:** save into the *active job's* folder, numbered
  `extra-01.mp4`, `extra-02.mp4`, … alongside the `scene-NN.mp4` clips (clip title
  ignored, for predictable names).

## Design

### 1. Path scheme (F3)

Downloads stay under `DATA_DIR/downloads/`. Each job owns one folder holding
everything for that session:

```
DATA_DIR/downloads/<video title>/
    scene-01.mp4        # per-scene source clips (existing)
    scene-02.mp4
    extra-01.mp4        # extra-clip downloader (new, F6)
    extra-02.mp4
```

"OPEN FOLDER" keeps revealing this folder. The resolved path is also shown as text
near the extra-clip downloader so tunnel testers (who can't open a local file
manager) can see where files go.

### 2. Collision-safe folder assignment (F7)

Replace the pure function `downloads_dir(data_dir, title, job_id)` with an
**assign-once-and-persist** scheme:

- Add a `download_dir TEXT` column to the `jobs` table (additive migration via the
  existing `Database._migrate()` pattern — the `table_info` check makes the ALTER
  run at most once).
- New `resolve_download_dir(db, data_dir, job) -> Path`:
  - If the job already has `download_dir` stored → return it. This keeps the
    folder stable for the job's whole life, so OPEN FOLDER and the download writers
    always agree.
  - Otherwise pick the first candidate of `<title>/`, `<title> (2)/`,
    `<title> (3)/`, … that is **both** (a) absent on disk **and** (b) not claimed
    by any other job's `download_dir` in the DB. Persist the choice to the job row,
    then return it.
  - The base name comes from `safe_dirname(job.title, job.id)` (unchanged); the
    ` (n)` suffix is appended to that directory name.
- Assignment is **lazy**: it happens on the first `resolve_download_dir` call for
  a job (the "else" branch above persists the choice). The disk + DB checks need
  `data_dir`, which `Database.set_job_source` doesn't have, so assignment is *not*
  done there. Since downloads only happen in the `interactive` state — after the
  title is set — the first call always sees a known title. The folder itself is
  still created lazily (`mkdir`) by the first writer / OPEN FOLDER, as today.

Why both checks:

- **Disk check** — START OVER deletes the job row but **not** the `downloads/`
  files. Without the disk check, a later same-title job would reclaim `<title>/`
  and clobber the orphaned files.
- **DB check** — guards against two live jobs with the same title racing onto the
  same name before either folder exists on disk.

With `scene-NN`/`extra-NN` filenames being inherently unique within a folder, this
folder-level fix is the entirety of F7 — there are no remaining title-based file
collisions.

### 3. Extra-clip downloader (F6)

A new UI component rendered at the bottom of the interactive scene list, shown
**only** when a job is in the `interactive` state (it writes into the job folder,
so it needs an active job):

- A URL input + "DOWNLOAD" button + an inline status line, styled like the
  existing per-scene download row (`_render_download_row`).
- On download:
  1. Resolve the job folder via `resolve_download_dir`.
  2. Scan it for existing `extra-*.mp4` and pick the next free `extra-NN.mp4`
     (zero-padded to two digits, matching `scene-NN`).
  3. Download at full resolution (`download_video(url, out, max_height=None)`,
     same as scene clips).
  4. Show ✓ `downloaded: extra-NN.mp4` / ✗ `failed: <err>` inline.
- Extra clips are **not** recorded in the `sources` table (that table is keyed per
  scene); they are pure file outputs surfaced via OPEN FOLDER.

## Affected code

- `pipeline/jobs.py` — replace `downloads_dir` with `resolve_download_dir`; keep
  `safe_dirname`; add next-`extra-NN` helper (or place it in `pages.py`).
- `store/schema.sql` — add `download_dir TEXT` to `jobs`.
- `store/db.py` — migration for `download_dir`; getter/setter for the column;
  include `download_dir` in the `Job` dataclass and `_row_to_job`.
- `ui/pages.py` — use `resolve_download_dir`; add the extra-clip download handler;
  render the extra downloader at the bottom of `_render_scene_list`.
- `ui/components.py` — extra-clip downloader component (reusing the download-row
  styling).

## Testing

- `resolve_download_dir`:
  - clean `<title>/` when the name is free;
  - `<title> (2)/` when the folder already exists on disk;
  - `<title> (2)/` when another job's DB row claims `<title>/`;
  - stable (same path) on repeated calls for the same job;
  - empty title falls back to `job-<id>` as before.
- Migration adds the `download_dir` column to a pre-existing DB without the column.
- Extra-clip numbering picks the next free `extra-NN` given existing files.
- Path-selection tests mock `download_video`; real download behaviour is already
  covered/mocked elsewhere (`respx` for imgbb; ffmpeg-built synthetic video).

## Out of scope

- Moving downloads outside `DATA_DIR` / making the root configurable.
- Job-history UI or multi-job management.
- Recording extra clips in the database.
