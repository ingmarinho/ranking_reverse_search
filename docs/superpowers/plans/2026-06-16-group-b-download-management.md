# Group B — Download Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give downloaded clips a stable, collision-safe per-job folder under `DATA_DIR/downloads/`, and add a "download any extra clip" box at the bottom of the interactive view.

**Architecture:** Each job is assigned exactly one download folder, resolved lazily and persisted to a new `jobs.download_dir` column. The folder name prefers the clean video title and only appends ` (2)`, ` (3)`, … when that name is already taken by another job (checked against both disk and DB). Extra clips download into the active job's folder as `extra-NN.mp4`, numbered alongside the existing `scene-NN.mp4` clips.

**Tech Stack:** Python 3.11+, sqlite (stdlib), NiceGUI 3.x, yt-dlp, pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-group-b-download-management-design.md`

---

## File structure

- `src/rrs/store/schema.sql` — add `download_dir TEXT` column to `jobs`.
- `src/rrs/store/db.py` — migration for the new column; `download_dir` on the `Job` dataclass + `_row_to_job`; `set_download_dir`; `claimed_download_dirs`.
- `src/rrs/pipeline/jobs.py` — replace `downloads_dir` with `resolve_download_dir(db, data_dir, job)`; add `next_extra_path(folder)`; keep `safe_dirname`.
- `src/rrs/ui/pages.py` — use `resolve_download_dir` in `download_source_for_scene` and `_open_downloads_folder`; add `download_extra_clip`; render the extra downloader at the bottom of `_render_scene_list`.
- `src/rrs/ui/components.py` — add `render_extra_downloader(...)`.
- `tests/test_db.py`, `tests/test_jobs.py`, `tests/test_pages_downloads.py` (new) — tests.

---

## Task 1: `download_dir` column + DB plumbing

**Files:**
- Modify: `src/rrs/store/schema.sql`
- Modify: `src/rrs/store/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_job_download_dir_defaults_none(db: Database):
    job_id = db.create_job(url="x")
    assert db.get_job(job_id).download_dir is None


def test_set_and_get_download_dir(db: Database):
    job_id = db.create_job(url="x")
    db.set_download_dir(job_id, "/data/downloads/My Video")
    assert db.get_job(job_id).download_dir == "/data/downloads/My Video"


def test_claimed_download_dirs_excludes_given_job(db: Database):
    a = db.create_job(url="a")
    b = db.create_job(url="b")
    db.set_download_dir(a, "/d/Foo")
    db.set_download_dir(b, "/d/Bar")
    # Claims by jobs other than `a`:
    assert db.claimed_download_dirs(exclude_job_id=a) == {"/d/Bar"}
    # Jobs with no download_dir contribute nothing:
    c = db.create_job(url="c")
    assert db.claimed_download_dirs(exclude_job_id=c) == {"/d/Foo", "/d/Bar"}


def test_migration_adds_download_dir_to_legacy_db(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL,"
        " title TEXT, duration_sec REAL, source_path TEXT, status TEXT NOT NULL,"
        " error TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));"
    )
    conn.commit()
    conn.close()

    db = open_db(path)
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(jobs)")}
    assert "download_dir" in cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -k "download_dir or migration_adds_download_dir" -v`
Expected: FAIL — `Job` has no attribute `download_dir`, `set_download_dir`/`claimed_download_dirs` not defined.

- [ ] **Step 3: Add the column to the schema**

In `src/rrs/store/schema.sql`, add `download_dir` to the `jobs` table (after `source_path`):

```sql
CREATE TABLE IF NOT EXISTS jobs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  url             TEXT NOT NULL,
  title           TEXT,
  duration_sec    REAL,
  source_path     TEXT,
  download_dir    TEXT,
  status          TEXT NOT NULL,
  error           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

- [ ] **Step 4: Add the migration**

In `src/rrs/store/db.py`, extend `_migrate` (after the existing frames-column loop, before the final `self._conn.commit()`):

```python
        job_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(jobs)")}
        if "download_dir" not in job_cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN download_dir TEXT")
```

- [ ] **Step 5: Add `download_dir` to the `Job` dataclass**

In `src/rrs/store/db.py`, add the field to `Job` (after `source_path`):

```python
@dataclass(frozen=True)
class Job:
    id: int
    url: str
    title: str | None
    duration_sec: float | None
    source_path: str | None
    download_dir: str | None
    status: JobStatus
    error: str | None
```

- [ ] **Step 6: Populate `download_dir` in `_row_to_job`**

In `src/rrs/store/db.py`, update `_row_to_job` (add the field after `source_path`):

```python
    @staticmethod
    def _row_to_job(r: sqlite3.Row) -> Job:
        return Job(
            id=r["id"],
            url=r["url"],
            title=r["title"],
            duration_sec=r["duration_sec"],
            source_path=r["source_path"],
            download_dir=r["download_dir"],
            status=JobStatus(r["status"]),
            error=r["error"],
        )
```

- [ ] **Step 7: Add the setter and the claims query**

In `src/rrs/store/db.py`, add to the `# ---- jobs ----` section (e.g. after `set_job_source`):

```python
    def set_download_dir(self, job_id: int, path: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET download_dir = ? WHERE id = ?", (path, job_id)
        )
        self._conn.commit()

    def claimed_download_dirs(self, exclude_job_id: int) -> set[str]:
        """All non-null download_dir values claimed by jobs other than the given one."""
        cur = self._conn.execute(
            "SELECT download_dir FROM jobs WHERE download_dir IS NOT NULL AND id != ?",
            (exclude_job_id,),
        )
        return {r["download_dir"] for r in cur.fetchall()}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all db tests, including the new four).

- [ ] **Step 9: Commit**

```bash
git add src/rrs/store/schema.sql src/rrs/store/db.py tests/test_db.py
git commit -m "feat: add jobs.download_dir column + claims query"
```

---

## Task 2: `resolve_download_dir` (replace `downloads_dir`)

**Files:**
- Modify: `src/rrs/pipeline/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_jobs.py`, replace the existing `test_downloads_dir_layout` (lines ~108–111) with these tests, and update the import block at the top (change `downloads_dir` to `resolve_download_dir`):

```python
def test_resolve_download_dir_clean_name_when_free(db, tmp_path):
    job_id = db.create_job(url="x")
    db.set_job_source(job_id, title="My Video", duration_sec=1.0, source_path="/s.mp4")
    job = db.get_job(job_id)
    d = resolve_download_dir(db, tmp_path, job)
    assert d == tmp_path / "downloads" / "My Video"
    # Persisted on the job row:
    assert db.get_job(job_id).download_dir == str(d)


def test_resolve_download_dir_stable_on_repeat(db, tmp_path):
    job_id = db.create_job(url="x")
    db.set_job_source(job_id, title="My Video", duration_sec=1.0, source_path="/s.mp4")
    first = resolve_download_dir(db, tmp_path, db.get_job(job_id))
    second = resolve_download_dir(db, tmp_path, db.get_job(job_id))
    assert first == second


def test_resolve_download_dir_suffixes_when_dir_exists_on_disk(db, tmp_path):
    # Simulate a leftover folder from a prior (deleted) job.
    (tmp_path / "downloads" / "My Video").mkdir(parents=True)
    job_id = db.create_job(url="x")
    db.set_job_source(job_id, title="My Video", duration_sec=1.0, source_path="/s.mp4")
    d = resolve_download_dir(db, tmp_path, db.get_job(job_id))
    assert d == tmp_path / "downloads" / "My Video (2)"


def test_resolve_download_dir_suffixes_when_claimed_by_other_job(db, tmp_path):
    other = db.create_job(url="o")
    db.set_download_dir(other, str(tmp_path / "downloads" / "My Video"))
    job_id = db.create_job(url="x")
    db.set_job_source(job_id, title="My Video", duration_sec=1.0, source_path="/s.mp4")
    d = resolve_download_dir(db, tmp_path, db.get_job(job_id))
    assert d == tmp_path / "downloads" / "My Video (2)"


def test_resolve_download_dir_empty_title_falls_back_to_job_id(db, tmp_path):
    job_id = db.create_job(url="x")  # title stays None
    job = db.get_job(job_id)
    d = resolve_download_dir(db, tmp_path, job)
    assert d == tmp_path / "downloads" / f"job-{job_id}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jobs.py -k resolve_download_dir -v`
Expected: FAIL — `resolve_download_dir` not importable.

- [ ] **Step 3: Replace `downloads_dir` with `resolve_download_dir`**

In `src/rrs/pipeline/jobs.py`, delete the `downloads_dir` function and add (keep `safe_dirname` as-is; add a `Database` import — the file already imports `Database` from `rrs.store.db`):

```python
def resolve_download_dir(db: Database, data_dir: Path, job) -> Path:
    """Return the job's download folder, assigning + persisting it on first call.

    Prefers the clean title-based name; appends ' (2)', ' (3)', … only when that
    name is already taken by another job — taken meaning it exists on disk (e.g. a
    leftover from a deleted job) or another job's row claims it. The choice is
    stored on the job so OPEN FOLDER and the download writers always agree."""
    if job.download_dir:
        return Path(job.download_dir)

    root = Path(data_dir) / "downloads"
    base = safe_dirname(job.title, job.id)
    claimed = db.claimed_download_dirs(exclude_job_id=job.id)

    candidate = root / base
    n = 2
    while str(candidate) in claimed or candidate.exists():
        candidate = root / f"{base} ({n})"
        n += 1

    db.set_download_dir(job.id, str(candidate))
    return candidate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_jobs.py -k resolve_download_dir -v`
Expected: PASS (all five).

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/jobs.py tests/test_jobs.py
git commit -m "feat: collision-safe resolve_download_dir replacing downloads_dir"
```

---

## Task 3: `next_extra_path` helper

**Files:**
- Modify: `src/rrs/pipeline/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py` (and add `next_extra_path` to the import block at the top):

```python
def test_next_extra_path_numbers_sequentially(tmp_path):
    folder = tmp_path / "downloads" / "My Video"
    folder.mkdir(parents=True)
    assert next_extra_path(folder) == folder / "extra-01.mp4"
    (folder / "extra-01.mp4").touch()
    assert next_extra_path(folder) == folder / "extra-02.mp4"
    # Gaps are ignored — numbering continues past the highest existing index:
    (folder / "extra-05.mp4").touch()
    assert next_extra_path(folder) == folder / "extra-06.mp4"


def test_next_extra_path_ignores_scene_clips(tmp_path):
    folder = tmp_path / "downloads" / "My Video"
    folder.mkdir(parents=True)
    (folder / "scene-01.mp4").touch()
    assert next_extra_path(folder) == folder / "extra-01.mp4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jobs.py -k next_extra_path -v`
Expected: FAIL — `next_extra_path` not importable.

- [ ] **Step 3: Implement the helper**

In `src/rrs/pipeline/jobs.py`, add (place near `resolve_download_dir`; add `import re` if not already present — it is):

```python
def next_extra_path(folder: Path) -> Path:
    """Return the next free `extra-NN.mp4` in `folder` (numbering past the highest
    existing index, so gaps are never reused)."""
    highest = 0
    if folder.exists():
        for p in folder.glob("extra-*.mp4"):
            m = re.fullmatch(r"extra-(\d+)", p.stem)
            if m:
                highest = max(highest, int(m.group(1)))
    return folder / f"extra-{highest + 1:02d}.mp4"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jobs.py -k next_extra_path -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/jobs.py tests/test_jobs.py
git commit -m "feat: next_extra_path helper for extra clip numbering"
```

---

## Task 4: Wire `pages.py` scene download + open-folder to `resolve_download_dir`

**Files:**
- Modify: `src/rrs/ui/pages.py`

- [ ] **Step 1: Update the import**

In `src/rrs/ui/pages.py`, change the jobs import (line ~19) from:

```python
from rrs.pipeline.jobs import downloads_dir, job_paths, run_pre_interactive_pipeline
```

to:

```python
from rrs.pipeline.jobs import (
    job_paths,
    next_extra_path,
    resolve_download_dir,
    run_pre_interactive_pipeline,
)
```

- [ ] **Step 2: Update `download_source_for_scene`**

In `src/rrs/ui/pages.py`, replace the `out_dir` line inside `download_source_for_scene` (line ~219):

```python
    out_dir = downloads_dir(data_dir, job.title, job.id)
```

with:

```python
    out_dir = resolve_download_dir(db, data_dir, job)
```

- [ ] **Step 3: Update `_open_downloads_folder` to take the db**

In `src/rrs/ui/pages.py`, change the signature and body of `_open_downloads_folder` (line ~229):

```python
def _open_downloads_folder(db: Database, data_dir: Path, job: Job) -> None:
    """Reveal the job's downloads folder in the OS file manager (local app)."""
    folder = resolve_download_dir(db, data_dir, job)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except OSError as exc:
        ui.notify(f"could not open folder: {exc}", type="negative")
```

- [ ] **Step 4: Update the `on_open_folder` callback wiring**

In `src/rrs/ui/pages.py`, inside `_render_scene_list`, change the callback (line ~148) from:

```python
            on_open_folder=lambda: _open_downloads_folder(cfg.data_dir, job),
```

to:

```python
            on_open_folder=lambda: _open_downloads_folder(db, cfg.data_dir, job),
```

- [ ] **Step 5: Verify the app imports and the suite still passes**

Run: `python -c "import rrs.ui.pages"` then `pytest -q`
Expected: import succeeds; full suite PASSES (no remaining `downloads_dir` references).

- [ ] **Step 6: Commit**

```bash
git add src/rrs/ui/pages.py
git commit -m "refactor: use resolve_download_dir for scene downloads + open folder"
```

---

## Task 5: Extra-clip downloader (F6)

**Files:**
- Modify: `src/rrs/ui/pages.py`
- Modify: `src/rrs/ui/components.py`
- Test: `tests/test_pages_downloads.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_pages_downloads.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from rrs.pipeline.download import DownloadResult
from rrs.store.db import JobStatus, open_db
from rrs.ui.pages import download_extra_clip


@pytest.fixture
def db():
    return open_db(":memory:")


@pytest.mark.asyncio
async def test_download_extra_clip_numbers_into_job_folder(db, tmp_path):
    job_id = db.create_job(url="ranking")
    db.set_job_source(job_id, title="My Video", duration_sec=1.0, source_path="/s.mp4")
    db.update_job_status(job_id, JobStatus.INTERACTIVE)

    def fake_download(url, out_path, max_height, progress_hook=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.touch()
        return DownloadResult(path=out_path, title="clip", duration_sec=3.0)

    with patch("rrs.ui.pages.download_video", side_effect=fake_download):
        name1 = await download_extra_clip(db, tmp_path, "https://clip/1")
        name2 = await download_extra_clip(db, tmp_path, "https://clip/2")

    folder = tmp_path / "downloads" / "My Video"
    assert name1 == "extra-01.mp4"
    assert name2 == "extra-02.mp4"
    assert (folder / "extra-01.mp4").exists()
    assert (folder / "extra-02.mp4").exists()


@pytest.mark.asyncio
async def test_download_extra_clip_raises_without_active_job(db, tmp_path):
    with pytest.raises(RuntimeError):
        await download_extra_clip(db, tmp_path, "https://clip/1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pages_downloads.py -v`
Expected: FAIL — `download_extra_clip` not defined.

- [ ] **Step 3: Implement `download_extra_clip`**

In `src/rrs/ui/pages.py`, add after `download_source_for_scene` (it reuses the existing `_find_active_job`, `next_extra_path`, `resolve_download_dir`, and `download_video`):

```python
async def download_extra_clip(db: Database, data_dir: Path, url: str) -> str:
    """Download an arbitrary clip into the active job's folder as extra-NN.mp4.

    Returns the saved filename. Raises (e.g. DownloadError) on failure so the
    caller can show it inline; raises RuntimeError if there is no active job."""
    job = _find_active_job(db)
    if job is None:
        raise RuntimeError("no active job")
    out_dir = resolve_download_dir(db, data_dir, job)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = next_extra_path(out_dir)
    result = await asyncio.to_thread(download_video, url, out, None)
    return Path(result.path).name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pages_downloads.py -v`
Expected: PASS (both).

- [ ] **Step 5: Add the `render_extra_downloader` component**

In `src/rrs/ui/components.py`, add (mirrors `_render_download_row`'s busy/✓/✗ status pattern; uses the existing `html_button` and `_download_status_html`):

```python
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
```

- [ ] **Step 6: Render it at the bottom of the scene list**

In `src/rrs/ui/components.py`, ensure `render_extra_downloader` is exported (it is a module-level def, so importing by name works). Then in `src/rrs/ui/pages.py`:

Update the components import (line ~21):

```python
from rrs.ui.components import html_button, render_extra_downloader, render_scene_card
```

At the end of `_render_scene_list`, after the `for scene in scenes:` loop, add:

```python
    render_extra_downloader(
        on_download=lambda url: download_extra_clip(db, cfg.data_dir, url)
    )
```

- [ ] **Step 7: Add a path label so testers can see where files go (F3)**

In `src/rrs/ui/pages.py`, inside `_render_scene_list`, just before the `render_extra_downloader(...)` call, show the resolved folder path as text:

```python
    folder = resolve_download_dir(db, cfg.data_dir, job)
    ui.html(
        f'<div class="rrs-meta" style="margin-top:10px">Downloads → '
        f"{html.escape(str(folder))}</div>"
    )
```

Add `import html` to the top of `src/rrs/ui/pages.py` if not already present.

- [ ] **Step 8: Verify import + full suite**

Run: `python -c "import rrs.ui.pages"` then `pytest -q`
Expected: import succeeds; full suite PASSES.

- [ ] **Step 9: Manual smoke check (optional but recommended)**

Run: `rrs` (or `python -m rrs.main`), process a short video, then use the "Download an extra clip" box at the bottom; confirm `extra-01.mp4` lands in the job folder shown by the path label and OPEN FOLDER.

- [ ] **Step 10: Commit**

```bash
git add src/rrs/ui/pages.py src/rrs/ui/components.py tests/test_pages_downloads.py
git commit -m "feat: extra-clip downloader + downloads path label (F6/F3)"
```

---

## Task 6: Update TODO.txt

**Files:**
- Modify: `TODO.txt`

- [ ] **Step 1: Mark Group B done**

In `TODO.txt`, update the Group B header to note completion, e.g. change the divider line/header to:

```
GROUP B — Download management  [DONE]
```

- [ ] **Step 2: Commit**

```bash
git add TODO.txt
git commit -m "docs: mark TODO Group B (download management) done"
```

---

## Self-review notes

- **Spec coverage:** F3 → Tasks 2 + 5 (stable folder + visible path label); F7 → Tasks 1 + 2 (disk-and-DB collision check); F6 → Tasks 3 + 5 (extra downloader). All three covered.
- **Type consistency:** `resolve_download_dir(db, data_dir, job)`, `next_extra_path(folder)`, `download_extra_clip(db, data_dir, url)`, `set_download_dir(job_id, path)`, `claimed_download_dirs(exclude_job_id)`, and the `Job.download_dir` field are referenced with identical signatures everywhere.
- **CSS:** `render_extra_downloader` reuses existing classes (`rrs-download`, `rrs-download-row`, `rrs-input`, `rrs-download-status`, `rrs-label`, `rrs-meta`); the extra `rrs-extra-download` class is optional styling with no behaviour attached, so no stylesheet change is required for function.
```
