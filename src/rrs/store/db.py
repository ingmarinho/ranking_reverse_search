from __future__ import annotations

import enum
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

SETTINGS_IMGBB_KEY = "imgbb_api_key"


class JobStatus(enum.StrEnum):
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
class CropRect:
    """A crop region as fractions (0..1) of the frame's width/height."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Frame:
    id: int
    scene_id: int
    ordinal: int
    frame_number: int
    path: str
    imgbb_url: str | None
    is_selected: bool
    crop: CropRect | None = None


@dataclass(frozen=True)
class Source:
    id: int
    scene_id: int
    url: str
    path: str | None


def _schema_sql() -> str:
    return resources.files("rrs.store").joinpath("schema.sql").read_text()


class Database:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_schema_sql())
        self._migrate()

    def _migrate(self) -> None:
        """Apply additive schema changes the idempotent CREATE TABLE can't.

        `schema.sql` uses CREATE TABLE IF NOT EXISTS, so columns added after a
        DB was first created won't appear. Add any missing ones here; the
        table_info check makes each ALTER run at most once."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(frames)")}
        for col in ("crop_x", "crop_y", "crop_w", "crop_h"):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE frames ADD COLUMN {col} REAL")
        self._conn.commit()

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
        cur = self._conn.execute("SELECT * FROM scenes WHERE job_id = ? ORDER BY idx", (job_id,))
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
        self._conn.execute("UPDATE frames SET imgbb_url = ? WHERE id = ?", (url, frame_id))
        self._conn.commit()

    def set_frame_image(self, frame_id: int, frame_number: int, path: str) -> None:
        """Point a frame row at a different extracted frame.

        Clears imgbb_url: the image changed, so any cached imgbb upload is stale
        and must be re-uploaded on the next reverse search."""
        self._conn.execute(
            "UPDATE frames SET frame_number = ?, path = ?, imgbb_url = NULL WHERE id = ?",
            (frame_number, path, frame_id),
        )
        self._conn.commit()

    def set_frame_selected(self, frame_id: int, selected: bool) -> None:
        self._conn.execute(
            "UPDATE frames SET is_selected = ? WHERE id = ?", (int(selected), frame_id)
        )
        self._conn.commit()

    def set_frame_crop(self, frame_id: int, rect: CropRect | None) -> None:
        """Set (or clear) the frame's crop region.

        Clears imgbb_url: the searched image changed, so any cached upload is
        stale and must be re-uploaded (cropped) on the next reverse search."""
        if rect is None:
            self._conn.execute(
                "UPDATE frames SET crop_x = NULL, crop_y = NULL, crop_w = NULL,"
                " crop_h = NULL, imgbb_url = NULL WHERE id = ?",
                (frame_id,),
            )
        else:
            self._conn.execute(
                "UPDATE frames SET crop_x = ?, crop_y = ?, crop_w = ?, crop_h = ?,"
                " imgbb_url = NULL WHERE id = ?",
                (rect.x, rect.y, rect.w, rect.h, frame_id),
            )
        self._conn.commit()

    # ---- sources ----

    def upsert_source(self, scene_id: int, url: str) -> int:
        existing = self._conn.execute(
            "SELECT id FROM sources WHERE scene_id = ?", (scene_id,)
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE sources SET url = ?, path = NULL WHERE id = ?",
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
        row = self._conn.execute("SELECT * FROM sources WHERE scene_id = ?", (scene_id,)).fetchone()
        return self._row_to_source(row) if row else None

    def set_source_downloaded(self, source_id: int, path: str) -> None:
        self._conn.execute("UPDATE sources SET path = ? WHERE id = ?", (path, source_id))
        self._conn.commit()

    # ---- settings ----

    def get_setting(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_imgbb_key(self) -> str | None:
        value = (self.get_setting(SETTINGS_IMGBB_KEY) or "").strip()
        return value or None

    def set_imgbb_key(self, key: str) -> None:
        self.set_setting(SETTINGS_IMGBB_KEY, key.strip())

    def clear_imgbb_key(self) -> None:
        self._conn.execute("DELETE FROM settings WHERE key = ?", (SETTINGS_IMGBB_KEY,))
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
            id=r["id"],
            job_id=r["job_id"],
            idx=r["idx"],
            start_frame=r["start_frame"],
            end_frame=r["end_frame"],
            start_sec=r["start_sec"],
            end_sec=r["end_sec"],
        )

    @staticmethod
    def _row_to_frame(r: sqlite3.Row) -> Frame:
        cx, cy, cw, ch = r["crop_x"], r["crop_y"], r["crop_w"], r["crop_h"]
        crop = CropRect(cx, cy, cw, ch) if None not in (cx, cy, cw, ch) else None
        return Frame(
            id=r["id"],
            scene_id=r["scene_id"],
            ordinal=r["ordinal"],
            frame_number=r["frame_number"],
            path=r["path"],
            imgbb_url=r["imgbb_url"],
            is_selected=bool(r["is_selected"]),
            crop=crop,
        )

    @staticmethod
    def _row_to_source(r: sqlite3.Row) -> Source:
        return Source(
            id=r["id"],
            scene_id=r["scene_id"],
            url=r["url"],
            path=r["path"],
        )


def open_db(path: str | Path) -> Database:
    conn = sqlite3.connect(str(path))
    return Database(conn)
