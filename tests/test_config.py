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
