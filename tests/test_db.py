from __future__ import annotations

import sqlite3

import pytest

from rrs.store.db import (
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
    with sqlite3.connect(":memory:"):
        pass
    assert db.list_scenes(job_id) == []
