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
    ui.add_head_html('<link rel="stylesheet" href="/_static/app.css">', shared=True)


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
