from __future__ import annotations

import sqlite3

import pytest

from rrs.store.db import (
    CropRect,
    Database,
    JobStatus,
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
    db.insert_scenes(
        job_id,
        [
            (0, 0, 48, 0.0, 2.0),
            (1, 48, 96, 2.0, 4.0),
        ],
    )
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


def test_set_frame_image_updates_and_clears_imgbb_url(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [(0, 0, 48, 0.0, 2.0)])
    scene_id = db.list_scenes(job_id)[0].id
    fid = db.insert_frame(scene_id, 0, 0, "/old.jpg", is_selected=True)
    db.set_frame_imgbb_url(fid, "https://i.ibb.co/abc.jpg")

    db.set_frame_image(fid, frame_number=25, path="/new.jpg")

    frame = db.list_frames(scene_id)[0]
    assert frame.frame_number == 25
    assert frame.path == "/new.jpg"
    assert frame.imgbb_url is None


def test_frame_crop_round_trip_and_clears_imgbb_url(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [(0, 0, 48, 0.0, 2.0)])
    scene_id = db.list_scenes(job_id)[0].id
    fid = db.insert_frame(scene_id, 0, 0, "/x.jpg", is_selected=True)
    assert db.list_frames(scene_id)[0].crop is None

    db.set_frame_imgbb_url(fid, "https://i.ibb.co/abc.jpg")
    db.set_frame_crop(fid, CropRect(0.1, 0.2, 0.3, 0.4))
    frame = db.list_frames(scene_id)[0]
    assert frame.crop == CropRect(0.1, 0.2, 0.3, 0.4)
    assert frame.imgbb_url is None  # crop change invalidates the cached upload

    db.set_frame_crop(fid, None)
    assert db.list_frames(scene_id)[0].crop is None


def test_migration_adds_crop_columns_to_legacy_db(tmp_path):
    # Build a frames table without the crop columns, then open via Database and
    # confirm the idempotent migration adds them.
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE frames (id INTEGER PRIMARY KEY, scene_id INTEGER, ordinal INTEGER,"
        " frame_number INTEGER, path TEXT, imgbb_url TEXT, is_selected INTEGER DEFAULT 0);"
    )
    conn.commit()
    conn.close()

    db = open_db(path)
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(frames)")}
    assert {"crop_x", "crop_y", "crop_w", "crop_h"} <= cols


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
    # re-upserting a new url resets the downloaded path
    db.upsert_source(scene_id=sid, url="https://src.example/other.mp4")
    src = db.get_source(sid)
    assert src.url == "https://src.example/other.mp4"
    assert src.path is None


def test_settings_get_and_set(db: Database):
    db.set_setting("enabled_engines", '["google_lens","yandex"]')
    assert db.get_setting("enabled_engines") == '["google_lens","yandex"]'
    assert db.get_setting("missing") is None


def test_foreign_keys_cascade(db: Database):
    job_id = db.create_job(url="x")
    db.insert_scenes(job_id, [(0, 0, 48, 0.0, 2.0)])
    db.delete_job(job_id)
    assert db.get_job(job_id) is None
    with sqlite3.connect(":memory:"):
        pass
    assert db.list_scenes(job_id) == []


def test_job_download_dir_defaults_none(db: Database):
    job_id = db.create_job(url="x")
    assert db.get_job(job_id).download_dir is None


def test_set_and_get_download_dir(db: Database):
    job_id = db.create_job(url="x")
    db.set_download_dir(job_id, "/data/downloads/My Video")
    assert db.get_job(job_id).download_dir == "/data/downloads/My Video"
    # overwrite semantics: second call replaces the value
    db.set_download_dir(job_id, "/data/downloads/New Title")
    assert db.get_job(job_id).download_dir == "/data/downloads/New Title"


def test_claimed_download_dirs_empty_when_no_other_jobs(db: Database):
    job_id = db.create_job(url="x")
    db.set_download_dir(job_id, "/data/downloads/Solo")
    assert db.claimed_download_dirs(exclude_job_id=job_id) == set()


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
