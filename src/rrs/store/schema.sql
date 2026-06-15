CREATE TABLE IF NOT EXISTS jobs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(scene_id)
);

CREATE TABLE IF NOT EXISTS settings (
  key             TEXT PRIMARY KEY,
  value           TEXT NOT NULL
);
