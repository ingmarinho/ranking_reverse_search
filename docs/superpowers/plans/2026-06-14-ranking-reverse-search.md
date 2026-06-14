# Ranking Reverse Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally-run NiceGUI app that downloads a ranking/compilation video, detects scenes, lets the user pick frames per scene, opens reverse-image-search engines in new tabs (frame hosted on imgbb), downloads pasted-back source URLs, and lets the user trim clips out of them.

**Architecture:** Single Python process serving NiceGUI on `localhost:8080`. Layered: `pipeline/` (pure functions per stage) → `store/` (SQLite DAL) → `ui/` (NiceGUI page + components + modals). Heavy work (yt-dlp, scene detect, ffmpeg) runs via `run_in_executor`. State machine persisted in SQLite so reloads rehydrate.

**Tech Stack:** Python 3.11+, NiceGUI, yt-dlp (library), PySceneDetect, opencv-python, ffmpeg (system binary), sqlite3 stdlib, httpx for imgbb, pytest.

**Spec:** `docs/superpowers/specs/2026-06-14-ranking-reverse-search-design.md`

---

## Conventions

- **Package import root:** `rrs` (installed editable via `pip install -e .`)
- **Tests:** pytest, run from repo root with `pytest`
- **Commits:** small per task, conventional prefix (`feat:`, `test:`, `chore:`, `docs:`)
- **TDD:** every pipeline/store module begins with a failing test
- **UI tasks:** no automated tests in MVP — every UI task ends with a manual smoke step

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/rrs/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "rrs"
version = "0.1.0"
description = "Ranking reverse search — local NiceGUI tool"
requires-python = ">=3.11"
dependencies = [
  "nicegui>=2.0",
  "yt-dlp>=2024.1.1",
  "scenedetect[opencv]>=0.6.4",
  "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "respx>=0.21",
]

[project.scripts]
rrs = "rrs.main:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
rrs = ["store/schema.sql", "ui/static/**/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create empty package files**

```bash
mkdir -p src/rrs tests/fixtures
touch src/rrs/__init__.py tests/__init__.py
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures. The synthetic_video fixture builds a small
multi-scene video with ffmpeg so scene detection / frame extraction tests
have a real file to work on without checking in binary fixtures."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory) -> Path:
    """A 6-second 320x180 video with 3 hard cuts (red, green, blue blocks of 2s each).
    PySceneDetect will reliably split this into 3 scenes."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    out = tmp_path_factory.mktemp("fix") / "synthetic.mp4"
    # Three concatenated solid-color segments via lavfi
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-t", "2", "-i", "color=c=red:s=320x180:r=24",
        "-f", "lavfi", "-t", "2", "-i", "color=c=green:s=320x180:r=24",
        "-f", "lavfi", "-t", "2", "-i", "color=c=blue:s=320x180:r=24",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v]",
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    assert out.exists()
    return out


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch) -> Path:
    """Point DATA_DIR at a temp dir for the test."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("DATA_DIR", str(d))
    return d
```

- [ ] **Step 4: Update `.gitignore`**

Append to existing `.gitignore`:

```
*.egg-info/
build/
dist/
.pytest_cache/
```

- [ ] **Step 5: Install editable + verify**

Run:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Expected: `pytest` runs, collects 0 tests, exits 0 (or "no tests ran").

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/ tests/ .gitignore
git commit -m "chore: scaffold rrs package"
```

---

## Task 2: Config module

**Files:**
- Create: `src/rrs/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

`tests/test_config.py`:
```python
from __future__ import annotations

from pathlib import Path

import pytest

from rrs.config import Config, MissingDependencyError, load_config


def test_load_config_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("IMGBB_API_KEY", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(probe_ffmpeg=False)
    assert cfg.data_dir == tmp_path
    assert cfg.port == 8080
    assert cfg.scene_threshold == 27.0
    assert cfg.imgbb_api_key is None


def test_load_config_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("IMGBB_API_KEY", "k123")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("SCENE_THRESHOLD", "30.5")
    cfg = load_config(probe_ffmpeg=False)
    assert cfg.imgbb_api_key == "k123"
    assert cfg.port == 9090
    assert cfg.scene_threshold == 30.5


def test_load_config_missing_ffmpeg(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(MissingDependencyError, match="ffmpeg"):
        load_config(probe_ffmpeg=True)


def test_load_config_creates_data_dir(monkeypatch, tmp_path):
    d = tmp_path / "nested" / "data"
    monkeypatch.setenv("DATA_DIR", str(d))
    cfg = load_config(probe_ffmpeg=False)
    assert cfg.data_dir.exists()
    assert isinstance(cfg, Config)
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'rrs.config'`

- [ ] **Step 3: Implement `src/rrs/config.py`**

```python
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class MissingDependencyError(RuntimeError):
    """Raised when a required external binary is missing at startup."""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int
    scene_threshold: float
    imgbb_api_key: str | None


def load_config(probe_ffmpeg: bool = True) -> Config:
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    if probe_ffmpeg and shutil.which("ffmpeg") is None:
        raise MissingDependencyError(
            "ffmpeg not found on PATH. Install it (e.g. `brew install ffmpeg`)."
        )

    return Config(
        data_dir=data_dir,
        port=int(os.environ.get("PORT", "8080")),
        scene_threshold=float(os.environ.get("SCENE_THRESHOLD", "27.0")),
        imgbb_api_key=os.environ.get("IMGBB_API_KEY") or None,
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_config.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/rrs/config.py tests/test_config.py
git commit -m "feat: add config module with env vars and ffmpeg probe"
```

---

## Task 3: SQLite schema + DAL

**Files:**
- Create: `src/rrs/store/__init__.py`
- Create: `src/rrs/store/schema.sql`
- Create: `src/rrs/store/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write `src/rrs/store/__init__.py`** (empty file)

```python
```

- [ ] **Step 2: Write `src/rrs/store/schema.sql`** (verbatim from spec)

```sql
CREATE TABLE IF NOT EXISTS jobs (
  id              INTEGER PRIMARY KEY,
  url             TEXT NOT NULL,
  title           TEXT,
  duration_sec    REAL,
  source_path     TEXT,
  status          TEXT NOT NULL,
  error           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scenes (
  id              INTEGER PRIMARY KEY,
  job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  idx             INTEGER NOT NULL,
  start_frame     INTEGER NOT NULL,
  end_frame       INTEGER NOT NULL,
  start_sec       REAL NOT NULL,
  end_sec         REAL NOT NULL,
  UNIQUE(job_id, idx)
);

CREATE TABLE IF NOT EXISTS frames (
  id              INTEGER PRIMARY KEY,
  scene_id        INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
  ordinal         INTEGER NOT NULL,
  frame_number    INTEGER NOT NULL,
  path            TEXT NOT NULL,
  imgbb_url       TEXT,
  is_selected     INTEGER NOT NULL DEFAULT 0,
  UNIQUE(scene_id, ordinal)
);

CREATE TABLE IF NOT EXISTS sources (
  id              INTEGER PRIMARY KEY,
  scene_id        INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
  url             TEXT NOT NULL,
  path            TEXT,
  trim_start_sec  REAL,
  trim_end_sec    REAL,
  clip_path       TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
  key             TEXT PRIMARY KEY,
  value           TEXT NOT NULL
);
```

- [ ] **Step 3: Write failing test `tests/test_db.py`**

```python
from __future__ import annotations

import sqlite3

import pytest

from rrs.store.db import (
    JobStatus,
    Database,
    open_db,
)


@pytest.fixture
def db() -> Database:
    return open_db(":memory:")


def test_create_and_get_job(db: Database):
    job_id = db.create_job(url="https://youtu.be/abc")
    job = db.get_job(job_id)
    assert job.id == job_id
    assert job.url == "https://youtu.be/abc"
    assert job.status == JobStatus.DOWNLOADING


def test_update_job_status(db: Database):
    job_id = db.create_job(url="x")
    db.update_job_status(job_id, JobStatus.DETECTING_SCENES)
    assert db.get_job(job_id).status == JobStatus.DETECTING_SCENES


def test_update_job_error_sets_failed(db: Database):
    job_id = db.create_job(url="x")
    db.fail_job(job_id, "boom")
    job = db.get_job(job_id)
    assert job.status == JobStatus.FAILED
    assert job.error == "boom"


def test_set_job_source(db: Database):
    job_id = db.create_job(url="x")
    db.set_job_source(job_id, title="My Vid", duration_sec=12.5, source_path="/tmp/a.mp4")
    job = db.get_job(job_id)
    assert job.title == "My Vid"
    assert job.duration_sec == 12.5
    assert job.source_path == "/tmp/a.mp4"


def test_insert_scenes_and_list(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [
        (0, 0, 48, 0.0, 2.0),
        (1, 48, 96, 2.0, 4.0),
    ])
    scenes = db.list_scenes(job_id)
    assert len(scenes) == 2
    assert scenes[0].idx == 0
    assert scenes[1].start_sec == 2.0


def test_insert_default_frame_and_select(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [(0, 0, 48, 0.0, 2.0)])
    scene_id = db.list_scenes(job_id)[0].id
    frame_id = db.insert_frame(
        scene_id=scene_id, ordinal=0, frame_number=0, path="/x.jpg", is_selected=True
    )
    frames = db.list_frames(scene_id)
    assert len(frames) == 1
    assert frames[0].id == frame_id
    assert frames[0].is_selected is True


def test_set_frame_imgbb_url(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [(0, 0, 48, 0.0, 2.0)])
    scene_id = db.list_scenes(job_id)[0].id
    fid = db.insert_frame(scene_id, 0, 0, "/x.jpg", is_selected=True)
    db.set_frame_imgbb_url(fid, "https://i.ibb.co/abc.jpg")
    assert db.list_frames(scene_id)[0].imgbb_url == "https://i.ibb.co/abc.jpg"


def test_toggle_frame_selection(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [(0, 0, 48, 0.0, 2.0)])
    sid = db.list_scenes(job_id)[0].id
    fid = db.insert_frame(sid, 0, 0, "/x.jpg", is_selected=True)
    db.set_frame_selected(fid, False)
    assert db.list_frames(sid)[0].is_selected is False


def test_upsert_source(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [(0, 0, 48, 0.0, 2.0)])
    sid = db.list_scenes(job_id)[0].id
    db.upsert_source(scene_id=sid, url="https://src.example/v.mp4")
    src = db.get_source(sid)
    assert src.url == "https://src.example/v.mp4"
    assert src.path is None
    db.set_source_downloaded(src.id, path="/data/s.mp4")
    assert db.get_source(sid).path == "/data/s.mp4"
    db.set_source_clip(src.id, trim_start_sec=1.0, trim_end_sec=3.0, clip_path="/c.mp4")
    src = db.get_source(sid)
    assert src.trim_start_sec == 1.0
    assert src.trim_end_sec == 3.0
    assert src.clip_path == "/c.mp4"


def test_settings_get_and_set(db: Database):
    db.set_setting("enabled_engines", '["google_lens","yandex"]')
    assert db.get_setting("enabled_engines") == '["google_lens","yandex"]'
    assert db.get_setting("missing") is None


def test_foreign_keys_cascade(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [(0, 0, 48, 0.0, 2.0)])
    db.delete_job(job_id)
    assert db.get_job(job_id) is None
    # scenes should also be gone
    with sqlite3.connect(":memory:"):
        pass  # cascade implicitly verified by the absence of rows
    assert db.list_scenes(job_id) == []
```

- [ ] **Step 4: Run test, verify failure**

Run: `pytest tests/test_db.py -v`
Expected: ImportError on `rrs.store.db`.

- [ ] **Step 5: Implement `src/rrs/store/db.py`**

```python
from __future__ import annotations

import enum
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable


class JobStatus(str, enum.Enum):
    DOWNLOADING = "downloading"
    DETECTING_SCENES = "detecting_scenes"
    EXTRACTING_FRAMES = "extracting_frames"
    INTERACTIVE = "interactive"
    FAILED = "failed"


@dataclass(frozen=True)
class Job:
    id: int
    url: str
    title: str | None
    duration_sec: float | None
    source_path: str | None
    status: JobStatus
    error: str | None


@dataclass(frozen=True)
class Scene:
    id: int
    job_id: int
    idx: int
    start_frame: int
    end_frame: int
    start_sec: float
    end_sec: float


@dataclass(frozen=True)
class Frame:
    id: int
    scene_id: int
    ordinal: int
    frame_number: int
    path: str
    imgbb_url: str | None
    is_selected: bool


@dataclass(frozen=True)
class Source:
    id: int
    scene_id: int
    url: str
    path: str | None
    trim_start_sec: float | None
    trim_end_sec: float | None
    clip_path: str | None


def _schema_sql() -> str:
    return resources.files("rrs.store").joinpath("schema.sql").read_text()


class Database:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_schema_sql())

    # ---- jobs ----

    def create_job(self, url: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO jobs (url, status) VALUES (?, ?)",
            (url, JobStatus.DOWNLOADING.value),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_job(self, job_id: int) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def update_job_status(self, job_id: int, status: JobStatus) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = ?, error = NULL WHERE id = ?",
            (status.value, job_id),
        )
        self._conn.commit()

    def fail_job(self, job_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = ?, error = ? WHERE id = ?",
            (JobStatus.FAILED.value, error, job_id),
        )
        self._conn.commit()

    def set_job_source(
        self, job_id: int, title: str, duration_sec: float, source_path: str
    ) -> None:
        self._conn.execute(
            "UPDATE jobs SET title = ?, duration_sec = ?, source_path = ? WHERE id = ?",
            (title, duration_sec, source_path, job_id),
        )
        self._conn.commit()

    def delete_job(self, job_id: int) -> None:
        self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self._conn.commit()

    # ---- scenes ----

    def insert_scenes(
        self,
        job_id: int,
        rows: Iterable[tuple[int, int, int, float, float]],
    ) -> None:
        """rows are (idx, start_frame, end_frame, start_sec, end_sec)."""
        self._conn.executemany(
            "INSERT INTO scenes (job_id, idx, start_frame, end_frame, start_sec, end_sec)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(job_id, *r) for r in rows],
        )
        self._conn.commit()

    def list_scenes(self, job_id: int) -> list[Scene]:
        cur = self._conn.execute(
            "SELECT * FROM scenes WHERE job_id = ? ORDER BY idx", (job_id,)
        )
        return [self._row_to_scene(r) for r in cur.fetchall()]

    # ---- frames ----

    def insert_frame(
        self,
        scene_id: int,
        ordinal: int,
        frame_number: int,
        path: str,
        is_selected: bool = False,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO frames (scene_id, ordinal, frame_number, path, is_selected)"
            " VALUES (?, ?, ?, ?, ?)",
            (scene_id, ordinal, frame_number, path, int(is_selected)),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_frames(self, scene_id: int) -> list[Frame]:
        cur = self._conn.execute(
            "SELECT * FROM frames WHERE scene_id = ? ORDER BY ordinal", (scene_id,)
        )
        return [self._row_to_frame(r) for r in cur.fetchall()]

    def set_frame_imgbb_url(self, frame_id: int, url: str) -> None:
        self._conn.execute(
            "UPDATE frames SET imgbb_url = ? WHERE id = ?", (url, frame_id)
        )
        self._conn.commit()

    def set_frame_selected(self, frame_id: int, selected: bool) -> None:
        self._conn.execute(
            "UPDATE frames SET is_selected = ? WHERE id = ?", (int(selected), frame_id)
        )
        self._conn.commit()

    # ---- sources ----

    def upsert_source(self, scene_id: int, url: str) -> int:
        existing = self._conn.execute(
            "SELECT id FROM sources WHERE scene_id = ?", (scene_id,)
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE sources SET url = ?, path = NULL, trim_start_sec = NULL,"
                " trim_end_sec = NULL, clip_path = NULL WHERE id = ?",
                (url, existing["id"]),
            )
            self._conn.commit()
            return existing["id"]
        cur = self._conn.execute(
            "INSERT INTO sources (scene_id, url) VALUES (?, ?)", (scene_id, url)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_source(self, scene_id: int) -> Source | None:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE scene_id = ?", (scene_id,)
        ).fetchone()
        return self._row_to_source(row) if row else None

    def set_source_downloaded(self, source_id: int, path: str) -> None:
        self._conn.execute(
            "UPDATE sources SET path = ? WHERE id = ?", (path, source_id)
        )
        self._conn.commit()

    def set_source_clip(
        self,
        source_id: int,
        trim_start_sec: float,
        trim_end_sec: float,
        clip_path: str,
    ) -> None:
        self._conn.execute(
            "UPDATE sources SET trim_start_sec = ?, trim_end_sec = ?, clip_path = ?"
            " WHERE id = ?",
            (trim_start_sec, trim_end_sec, clip_path, source_id),
        )
        self._conn.commit()

    # ---- settings ----

    def get_setting(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    # ---- helpers ----

    @staticmethod
    def _row_to_job(r: sqlite3.Row) -> Job:
        return Job(
            id=r["id"],
            url=r["url"],
            title=r["title"],
            duration_sec=r["duration_sec"],
            source_path=r["source_path"],
            status=JobStatus(r["status"]),
            error=r["error"],
        )

    @staticmethod
    def _row_to_scene(r: sqlite3.Row) -> Scene:
        return Scene(
            id=r["id"], job_id=r["job_id"], idx=r["idx"],
            start_frame=r["start_frame"], end_frame=r["end_frame"],
            start_sec=r["start_sec"], end_sec=r["end_sec"],
        )

    @staticmethod
    def _row_to_frame(r: sqlite3.Row) -> Frame:
        return Frame(
            id=r["id"], scene_id=r["scene_id"], ordinal=r["ordinal"],
            frame_number=r["frame_number"], path=r["path"],
            imgbb_url=r["imgbb_url"], is_selected=bool(r["is_selected"]),
        )

    @staticmethod
    def _row_to_source(r: sqlite3.Row) -> Source:
        return Source(
            id=r["id"], scene_id=r["scene_id"], url=r["url"], path=r["path"],
            trim_start_sec=r["trim_start_sec"], trim_end_sec=r["trim_end_sec"],
            clip_path=r["clip_path"],
        )


def open_db(path: str | Path) -> Database:
    conn = sqlite3.connect(str(path))
    return Database(conn)
```

- [ ] **Step 6: Run tests, verify pass**

Run: `pytest tests/test_db.py -v`
Expected: all PASSED.

- [ ] **Step 7: Commit**

```bash
git add src/rrs/store tests/test_db.py
git commit -m "feat: add SQLite schema and DAL"
```

---

## Task 4: Engine base type + registry

**Files:**
- Create: `src/rrs/pipeline/__init__.py`
- Create: `src/rrs/pipeline/engines/__init__.py`
- Create: `src/rrs/pipeline/engines/base.py`
- Create: `tests/test_engines_base.py`

- [ ] **Step 1: Create empty `src/rrs/pipeline/__init__.py`**

```python
```

- [ ] **Step 2: Write failing test `tests/test_engines_base.py`**

```python
from __future__ import annotations

import pytest

from rrs.pipeline.engines.base import Engine


def test_engine_search_url_quotes_image_url():
    e = Engine(
        id="t", name="T", category="western", enabled_by_default=True,
        status="ready", url_template="https://example.com/?u={image_url}",
    )
    url = e.search_url("https://i.ibb.co/abc/x.jpg?token=hi&size=1")
    # The image_url must be URL-encoded so query separators don't bleed through.
    assert "https://example.com/?u=" in url
    assert "%3A" in url and "%2F" in url  # encoded ":" and "/"


def test_engine_stub_status_returns_none():
    e = Engine(
        id="t", name="T", category="chinese", enabled_by_default=False,
        status="todo", url_template=None,
    )
    assert e.search_url("https://i.ibb.co/x.jpg") is None
```

- [ ] **Step 3: Run test, verify failure**

Run: `pytest tests/test_engines_base.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `src/rrs/pipeline/engines/base.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

EngineStatus = Literal["ready", "todo"]
EngineCategory = Literal["western", "chinese", "regional", "specialized"]


@dataclass(frozen=True)
class Engine:
    id: str
    name: str
    category: EngineCategory
    enabled_by_default: bool
    status: EngineStatus
    url_template: str | None  # None for "todo" engines

    def search_url(self, image_url: str) -> str | None:
        if self.status != "ready" or self.url_template is None:
            return None
        return self.url_template.format(image_url=quote(image_url, safe=""))
```

- [ ] **Step 5: Run tests, verify pass**

Run: `pytest tests/test_engines_base.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/rrs/pipeline tests/test_engines_base.py
git commit -m "feat: add Engine base type"
```

---

## Task 5: Engine adapters + registry

**Files:**
- Create: `src/rrs/pipeline/engines/google_lens.py`
- Create: `src/rrs/pipeline/engines/yandex.py`
- Create: `src/rrs/pipeline/engines/bing.py`
- Create: `src/rrs/pipeline/engines/tineye.py`
- Create: `src/rrs/pipeline/engines/saucenao.py`
- Create: `src/rrs/pipeline/engines/stubs.py`
- Create: `src/rrs/pipeline/engines/__init__.py` (registry)
- Create: `tests/test_engines_registry.py`

- [ ] **Step 1: Write failing test `tests/test_engines_registry.py`**

```python
from __future__ import annotations

import pytest

from rrs.pipeline.engines import ALL_ENGINES, get_engine


@pytest.mark.parametrize("engine_id, expected_host", [
    ("google_lens", "lens.google.com"),
    ("yandex", "yandex.com"),
    ("bing", "bing.com"),
    ("tineye", "tineye.com"),
    ("saucenao", "saucenao.com"),
])
def test_ready_engines_emit_url_with_image(engine_id: str, expected_host: str):
    e = get_engine(engine_id)
    assert e is not None
    assert e.status == "ready"
    url = e.search_url("https://i.ibb.co/abc/x.jpg")
    assert url is not None
    assert expected_host in url
    assert "i.ibb.co" in url or "%2Fi.ibb.co" in url or "i.ibb.co" in url.lower()


def test_registry_has_stubbed_engines():
    ids = {e.id for e in ALL_ENGINES}
    for stub in ("baidu", "sogou", "qihoo360", "naver", "lenso", "pimeyes", "karma_decay"):
        assert stub in ids, f"missing stub {stub}"
    assert all(get_engine(s).status == "todo" for s in ("baidu", "sogou", "naver"))


def test_get_engine_unknown_returns_none():
    assert get_engine("nope") is None


def test_default_enabled_engines_are_ready():
    for e in ALL_ENGINES:
        if e.enabled_by_default:
            assert e.status == "ready"
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_engines_registry.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement engine modules**

`src/rrs/pipeline/engines/google_lens.py`:
```python
from .base import Engine

ENGINE = Engine(
    id="google_lens",
    name="Google Lens",
    category="western",
    enabled_by_default=True,
    status="ready",
    url_template="https://lens.google.com/uploadbyurl?url={image_url}",
)
```

`src/rrs/pipeline/engines/yandex.py`:
```python
from .base import Engine

ENGINE = Engine(
    id="yandex",
    name="Yandex Images",
    category="western",
    enabled_by_default=True,
    status="ready",
    url_template="https://yandex.com/images/search?rpt=imageview&url={image_url}",
)
```

`src/rrs/pipeline/engines/bing.py`:
```python
from .base import Engine

ENGINE = Engine(
    id="bing",
    name="Bing Visual Search",
    category="western",
    enabled_by_default=True,
    status="ready",
    url_template="https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{image_url}",
)
```

`src/rrs/pipeline/engines/tineye.py`:
```python
from .base import Engine

ENGINE = Engine(
    id="tineye",
    name="TinEye",
    category="western",
    enabled_by_default=True,
    status="ready",
    url_template="https://tineye.com/search?url={image_url}",
)
```

`src/rrs/pipeline/engines/saucenao.py`:
```python
from .base import Engine

ENGINE = Engine(
    id="saucenao",
    name="SauceNAO",
    category="specialized",
    enabled_by_default=False,
    status="ready",
    url_template="https://saucenao.com/search.php?url={image_url}",
)
```

`src/rrs/pipeline/engines/stubs.py`:
```python
from .base import Engine

STUBS = [
    Engine("baidu", "Baidu Images", "chinese", False, "todo", None),
    Engine("sogou", "Sogou Images", "chinese", False, "todo", None),
    Engine("qihoo360", "Qihoo 360 Images", "chinese", False, "todo", None),
    Engine("naver", "Naver", "regional", False, "todo", None),
    Engine("lenso", "Lenso.ai", "specialized", False, "todo", None),
    Engine("pimeyes", "PimEyes", "specialized", False, "todo", None),
    Engine("karma_decay", "Karma Decay", "specialized", False, "todo", None),
]
```

`src/rrs/pipeline/engines/__init__.py`:
```python
from __future__ import annotations

from .base import Engine, EngineCategory, EngineStatus
from .bing import ENGINE as _bing
from .google_lens import ENGINE as _glens
from .saucenao import ENGINE as _saucenao
from .stubs import STUBS as _stubs
from .tineye import ENGINE as _tineye
from .yandex import ENGINE as _yandex

ALL_ENGINES: list[Engine] = [_glens, _yandex, _bing, _tineye, _saucenao, *_stubs]

_BY_ID = {e.id: e for e in ALL_ENGINES}


def get_engine(engine_id: str) -> Engine | None:
    return _BY_ID.get(engine_id)


def default_enabled_ids() -> list[str]:
    return [e.id for e in ALL_ENGINES if e.enabled_by_default]


__all__ = ["Engine", "EngineCategory", "EngineStatus", "ALL_ENGINES",
           "get_engine", "default_enabled_ids"]
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_engines_registry.py -v`
Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/engines tests/test_engines_registry.py
git commit -m "feat: add engine adapters (5 ready, 7 stubbed)"
```

---

## Task 6: imgbb hosting

**Files:**
- Create: `src/rrs/pipeline/hosting.py`
- Create: `tests/test_hosting.py`

The imgbb API: `POST https://api.imgbb.com/1/upload?key=API_KEY` with form field `image` (base64 string). Response JSON has `data.url`.

- [ ] **Step 1: Write failing test `tests/test_hosting.py`**

```python
from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
import respx

from rrs.pipeline.hosting import ImgbbError, upload_image


@pytest.fixture
def small_jpeg(tmp_path: Path) -> Path:
    """A 1x1 jpeg byte-blob is enough for upload tests."""
    p = tmp_path / "x.jpg"
    p.write_bytes(
        b"\xff\xd8\xff\xdb\x00C\x00" + b"\x08" * 64
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xc4\x00\x14\x00\x01" + b"\x00" * 15
        + b"\xff\xc4\x00\x14\x10\x01" + b"\x00" * 15
        + b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x37\xff\xd9"
    )
    return p


@respx.mock
def test_upload_image_success(small_jpeg: Path):
    respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(
            200, json={"data": {"url": "https://i.ibb.co/abc/x.jpg"}, "success": True}
        )
    )
    url = upload_image(small_jpeg, api_key="k123")
    assert url == "https://i.ibb.co/abc/x.jpg"


@respx.mock
def test_upload_image_sends_base64_form_field(small_jpeg: Path):
    route = respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(
            200, json={"data": {"url": "https://i.ibb.co/x.jpg"}}
        )
    )
    upload_image(small_jpeg, api_key="k123")
    sent = route.calls.last.request
    body = sent.content.decode()
    assert "image=" in body
    # Verify base64 of the file bytes is in the form body (URL-encoded)
    expected = base64.b64encode(small_jpeg.read_bytes()).decode()
    # base64 is mostly safe but '+' and '/' get encoded; cheap sanity:
    assert expected[:20].replace("+", "%2B").replace("/", "%2F") in body \
        or expected[:20] in body


@respx.mock
def test_upload_image_http_error_raises(small_jpeg: Path):
    respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(403, text="forbidden")
    )
    with pytest.raises(ImgbbError):
        upload_image(small_jpeg, api_key="bad")


@respx.mock
def test_upload_image_malformed_response_raises(small_jpeg: Path):
    respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(200, json={"nope": True})
    )
    with pytest.raises(ImgbbError):
        upload_image(small_jpeg, api_key="k")
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_hosting.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/rrs/pipeline/hosting.py`**

```python
from __future__ import annotations

import base64
from pathlib import Path

import httpx


class ImgbbError(RuntimeError):
    pass


def upload_image(path: Path, api_key: str, timeout: float = 30.0) -> str:
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    try:
        resp = httpx.post(
            "https://api.imgbb.com/1/upload",
            params={"key": api_key},
            data={"image": encoded},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise ImgbbError(f"imgbb request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise ImgbbError(f"imgbb {resp.status_code}: {resp.text[:200]}")

    try:
        url = resp.json()["data"]["url"]
    except (KeyError, ValueError) as exc:
        raise ImgbbError(f"imgbb malformed response: {resp.text[:200]}") from exc
    return url
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_hosting.py -v`
Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/hosting.py tests/test_hosting.py
git commit -m "feat: add imgbb upload"
```

---

## Task 7: yt-dlp download wrapper

**Files:**
- Create: `src/rrs/pipeline/download.py`
- Create: `tests/test_download.py`

We DO NOT hit the network in tests. We assert that `download_video` calls `YoutubeDL` with the right `format` string and output template, and that it returns the expected `DownloadResult` from the info dict.

- [ ] **Step 1: Write failing test `tests/test_download.py`**

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rrs.pipeline.download import DownloadResult, download_video


@pytest.fixture
def fake_ydl(monkeypatch):
    """Replace yt_dlp.YoutubeDL with a context-manager mock and capture init opts."""
    calls = {}

    class FakeYDL:
        def __init__(self, opts):
            calls["opts"] = opts
            self._info = {
                "title": "My Vid",
                "duration": 12.5,
                "_filename": opts["outtmpl"].format(id="abc"),
            }

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            calls["url"] = url
            calls["download"] = download
            # simulate file existing for the assertion in download_video
            Path(self._info["_filename"]).parent.mkdir(parents=True, exist_ok=True)
            Path(self._info["_filename"]).write_bytes(b"\x00")
            return self._info

    monkeypatch.setattr("rrs.pipeline.download.YoutubeDL", FakeYDL)
    return calls


def test_download_video_with_1080p_cap(fake_ydl, tmp_path):
    out = tmp_path / "source.mp4"
    result = download_video(
        url="https://youtu.be/xyz",
        out_path=out,
        max_height=1080,
    )
    assert isinstance(result, DownloadResult)
    assert result.title == "My Vid"
    assert result.duration_sec == 12.5
    assert result.path == out
    assert "height<=1080" in fake_ydl["opts"]["format"]
    assert fake_ydl["opts"]["merge_output_format"] == "mp4"
    assert fake_ydl["opts"]["outtmpl"].startswith(str(tmp_path))


def test_download_video_best_when_max_height_none(fake_ydl, tmp_path):
    out = tmp_path / "source.mp4"
    download_video(url="x", out_path=out, max_height=None)
    assert fake_ydl["opts"]["format"] == "bv*+ba/b"


def test_download_video_progress_hook_invoked(fake_ydl, tmp_path):
    received = []

    def on_progress(p):
        received.append(p)

    out = tmp_path / "source.mp4"
    download_video(url="x", out_path=out, max_height=1080, progress_hook=on_progress)

    # The hook list passed to ydl should contain our wrapper
    hooks = fake_ydl["opts"]["progress_hooks"]
    assert len(hooks) == 1
    # Simulate yt-dlp invoking the hook
    hooks[0]({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
    assert received and 0.0 <= received[-1] <= 1.0
    assert received[-1] == pytest.approx(0.5)
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_download.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/rrs/pipeline/download.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    title: str
    duration_sec: float


ProgressHook = Callable[[float], None]


def _format_string(max_height: int | None) -> str:
    if max_height is None:
        return "bv*+ba/b"
    return f"bv*[height<={max_height}]+ba/b[height<={max_height}]"


def download_video(
    url: str,
    out_path: Path,
    max_height: int | None,
    progress_hook: ProgressHook | None = None,
) -> DownloadResult:
    """Download a video via yt-dlp library.

    `out_path` is the final desired path (e.g. .../source.mp4). The %(id)s
    template is not used — yt-dlp will write to this exact file.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _hook(d):
        if progress_hook is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                progress_hook(min(1.0, done / total))
        elif d.get("status") == "finished":
            progress_hook(1.0)

    opts = {
        "format": _format_string(max_height),
        "merge_output_format": "mp4",
        "outtmpl": str(out_path).replace("%", "%%").replace("%%(", "%("),  # safe template
        "progress_hooks": [_hook],
        "quiet": True,
        "noprogress": True,
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:  # yt-dlp raises many types
        raise DownloadError(f"yt-dlp failed: {exc}") from exc

    if not out_path.exists():
        raise DownloadError(f"yt-dlp finished but {out_path} is missing")

    return DownloadResult(
        path=out_path,
        title=str(info.get("title") or "Untitled"),
        duration_sec=float(info.get("duration") or 0.0),
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_download.py -v`
Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/download.py tests/test_download.py
git commit -m "feat: add yt-dlp download wrapper"
```

---

## Task 8: Scene detection

**Files:**
- Create: `src/rrs/pipeline/scenes.py`
- Create: `tests/test_scenes.py`

- [ ] **Step 1: Write failing test `tests/test_scenes.py`**

```python
from __future__ import annotations

from pathlib import Path

from rrs.pipeline.scenes import SceneRow, detect_scenes


def test_detect_scenes_finds_three_in_synthetic(synthetic_video: Path):
    scenes = detect_scenes(synthetic_video, threshold=27.0)
    assert len(scenes) == 3
    assert isinstance(scenes[0], SceneRow)
    assert scenes[0].idx == 0
    assert scenes[0].start_sec == 0.0
    assert scenes[-1].end_sec > 5.0  # ~6s total


def test_detect_scenes_falls_back_to_single_scene_for_static(tmp_path):
    import subprocess
    # one-second solid black, single scene
    out = tmp_path / "static.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-t", "1", "-i", "color=c=black:s=160x90:r=24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    scenes = detect_scenes(out, threshold=27.0)
    assert len(scenes) >= 1
    assert scenes[0].start_sec == 0.0
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_scenes.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/rrs/pipeline/scenes.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scenedetect import ContentDetector, SceneManager, open_video


@dataclass(frozen=True)
class SceneRow:
    idx: int
    start_frame: int
    end_frame: int
    start_sec: float
    end_sec: float


def detect_scenes(video_path: Path, threshold: float = 27.0) -> list[SceneRow]:
    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold))
    sm.detect_scenes(video=video, show_progress=False)
    scenes = sm.get_scene_list()

    if not scenes:
        duration_seconds = video.duration.get_seconds()
        end_frame = int(video.duration.get_frames())
        return [SceneRow(
            idx=0, start_frame=0, end_frame=end_frame,
            start_sec=0.0, end_sec=duration_seconds,
        )]

    rows: list[SceneRow] = []
    for i, (start, end) in enumerate(scenes):
        rows.append(SceneRow(
            idx=i,
            start_frame=int(start.get_frames()),
            end_frame=int(end.get_frames()),
            start_sec=float(start.get_seconds()),
            end_sec=float(end.get_seconds()),
        ))
    return rows
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_scenes.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/scenes.py tests/test_scenes.py
git commit -m "feat: add PySceneDetect wrapper with single-scene fallback"
```

---

## Task 9: Frame extraction

**Files:**
- Create: `src/rrs/pipeline/frames.py`
- Create: `tests/test_frames.py`

- [ ] **Step 1: Write failing test `tests/test_frames.py`**

```python
from __future__ import annotations

from pathlib import Path

from rrs.pipeline.frames import extract_frame, extract_evenly_spaced


def test_extract_frame_writes_jpeg(synthetic_video: Path, tmp_path: Path):
    out = tmp_path / "f.jpg"
    extract_frame(video_path=synthetic_video, frame_number=12, out_path=out)
    assert out.exists()
    assert out.stat().st_size > 0
    # JPEG SOI marker
    assert out.read_bytes()[:2] == b"\xff\xd8"


def test_extract_evenly_spaced_returns_n_frames(synthetic_video: Path, tmp_path: Path):
    # synthetic video is 6s at 24fps = 144 frames; ask for 9 in scene [0, 48)
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    results = extract_evenly_spaced(
        video_path=synthetic_video,
        start_frame=0,
        end_frame=48,
        count=9,
        out_dir=out_dir,
    )
    assert len(results) == 9
    for frame_number, path in results:
        assert 0 <= frame_number < 48
        assert path.exists()
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_frames.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/rrs/pipeline/frames.py`**

```python
from __future__ import annotations

from pathlib import Path

import cv2


class FrameExtractError(RuntimeError):
    pass


def extract_frame(video_path: Path, frame_number: int, out_path: Path) -> Path:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise FrameExtractError(f"could not open {video_path}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_number))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise FrameExtractError(
                f"could not read frame {frame_number} from {video_path}"
            )
    finally:
        cap.release()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise FrameExtractError(f"failed to write {out_path}")
    return out_path


def extract_evenly_spaced(
    video_path: Path,
    start_frame: int,
    end_frame: int,
    count: int,
    out_dir: Path,
) -> list[tuple[int, Path]]:
    """Extract `count` frames evenly spaced through [start_frame, end_frame).

    Returns list of (frame_number, written_path) in order.
    """
    if count < 1:
        return []
    span = max(1, end_frame - start_frame)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[int, Path]] = []
    for i in range(count):
        # midpoints of count equal sub-spans
        fn = start_frame + int((i + 0.5) * span / count)
        path = out_dir / f"cand_{i}.jpg"
        extract_frame(video_path, fn, path)
        results.append((fn, path))
    return results
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_frames.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/frames.py tests/test_frames.py
git commit -m "feat: add OpenCV frame extraction"
```

---

## Task 10: ffmpeg trim

**Files:**
- Create: `src/rrs/pipeline/trim.py`
- Create: `tests/test_trim.py`

- [ ] **Step 1: Write failing test `tests/test_trim.py`**

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rrs.pipeline.trim import TrimError, trim_clip


def _duration_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def test_trim_clip_writes_subclip(synthetic_video: Path, tmp_path: Path):
    out = tmp_path / "clip.mp4"
    trim_clip(source=synthetic_video, start_sec=1.0, end_sec=3.5, out_path=out)
    assert out.exists()
    # Stream copy snaps to keyframes; duration is approximate. Just verify a clip exists.
    dur = _duration_seconds(out)
    assert 0.5 < dur <= 4.0


def test_trim_clip_rejects_inverted_range(synthetic_video: Path, tmp_path: Path):
    with pytest.raises(TrimError):
        trim_clip(source=synthetic_video, start_sec=3.0, end_sec=1.0, out_path=tmp_path / "x.mp4")


def test_trim_clip_rejects_missing_source(tmp_path: Path):
    with pytest.raises(TrimError):
        trim_clip(source=tmp_path / "nope.mp4", start_sec=0, end_sec=1, out_path=tmp_path / "x.mp4")
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_trim.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/rrs/pipeline/trim.py`**

```python
from __future__ import annotations

import subprocess
from pathlib import Path


class TrimError(RuntimeError):
    pass


def trim_clip(source: Path, start_sec: float, end_sec: float, out_path: Path) -> Path:
    source = Path(source)
    if not source.exists():
        raise TrimError(f"source does not exist: {source}")
    if end_sec <= start_sec:
        raise TrimError(f"end_sec ({end_sec}) must be > start_sec ({start_sec})")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start_sec:.3f}",
        "-to", f"{end_sec:.3f}",
        "-i", str(source),
        "-c", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise TrimError(f"ffmpeg failed: {result.stderr[:500]}")
    return out_path
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_trim.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/trim.py tests/test_trim.py
git commit -m "feat: add ffmpeg stream-copy trim"
```

---

## Task 11: Job orchestrator

**Files:**
- Create: `src/rrs/pipeline/jobs.py`
- Create: `tests/test_jobs.py`

The orchestrator runs the pre-interactive stages (download → scenes → first-frame extraction), updating `jobs.status` between each stage. Heavy work happens via `asyncio.to_thread` so it can be called from NiceGUI's event loop.

- [ ] **Step 1: Write failing test `tests/test_jobs.py`**

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from rrs.pipeline.jobs import job_paths, run_pre_interactive_pipeline
from rrs.store.db import JobStatus, open_db


@pytest.fixture
def db():
    return open_db(":memory:")


@pytest.mark.asyncio
async def test_run_pre_interactive_pipeline_happy_path(
    db, tmp_path, synthetic_video: Path
):
    job_id = db.create_job(url="x")
    statuses: list[JobStatus] = []

    def fake_download(url, out_path, max_height, progress_hook=None):
        # simulate the download by copying our fixture in place
        import shutil
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(synthetic_video, out_path)
        from rrs.pipeline.download import DownloadResult
        return DownloadResult(path=out_path, title="t", duration_sec=6.0)

    def on_status(s: JobStatus) -> None:
        statuses.append(s)

    with patch("rrs.pipeline.jobs.download_video", side_effect=fake_download):
        await run_pre_interactive_pipeline(
            db=db, job_id=job_id, data_dir=tmp_path,
            scene_threshold=27.0, on_status=on_status,
        )

    assert statuses == [
        JobStatus.DOWNLOADING,
        JobStatus.DETECTING_SCENES,
        JobStatus.EXTRACTING_FRAMES,
        JobStatus.INTERACTIVE,
    ]
    job = db.get_job(job_id)
    assert job.status == JobStatus.INTERACTIVE
    assert job.title == "t"
    assert job.duration_sec == 6.0
    scenes = db.list_scenes(job_id)
    assert len(scenes) == 3
    # each scene should have its default frame on disk
    for s in scenes:
        frames = db.list_frames(s.id)
        assert len(frames) == 1
        assert frames[0].is_selected is True
        assert Path(frames[0].path).exists()


@pytest.mark.asyncio
async def test_run_pre_interactive_pipeline_download_failure_marks_failed(
    db, tmp_path,
):
    job_id = db.create_job(url="x")

    def boom(*a, **k):
        from rrs.pipeline.download import DownloadError
        raise DownloadError("boom")

    with patch("rrs.pipeline.jobs.download_video", side_effect=boom):
        with pytest.raises(Exception):
            await run_pre_interactive_pipeline(
                db=db, job_id=job_id, data_dir=tmp_path,
                scene_threshold=27.0,
            )
    assert db.get_job(job_id).status == JobStatus.FAILED
    assert "boom" in db.get_job(job_id).error


def test_job_paths_layout(tmp_path):
    paths = job_paths(tmp_path, job_id=42)
    assert paths.root == tmp_path / "jobs" / "42"
    assert paths.source == paths.root / "source.mp4"
    assert paths.frames_dir == paths.root / "frames"
    assert paths.sources_dir == paths.root / "sources"
    assert paths.clips_dir == paths.root / "clips"
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_jobs.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/rrs/pipeline/jobs.py`**

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rrs.pipeline.download import download_video
from rrs.pipeline.frames import extract_frame
from rrs.pipeline.scenes import detect_scenes
from rrs.store.db import Database, JobStatus

StatusHook = Callable[[JobStatus], None]
ProgressHook = Callable[[float], None]


@dataclass(frozen=True)
class JobPaths:
    root: Path
    source: Path
    frames_dir: Path
    sources_dir: Path
    clips_dir: Path


def job_paths(data_dir: Path, job_id: int) -> JobPaths:
    root = Path(data_dir) / "jobs" / str(job_id)
    return JobPaths(
        root=root,
        source=root / "source.mp4",
        frames_dir=root / "frames",
        sources_dir=root / "sources",
        clips_dir=root / "clips",
    )


def _set_status(db: Database, job_id: int, status: JobStatus, hook: StatusHook | None):
    db.update_job_status(job_id, status)
    if hook:
        hook(status)


async def run_pre_interactive_pipeline(
    db: Database,
    job_id: int,
    data_dir: Path,
    scene_threshold: float,
    on_status: StatusHook | None = None,
    on_download_progress: ProgressHook | None = None,
) -> None:
    """Run download → scene detect → first-frame extraction, then mark interactive.

    On any failure, mark the job failed (db.fail_job) and re-raise."""
    job = db.get_job(job_id)
    assert job is not None
    paths = job_paths(data_dir, job_id)
    paths.root.mkdir(parents=True, exist_ok=True)

    try:
        _set_status(db, job_id, JobStatus.DOWNLOADING, on_status)
        result = await asyncio.to_thread(
            download_video, job.url, paths.source, 1080, on_download_progress
        )
        db.set_job_source(
            job_id, title=result.title, duration_sec=result.duration_sec,
            source_path=str(result.path),
        )

        _set_status(db, job_id, JobStatus.DETECTING_SCENES, on_status)
        scenes = await asyncio.to_thread(
            detect_scenes, paths.source, scene_threshold
        )
        db.insert_scenes(
            job_id,
            [(s.idx, s.start_frame, s.end_frame, s.start_sec, s.end_sec) for s in scenes],
        )
        scene_rows = db.list_scenes(job_id)

        _set_status(db, job_id, JobStatus.EXTRACTING_FRAMES, on_status)
        for s, row in zip(scenes, scene_rows):
            scene_dir = paths.frames_dir / str(s.idx)
            out = scene_dir / "0.jpg"
            await asyncio.to_thread(extract_frame, paths.source, s.start_frame, out)
            db.insert_frame(
                scene_id=row.id, ordinal=0, frame_number=s.start_frame,
                path=str(out), is_selected=True,
            )

        _set_status(db, job_id, JobStatus.INTERACTIVE, on_status)
    except Exception as exc:
        db.fail_job(job_id, str(exc))
        raise
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_jobs.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/rrs/pipeline/jobs.py tests/test_jobs.py
git commit -m "feat: add pre-interactive pipeline orchestrator"
```

---

## Task 12: Visual assets (CSS + fonts)

**Files:**
- Create: `src/rrs/ui/__init__.py`
- Create: `src/rrs/ui/static/app.css`
- Create: `src/rrs/ui/static/fonts/.gitkeep`
- Create: `src/rrs/ui/static/fonts/README.md`

We self-host IBM Plex Mono. Three weights, woff2 only.

- [ ] **Step 1: Create empty `src/rrs/ui/__init__.py`**

```python
```

- [ ] **Step 2: Create font directory + README**

`src/rrs/ui/static/fonts/.gitkeep`: empty file.

`src/rrs/ui/static/fonts/README.md`:
```markdown
# Fonts

Drop the following IBM Plex Mono woff2 files here (download from
<https://github.com/IBM/plex/tree/master/IBM-Plex-Mono/fonts/complete/woff2>
or any mirror):

- `IBMPlexMono-Regular.woff2`
- `IBMPlexMono-Medium.woff2`
- `IBMPlexMono-Bold.woff2`

IBM Plex Mono is OFL-1.1 licensed.
```

- [ ] **Step 3: Manually download the three woff2 files** into `src/rrs/ui/static/fonts/`. Verify:

```bash
ls src/rrs/ui/static/fonts/
```

Expected: three .woff2 files (skip this step in tests; required for runtime).

- [ ] **Step 4: Write `src/rrs/ui/static/app.css`**

```css
@font-face {
  font-family: "IBM Plex Mono";
  src: url("/_static/fonts/IBMPlexMono-Regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: "IBM Plex Mono";
  src: url("/_static/fonts/IBMPlexMono-Medium.woff2") format("woff2");
  font-weight: 500;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: "IBM Plex Mono";
  src: url("/_static/fonts/IBMPlexMono-Bold.woff2") format("woff2");
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}

:root {
  --bg:       #0d0c0a;
  --surface:  #161513;
  --border:   #2a2826;
  --text:     #e8e6e1;
  --text-dim: #7a7771;
  --accent:   #ff8a3d;
  --danger:   #c14a3d;
}

html, body, .nicegui-content {
  background: var(--bg);
  color: var(--text);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 14px;
  line-height: 1.5;
  margin: 0;
}

/* Film grain overlay */
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 1000;
  opacity: 0.03;
  background-image:
    url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
  mix-blend-mode: overlay;
}

/* Reset corners */
* { border-radius: 0 !important; }

/* Utility classes */

.rrs-surface { background: var(--surface); border: 1px solid var(--border); }
.rrs-hairline { border: 1px solid var(--border); }

.rrs-label {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  font-weight: 500;
  font-size: 11px;
}

.rrs-timecode {
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.rrs-input {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  padding: 6px 10px;
  width: 100%;
}
.rrs-input:focus { outline: none; border-color: var(--accent); }

.rrs-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 8px 14px;
  cursor: pointer;
  transition: border-color 120ms linear, color 120ms linear;
}
.rrs-btn:hover { border-color: var(--accent); color: var(--accent); }
.rrs-btn[disabled] { color: var(--text-dim); cursor: not-allowed; }
.rrs-btn[disabled]:hover { border-color: var(--border); color: var(--text-dim); }

.rrs-btn-primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #0d0c0a;
}
.rrs-btn-primary:hover { background: #ffa15a; border-color: #ffa15a; color: #0d0c0a; }

.rrs-engine-chip::before { content: "▸ "; }
.rrs-engine-chip[data-status="todo"]::before { content: ""; }

/* Frame strip */

.rrs-frame-strip {
  display: flex;
  gap: 8px;
  align-items: stretch;
}
.rrs-frame {
  position: relative;
  width: 120px; height: 68px;
  background: var(--surface);
  border: 1px solid var(--border);
  overflow: hidden;
  cursor: pointer;
  transition: border-color 80ms linear;
}
.rrs-frame img { width: 100%; height: 100%; object-fit: cover; display: block; }
.rrs-frame.selected { border: 2px solid var(--accent); }
.rrs-frame .rrs-ord {
  position: absolute; top: 0; left: 0;
  background: var(--accent); color: #0d0c0a;
  font-weight: 700; font-size: 10px;
  padding: 2px 6px;
  letter-spacing: 0.04em;
}
.rrs-frame-add {
  width: 60px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-dim);
  font-size: 18px;
}
.rrs-frame-add:hover { color: var(--accent); border-color: var(--accent); }

/* Scene card */

.rrs-scene-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 2px solid var(--border);
  padding: 16px 18px;
  margin-bottom: 14px;
  animation: rrs-card-in 240ms ease-out backwards;
}
@keyframes rrs-card-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.rrs-scene-head {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 12px;
  font-size: 12px;
}
.rrs-scene-idx { font-weight: 700; letter-spacing: 0.05em; }
.rrs-scene-range { color: var(--text); }
.rrs-scene-delta { color: var(--text-dim); }

.rrs-engines { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }

.rrs-source-row {
  display: flex; gap: 10px; align-items: stretch; margin-top: 14px;
}
.rrs-source-row .rrs-input { flex: 1; }

.rrs-status-line {
  margin-top: 12px; padding-top: 10px;
  border-top: 1px dashed var(--border);
  display: flex; align-items: center; gap: 12px;
  font-size: 12px; color: var(--text-dim);
}

/* Top progress strip */

.rrs-top-progress {
  height: 1px; background: var(--border);
  position: relative; overflow: hidden;
}
.rrs-top-progress > span {
  display: block; height: 100%;
  background: var(--accent);
  transition: width 200ms linear;
}
.rrs-top-progress.indet > span {
  animation: rrs-indet 1.2s ease-in-out infinite;
  width: 30%;
}
@keyframes rrs-indet {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.rrs-stage-label {
  margin-top: 10px;
  letter-spacing: 0.1em; text-transform: uppercase;
  font-size: 11px; color: var(--text-dim);
}

/* Modal */

.rrs-modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(13, 12, 10, 0.9);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.rrs-modal {
  background: var(--bg);
  border: 1px solid var(--border);
  padding: 24px;
  width: min(960px, 92vw);
  max-height: 88vh;
  overflow: auto;
  animation: rrs-modal-in 120ms ease-out;
}
@keyframes rrs-modal-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Frame picker grid */
.rrs-grid-9 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.rrs-grid-9 .rrs-frame { width: 100%; height: 0; padding-bottom: 56.25%; }

/* Page container */

.rrs-wrap {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px 28px 80px 28px;
}
.rrs-title {
  text-transform: uppercase; letter-spacing: 0.12em;
  font-weight: 700; font-size: 13px;
  margin-bottom: 24px;
  color: var(--text);
}
.rrs-meta { color: var(--text-dim); font-size: 12px; }

.rrs-error {
  border: 1px solid var(--danger);
  padding: 14px 16px;
  margin: 20px 0;
  color: var(--text);
}
.rrs-error::before { content: "ERR · "; color: var(--danger); font-weight: 700; }
```

- [ ] **Step 5: Commit**

```bash
git add src/rrs/ui
git commit -m "feat: add visual assets — app.css and fonts directory"
```

---

## Task 13: App entry + main wizard skeleton

**Files:**
- Create: `src/rrs/main.py`
- Create: `src/rrs/ui/pages.py`

This task wires up: NiceGUI app, static-file mount, DB initialization, and the wizard page that branches on `jobs.status`. URL input + "process video" button only — heavy stages come in later tasks but this should be runnable now (will route correctly given a job is created and its status mutated externally).

- [ ] **Step 1: Implement `src/rrs/main.py`**

```python
from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

from rrs.config import Config, load_config
from rrs.pipeline.engines import default_enabled_ids
from rrs.store.db import Database, open_db
from rrs.ui.pages import register_pages

_DB: Database | None = None
_CFG: Config | None = None


def get_db() -> Database:
    assert _DB is not None
    return _DB


def get_cfg() -> Config:
    assert _CFG is not None
    return _CFG


def _serve_static(cfg: Config) -> None:
    static_dir = Path(__file__).parent / "ui" / "static"
    app.add_static_files("/_static", str(static_dir))
    app.add_static_files("/_data", str(cfg.data_dir))
    ui.add_head_html('<link rel="stylesheet" href="/_static/app.css">')


def main() -> None:
    global _DB, _CFG
    _CFG = load_config(probe_ffmpeg=True)
    _DB = open_db(_CFG.data_dir / "app.db")

    if _DB.get_setting("enabled_engines") is None:
        import json
        _DB.set_setting("enabled_engines", json.dumps(default_enabled_ids()))

    _serve_static(_CFG)
    register_pages(get_db=get_db, get_cfg=get_cfg)
    ui.run(port=_CFG.port, title="rrs", reload=False, show=False, dark=True)


if __name__ == "__main__" or __name__ == "__mp_main__":
    main()
```

- [ ] **Step 2: Implement skeleton `src/rrs/ui/pages.py`**

```python
from __future__ import annotations

import asyncio
from typing import Callable

from nicegui import ui

from rrs.config import Config
from rrs.pipeline.jobs import run_pre_interactive_pipeline
from rrs.store.db import Database, Job, JobStatus

GetDb = Callable[[], Database]
GetCfg = Callable[[], Config]


def register_pages(get_db: GetDb, get_cfg: GetCfg) -> None:
    @ui.page("/")
    async def index() -> None:
        db = get_db()
        cfg = get_cfg()
        active = _find_active_job(db)
        _render_wizard(db, cfg, active)


def _find_active_job(db: Database) -> Job | None:
    """Return the most recent non-deleted job, or None."""
    row = db._conn.execute(
        "SELECT id FROM jobs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return db.get_job(row["id"]) if row else None


def _render_wizard(db: Database, cfg: Config, job: Job | None) -> None:
    with ui.element("div").classes("rrs-wrap"):
        ui.html('<div class="rrs-title">Ranking Reverse Search</div>')
        if job is None:
            _render_url_input(db, cfg)
            return
        _render_for_status(db, cfg, job)


def _render_url_input(db: Database, cfg: Config) -> None:
    ui.html('<div class="rrs-label" style="margin-bottom:8px">Paste ranking video URL</div>')
    with ui.row().classes("w-full"):
        url_input = ui.input(placeholder="https://...").classes("rrs-input").style("flex:1")

        async def on_click() -> None:
            url = url_input.value.strip()
            if not url:
                return
            job_id = db.create_job(url=url)
            # kick off the pipeline as a fire-and-forget asyncio task
            asyncio.create_task(_run_pipeline(db, cfg, job_id))
            ui.navigate.reload()

        ui.button("PROCESS VIDEO", on_click=on_click).props("flat").classes("rrs-btn rrs-btn-primary")


async def _run_pipeline(db: Database, cfg: Config, job_id: int) -> None:
    try:
        await run_pre_interactive_pipeline(
            db=db, job_id=job_id, data_dir=cfg.data_dir,
            scene_threshold=cfg.scene_threshold,
        )
    except Exception:
        # Already marked failed inside the pipeline; UI will reflect on next render.
        pass


def _render_for_status(db: Database, cfg: Config, job: Job) -> None:
    status = job.status
    if status == JobStatus.FAILED:
        ui.html(f'<div class="rrs-error">{(job.error or "Unknown error")}</div>')
        ui.button("START OVER", on_click=lambda: _start_over(db, job.id)).classes("rrs-btn")
        return
    if status in (
        JobStatus.DOWNLOADING,
        JobStatus.DETECTING_SCENES,
        JobStatus.EXTRACTING_FRAMES,
    ):
        _render_progress(job)
        ui.timer(1.0, lambda: ui.navigate.reload(), once=True)
        return
    if status == JobStatus.INTERACTIVE:
        # full scene-list view comes in Task 14
        ui.html('<div class="rrs-meta">Pipeline complete. Scene list view: see Task 14.</div>')
        ui.button("START OVER", on_click=lambda: _start_over(db, job.id)).classes("rrs-btn")
        return


def _render_progress(job: Job) -> None:
    labels = {
        JobStatus.DOWNLOADING: "DOWNLOADING RANKING VIDEO",
        JobStatus.DETECTING_SCENES: "DETECTING SCENES",
        JobStatus.EXTRACTING_FRAMES: "EXTRACTING FRAMES",
    }
    label = labels.get(job.status, str(job.status))
    ui.html(f'<div class="rrs-top-progress indet"><span></span></div>')
    ui.html(f'<div class="rrs-stage-label">{label}</div>')


def _start_over(db: Database, job_id: int) -> None:
    import shutil
    from rrs.pipeline.jobs import job_paths
    # tear down on-disk artifacts
    from rrs.main import get_cfg
    paths = job_paths(get_cfg().data_dir, job_id)
    if paths.root.exists():
        shutil.rmtree(paths.root, ignore_errors=True)
    db.delete_job(job_id)
    ui.navigate.to("/")
```

- [ ] **Step 3: Smoke-test the app manually**

Run:
```bash
IMGBB_API_KEY=dummy DATA_DIR=./.local-data python -m rrs.main
```

Open `http://localhost:8080`. Expected: dark theme, mono font (or system fallback if you haven't downloaded fonts yet), "RANKING REVERSE SEARCH" title, URL input + amber PROCESS VIDEO button.

Paste a real YouTube URL → click → page reloads → progress bar shows → eventually the placeholder "Pipeline complete" appears. (Or a yt-dlp error in red if the URL is private/blocked.)

- [ ] **Step 4: Commit**

```bash
git add src/rrs/main.py src/rrs/ui/pages.py
git commit -m "feat: app entry, static asset wiring, wizard skeleton"
```

---

## Task 14: Scene list + scene card

**Files:**
- Create: `src/rrs/ui/components.py`
- Modify: `src/rrs/ui/pages.py` (replace `INTERACTIVE` branch)

- [ ] **Step 1: Implement `src/rrs/ui/components.py`**

```python
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
        # Header
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
        # Frame strip
        _render_frame_strip(scene, selected, frames, data_dir, on_open_frame_picker)
        # Engine chips per selected frame
        for f in selected:
            _render_engine_row(f, enabled_ids, on_search_click)
        # Source row
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
        # Add button
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
            from rrs.ui.pages import download_source_for_scene  # avoid circular
            url = inp.value.strip()
            if not url:
                return
            await download_source_for_scene(db, data_dir, scene.id, url)
            ui.navigate.reload()

        ui.button("DOWNLOAD", on_click=on_download).classes("rrs-btn")
    # Status / trim row
    src = db.get_source(scene.id)
    if src and src.path:
        with ui.element("div").classes("rrs-status-line"):
            ui.html(f'<span>source: {Path(src.path).name}</span>')
            ui.button("TRIM CLIP", on_click=lambda s=scene: on_open_trim(s)).classes("rrs-btn")
            if src.clip_path:
                clip_url = file_url(src.clip_path, data_dir)
                ui.html(f'<a class="rrs-btn" href="{clip_url}" target="_blank">OPEN CLIP</a>')
```

- [ ] **Step 2: Modify the `INTERACTIVE` branch of `_render_for_status`** in `src/rrs/ui/pages.py`

Replace the existing `INTERACTIVE` block with:

```python
    if status == JobStatus.INTERACTIVE:
        _render_scene_list(db, cfg, job)
        return
```

And add this function below `_render_for_status`:

```python
def _render_scene_list(db: Database, cfg: Config, job: Job) -> None:
    from rrs.ui.components import render_scene_card

    with ui.element("div").classes("rrs-meta"):
        ui.html(
            f'<div>{(job.title or "Untitled")} — '
            f'{(job.duration_sec or 0):.1f}s</div>'
        )
    ui.button("START OVER", on_click=lambda: _start_over(db, job.id)).classes("rrs-btn")

    scenes = db.list_scenes(job.id)
    for scene in scenes:
        render_scene_card(
            db=db, data_dir=cfg.data_dir, scene=scene, total_scenes=len(scenes),
            on_open_frame_picker=lambda s: _open_frame_picker(db, cfg, s),
            on_open_trim=lambda s: _open_trim(db, cfg, s),
            on_search_click=lambda f, eid: _do_reverse_search(db, cfg, f, eid),
        )


# Placeholder handlers — filled in by later tasks.
def _open_frame_picker(db, cfg, scene):
    ui.notify("frame picker — Task 15", type="warning")


def _open_trim(db, cfg, scene):
    ui.notify("trim modal — Task 17", type="warning")


def _do_reverse_search(db, cfg, frame, engine_id):
    ui.notify("reverse search — Task 16", type="warning")


async def download_source_for_scene(db, data_dir, scene_id, url):
    ui.notify("source download — Task 16", type="warning")
```

- [ ] **Step 3: Smoke-test**

Restart the app. Process a YouTube video. When status reaches `interactive`, the page should show the scene list with cards. Each card shows: timecode header, frame strip with the first frame (amber 2px border + "01" ordinal tag), engine button chips (GOOGLE LENS / YANDEX / BING / TINEYE), source URL input + DOWNLOAD button.

Buttons currently just toast placeholders. That's expected.

- [ ] **Step 4: Commit**

```bash
git add src/rrs/ui/components.py src/rrs/ui/pages.py
git commit -m "feat: scene list + scene card layout"
```

---

## Task 15: Frame picker modal

**Files:**
- Create: `src/rrs/ui/modals.py`
- Modify: `src/rrs/ui/pages.py` (`_open_frame_picker`)

- [ ] **Step 1: Implement `src/rrs/ui/modals.py` (frame picker only for now)**

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

from nicegui import ui

from rrs.pipeline.frames import extract_evenly_spaced
from rrs.pipeline.jobs import job_paths
from rrs.store.db import Database, Scene
from rrs.ui.components import file_url

CANDIDATE_COUNT = 9


async def open_frame_picker(
    db: Database, data_dir: Path, job_id: int, scene: Scene,
    on_close: Callable[[], None],
) -> None:
    """Show modal grid of CANDIDATE_COUNT frames; click to toggle selection."""
    paths = job_paths(data_dir, job_id)
    cand_dir = paths.frames_dir / str(scene.idx) / "candidates"

    # Lazy-extract candidate frames on first open
    if not cand_dir.exists() or len(list(cand_dir.glob("cand_*.jpg"))) < CANDIDATE_COUNT:
        # Compute synchronously - already on a background-friendly handler thread in NiceGUI
        extract_evenly_spaced(
            video_path=paths.source,
            start_frame=scene.start_frame,
            end_frame=scene.end_frame,
            count=CANDIDATE_COUNT,
            out_dir=cand_dir,
        )

    candidates = sorted(cand_dir.glob("cand_*.jpg"))
    # Compute frame_number for each candidate by stem order
    span = max(1, scene.end_frame - scene.start_frame)
    candidate_meta = [
        (scene.start_frame + int((i + 0.5) * span / CANDIDATE_COUNT), p)
        for i, p in enumerate(candidates)
    ]

    existing_frames = db.list_frames(scene.id)
    by_frame_number = {f.frame_number: f for f in existing_frames}

    with ui.dialog().props("persistent").classes("rrs-modal-backdrop") as dialog:
        with ui.element("div").classes("rrs-modal"):
            ui.html('<div class="rrs-label" style="margin-bottom:14px">SELECT FRAMES</div>')
            with ui.element("div").classes("rrs-grid-9"):
                for frame_number, path in candidate_meta:
                    existing = by_frame_number.get(frame_number)
                    selected = bool(existing and existing.is_selected)
                    url = file_url(path, data_dir)
                    sel_cls = " selected" if selected else ""
                    html = (
                        f'<div class="rrs-frame{sel_cls}" data-fn="{frame_number}">'
                        f'  <img src="{url}">'
                        f'</div>'
                    )
                    el = ui.html(html)

                    def _toggle(_, fn=frame_number, p=path):
                        _toggle_selection(db, scene, fn, p)
                        on_close()
                        dialog.close()
                        ui.navigate.reload()

                    el.on("click", _toggle)
            with ui.element("div").style("text-align:right; margin-top: 18px"):
                ui.button("CLOSE", on_click=lambda: (dialog.close(), on_close())).classes("rrs-btn")
    dialog.open()


def _toggle_selection(db: Database, scene: Scene, frame_number: int, path: Path) -> None:
    """Toggle is_selected for the candidate at frame_number. Inserts a frames row if new."""
    existing = [f for f in db.list_frames(scene.id) if f.frame_number == frame_number]
    if existing:
        f = existing[0]
        db.set_frame_selected(f.id, not f.is_selected)
        return
    # New row — find next free ordinal
    next_ord = max((f.ordinal for f in db.list_frames(scene.id)), default=-1) + 1
    db.insert_frame(
        scene_id=scene.id, ordinal=next_ord, frame_number=frame_number,
        path=str(path), is_selected=True,
    )
```

- [ ] **Step 2: Modify `_open_frame_picker` in `src/rrs/ui/pages.py`**

Replace:
```python
def _open_frame_picker(db, cfg, scene):
    ui.notify("frame picker — Task 15", type="warning")
```

with:
```python
def _open_frame_picker(db: Database, cfg: Config, scene) -> None:
    import asyncio
    from rrs.ui.modals import open_frame_picker

    # asyncio task because open_frame_picker is async
    job = _find_active_job(db)
    if job is None:
        return
    asyncio.create_task(
        open_frame_picker(db, cfg.data_dir, job.id, scene, on_close=lambda: None)
    )
```

- [ ] **Step 3: Smoke-test**

Restart the app, drive through to the interactive view, click on a scene's frame thumbnail. Expected: 3×3 grid of candidate frames, currently-selected ones highlighted with amber border + ordinal. Click any to toggle. Close → scene card re-renders with the new selection.

- [ ] **Step 4: Commit**

```bash
git add src/rrs/ui/modals.py src/rrs/ui/pages.py
git commit -m "feat: frame picker modal with lazy candidate extraction"
```

---

## Task 16: Reverse search wiring + source download

**Files:**
- Modify: `src/rrs/ui/pages.py` (replace `_do_reverse_search` and `download_source_for_scene`)

- [ ] **Step 1: Replace placeholders in `src/rrs/ui/pages.py`**

Replace `_do_reverse_search`:
```python
def _do_reverse_search(db: Database, cfg: Config, frame, engine_id: str) -> None:
    import asyncio
    from rrs.pipeline.engines import get_engine
    from rrs.pipeline.hosting import ImgbbError, upload_image

    engine = get_engine(engine_id)
    if engine is None or engine.status != "ready":
        ui.notify(f"{engine_id} is not implemented yet", type="warning")
        return
    if cfg.imgbb_api_key is None:
        ui.notify("IMGBB_API_KEY not set", type="negative")
        return

    async def _go() -> None:
        # Reuse cached upload if we have it
        fresh = next((f for f in db.list_frames(frame.scene_id) if f.id == frame.id), None)
        if fresh is None:
            ui.notify("frame missing", type="negative")
            return
        if fresh.imgbb_url:
            image_url = fresh.imgbb_url
        else:
            try:
                image_url = await asyncio.to_thread(
                    upload_image, Path(fresh.path), cfg.imgbb_api_key
                )
            except ImgbbError as exc:
                ui.notify(f"imgbb: {exc}", type="negative")
                return
            db.set_frame_imgbb_url(fresh.id, image_url)
        url = engine.search_url(image_url)
        if url is None:
            ui.notify(f"{engine_id} not searchable", type="warning")
            return
        ui.run_javascript(f"window.open({url!r}, '_blank')")

    asyncio.create_task(_go())
```

Replace `download_source_for_scene`:
```python
async def download_source_for_scene(db: Database, data_dir, scene_id: int, url: str) -> None:
    import asyncio
    from rrs.pipeline.download import DownloadError, download_video
    from rrs.pipeline.jobs import job_paths

    scene = next((s for s in db.list_scenes(_active_job_id(db) or -1) if s.id == scene_id), None)
    if scene is None:
        ui.notify("scene not found", type="negative")
        return
    paths = job_paths(data_dir, scene.job_id)
    paths.sources_dir.mkdir(parents=True, exist_ok=True)
    out = paths.sources_dir / f"{scene.idx}.mp4"

    src_id = db.upsert_source(scene_id=scene.id, url=url)
    try:
        result = await asyncio.to_thread(
            download_video, url, out, None  # max_height=None → best
        )
    except DownloadError as exc:
        ui.notify(f"yt-dlp: {exc}", type="negative")
        return
    db.set_source_downloaded(src_id, path=str(result.path))
    ui.notify("source downloaded", type="positive")


def _active_job_id(db) -> int | None:
    job = _find_active_job(db)
    return job.id if job else None
```

The `download_source_for_scene` function lives at module level — `components.py` imports it lazily. Make sure to add the `Path` import at the top of `pages.py` if not already there:

```python
from pathlib import Path
```

- [ ] **Step 2: Import additions at top of `pages.py`**

Add (if not already present):
```python
import asyncio
from pathlib import Path
from rrs.store.db import Database, Job, JobStatus
from rrs.config import Config
```

- [ ] **Step 3: Manual smoke test**

1. Set `IMGBB_API_KEY=<your-key>`.
2. Restart app, process a video to interactive.
3. Click `GOOGLE LENS` on a scene's frame. Expected: amber-tinted notification, then a new browser tab opens at lens.google.com with the imgbb-hosted frame URL.
4. Click again — opens instantly (cached).
5. Paste a YouTube URL (any short clip) into a source URL field, click `DOWNLOAD`. Expected: spinner-ish blocking wait (acceptable for MVP), then notification, page reload, status line appears reading `source: 0.mp4`.

- [ ] **Step 4: Commit**

```bash
git add src/rrs/ui/pages.py
git commit -m "feat: reverse-search button wiring and source download"
```

---

## Task 17: Trim modal

**Files:**
- Modify: `src/rrs/ui/modals.py` (add `open_trim_modal`)
- Modify: `src/rrs/ui/pages.py` (`_open_trim`)

- [ ] **Step 1: Add `open_trim_modal` to `src/rrs/ui/modals.py`**

```python
async def open_trim_modal(
    db: Database, data_dir: Path, job_id: int, scene: Scene,
) -> None:
    src = db.get_source(scene.id)
    if src is None or not src.path:
        return

    # Probe source duration via ffprobe (cheap, one call)
    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", src.path],
        capture_output=True, text=True,
    )
    try:
        source_duration = float(probe.stdout.strip())
    except ValueError:
        ui.notify("could not read source duration", type="negative")
        return

    scene_duration = scene.end_sec - scene.start_sec
    midpoint = source_duration / 2.0
    default_start = max(0.0, midpoint - scene_duration / 2.0)
    default_end = min(source_duration, midpoint + scene_duration / 2.0)

    initial_start = src.trim_start_sec if src.trim_start_sec is not None else default_start
    initial_end = src.trim_end_sec if src.trim_end_sec is not None else default_end

    video_url = file_url(src.path, data_dir)

    with ui.dialog().props("persistent").classes("rrs-modal-backdrop") as dialog:
        with ui.element("div").classes("rrs-modal"):
            ui.html('<div class="rrs-label" style="margin-bottom:14px">TRIM CLIP</div>')
            ui.html(
                f'<video controls src="{video_url}" '
                f'style="width:100%; max-height:50vh; background:black"></video>'
            )
            ui.html(
                f'<div class="rrs-meta rrs-timecode" style="margin-top:10px">'
                f'source duration: {source_duration:.2f}s  ·  scene Δ {scene_duration:.2f}s'
                f'</div>'
            )
            with ui.row().classes("w-full").style("gap:12px; margin-top:14px"):
                start_in = ui.number(label="START (s)", value=round(initial_start, 3), format="%.3f").classes("rrs-input")
                end_in = ui.number(label="END (s)", value=round(initial_end, 3), format="%.3f").classes("rrs-input")

            async def on_save() -> None:
                from rrs.pipeline.jobs import job_paths
                from rrs.pipeline.trim import TrimError, trim_clip
                import asyncio

                a = float(start_in.value)
                b = float(end_in.value)
                if b <= a:
                    ui.notify("END must be greater than START", type="negative")
                    return
                paths = job_paths(data_dir, job_id)
                paths.clips_dir.mkdir(parents=True, exist_ok=True)
                out = paths.clips_dir / f"{scene.idx}.mp4"
                try:
                    await asyncio.to_thread(trim_clip, Path(src.path), a, b, out)
                except TrimError as exc:
                    ui.notify(f"ffmpeg: {exc}", type="negative")
                    return
                db.set_source_clip(src.id, trim_start_sec=a, trim_end_sec=b, clip_path=str(out))
                ui.notify("clip saved", type="positive")
                dialog.close()
                ui.navigate.reload()

            with ui.row().style("justify-content: flex-end; gap: 10px; margin-top: 18px"):
                ui.button("CANCEL", on_click=dialog.close).classes("rrs-btn")
                ui.button("SAVE CLIP", on_click=on_save).classes("rrs-btn rrs-btn-primary")
    dialog.open()
```

- [ ] **Step 2: Wire `_open_trim` in `src/rrs/ui/pages.py`**

Replace:
```python
def _open_trim(db, cfg, scene):
    ui.notify("trim modal — Task 17", type="warning")
```

with:
```python
def _open_trim(db: Database, cfg: Config, scene) -> None:
    import asyncio
    from rrs.ui.modals import open_trim_modal
    job = _find_active_job(db)
    if job is None:
        return
    asyncio.create_task(open_trim_modal(db, cfg.data_dir, job.id, scene))
```

- [ ] **Step 3: Manual smoke test**

Drive through to the interactive view, paste a YouTube URL for a scene, download it, then click `TRIM CLIP`. Expected: modal opens with the source video playing inline, START/END inputs default to a window of scene-duration around the source midpoint, "SAVE CLIP" runs ffmpeg and the scene card now shows an OPEN CLIP link.

- [ ] **Step 4: Commit**

```bash
git add src/rrs/ui/modals.py src/rrs/ui/pages.py
git commit -m "feat: trim modal with default window around source midpoint"
```

---

## Task 18: Resume handling + missing-key UX

**Files:**
- Modify: `src/rrs/ui/pages.py`

When the user reloads the browser mid-pipeline and no in-flight task is present, the wizard should show a Resume button instead of an infinite spinner.

- [ ] **Step 1: Track in-flight jobs in pages module**

Add at the top of `src/rrs/ui/pages.py` (module level):

```python
_INFLIGHT: set[int] = set()
```

- [ ] **Step 2: Update `_run_pipeline` to register/unregister**

Replace `_run_pipeline` with:

```python
async def _run_pipeline(db: Database, cfg: Config, job_id: int) -> None:
    _INFLIGHT.add(job_id)
    try:
        await run_pre_interactive_pipeline(
            db=db, job_id=job_id, data_dir=cfg.data_dir,
            scene_threshold=cfg.scene_threshold,
        )
    except Exception:
        pass
    finally:
        _INFLIGHT.discard(job_id)
```

- [ ] **Step 3: Update `_render_for_status` to show Resume when needed**

Replace the in-progress branch with:

```python
    if status in (
        JobStatus.DOWNLOADING,
        JobStatus.DETECTING_SCENES,
        JobStatus.EXTRACTING_FRAMES,
    ):
        if job.id in _INFLIGHT:
            _render_progress(job)
            ui.timer(1.0, lambda: ui.navigate.reload(), once=True)
        else:
            _render_progress(job)
            ui.html('<div class="rrs-meta" style="margin-top:14px">no worker running for this stage</div>')
            def _resume():
                import asyncio
                asyncio.create_task(_run_pipeline(db, cfg, job.id))
                ui.navigate.reload()
            ui.button("RESUME", on_click=_resume).classes("rrs-btn rrs-btn-primary")
            ui.button("START OVER", on_click=lambda: _start_over(db, job.id)).classes("rrs-btn")
        return
```

- [ ] **Step 4: Improve imgbb-missing UX**

In `_render_scene_list`, before calling `render_scene_card`, surface a banner if the key is missing:

```python
    if cfg.imgbb_api_key is None:
        ui.html('<div class="rrs-error">IMGBB_API_KEY not set — engine buttons disabled</div>')
```

And in `_do_reverse_search` we already early-return with a notify on missing key — leave that as is.

- [ ] **Step 5: Smoke test**

1. Start a long job (e.g. a multi-minute YouTube video). While the progress bar shows, kill the server and restart it. Visit `/`. Expected: "no worker running" + RESUME button.
2. Click RESUME → pipeline picks up from where the persisted status indicates (in practice: re-runs the current stage, idempotent for scene/frame inserts? — note: scenes have UNIQUE constraint and INSERTs will fail on resume mid-detect; see step 6 caveat).

**Caveat:** Stages aren't perfectly idempotent — re-running scene detection after partial inserts will hit `UNIQUE(job_id, idx)`. For MVP this is acceptable: the user can RESUME only if the prior worker died *before* the stage's DB writes started, otherwise START OVER is the right move. Document this in a comment.

Add a comment above the resume button:

```python
            # NOTE: resume re-runs the current stage from scratch. If the prior
            # worker died mid-write (rare), the user should START OVER instead.
```

- [ ] **Step 6: Commit**

```bash
git add src/rrs/ui/pages.py
git commit -m "feat: resume button for orphaned jobs, imgbb-missing banner"
```

---

## Task 19: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# rrs — ranking reverse search

A local NiceGUI app for sourcing video clips out of compilation/ranking
videos via reverse image search.

## Install

Requires Python 3.11+ and ffmpeg on PATH.

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Download IBM Plex Mono woff2 files into `src/rrs/ui/static/fonts/` —
see that directory's README for details.

## Run

```sh
export IMGBB_API_KEY=<your-key>
export DATA_DIR=./data            # optional, defaults to ./data
rrs                                # or: python -m rrs.main
```

Open <http://localhost:8080>.

## Workflow

1. Paste a YouTube (or other yt-dlp-supported) URL → app downloads at
   1080p, detects scenes, extracts first frame per scene.
2. For each scene: click the frame thumbnail to pick a different frame
   (or add additional frames), then click an engine button to open a
   reverse-image search in a new tab.
3. When you find the source, paste its URL into the scene's source
   field and click DOWNLOAD (highest available quality).
4. Click TRIM CLIP to scrub and save the relevant moment.

## Tests

```sh
pytest
```

## Spec

See `docs/superpowers/specs/2026-06-14-ranking-reverse-search-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README"
```

---

## Self-review

**Spec coverage check** (each section of the spec → task):

| Spec section | Task(s) |
|---|---|
| Stack / deps | 1 |
| Architecture (modules) | 1, 3, 4, 7, 8, 9, 10, 11, 12, 13 |
| Single-job UX, status-driven view | 13, 14, 18 |
| Visual design (palette, typography, layout) | 12, 14, 15, 17 |
| Pipeline stages 1–3 (download/scenes/frames) | 7, 8, 9, 11 |
| Pipeline stage 4 (interactive reverse search) | 16 |
| Pipeline stage 5 (source download) | 16 |
| Pipeline stage 6 (trim) | 10, 17 |
| Engine registry, ready & TODO | 4, 5 |
| Data model (sql + DAL) | 3 |
| Threading via run_in_executor / to_thread | 11, 16, 17 |
| Config + startup probes | 2, 13 |
| Error handling matrix | 7, 11, 13, 16, 17, 18 |
| Reload mid-pipeline resume | 18 |
| Tests (unit + integration) | 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 |
| Out of scope (no pHash, no matching, no UI tests) | implicit — no task |

All spec sections accounted for.

**Placeholder scan:** None remaining. Every code step shows working code.

**Type consistency check:**
- `Database` methods used in `jobs.py`, `pages.py`, `modals.py` all match signatures defined in Task 3.
- `Engine.search_url(image_url) -> str | None` signature matches across registry and `pages.py`.
- `DownloadResult(path, title, duration_sec)` constructed in Task 7, consumed identically in Task 11.
- `SceneRow` (returned by `detect_scenes`) and `Scene` (DB row dataclass) are distinct types — `jobs.py` maps from one to the other explicitly. Confirmed.
- `JobPaths` accessed via `paths.root/source/frames_dir/sources_dir/clips_dir` consistently.

Plan ready.
