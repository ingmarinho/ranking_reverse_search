from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from rrs.config import (
    Config,
    MissingDependencyError,
    _activate_bundled_binaries,
    _default_data_dir,
    load_config,
)


def test_load_config_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("IMGBB_API_KEY", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(probe_ffmpeg=False)
    assert cfg.data_dir == tmp_path
    assert cfg.port == 8080
    assert cfg.scene_threshold == 27.0
    assert cfg.max_clip_duration_sec == 180.0
    assert cfg.imgbb_api_key is None


def test_load_config_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("IMGBB_API_KEY", "k123")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("SCENE_THRESHOLD", "30.5")
    monkeypatch.setenv("MAX_CLIP_DURATION_SEC", "300")
    cfg = load_config(probe_ffmpeg=False)
    assert cfg.imgbb_api_key == "k123"
    assert cfg.port == 9090
    assert cfg.scene_threshold == 30.5
    assert cfg.max_clip_duration_sec == 300.0


def test_load_config_max_clip_duration_disabled_when_non_positive(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_CLIP_DURATION_SEC", "0")
    cfg = load_config(probe_ffmpeg=False)
    assert cfg.max_clip_duration_sec is None


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


def test_default_data_dir_is_cwd_relative_in_source_run(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert _default_data_dir() == Path("./data")


def test_default_data_dir_next_to_binary_when_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "rrs"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    assert _default_data_dir() == tmp_path.resolve() / "data"


def test_load_config_uses_binary_dir_when_frozen_and_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_DIR", raising=False)
    exe = tmp_path / "rrs"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    cfg = load_config(probe_ffmpeg=False)
    assert cfg.data_dir == tmp_path.resolve() / "data"
    assert cfg.data_dir.exists()


def test_load_config_env_wins_even_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "rrs"), raising=False)
    override = tmp_path / "elsewhere"
    monkeypatch.setenv("DATA_DIR", str(override))
    cfg = load_config(probe_ffmpeg=False)
    assert cfg.data_dir == override


def test_activate_bundled_binaries_noop_without_meipass(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    before = os.environ.get("PATH", "")
    _activate_bundled_binaries()
    assert os.environ.get("PATH", "") == before


def test_activate_bundled_binaries_prepends_bin_when_frozen(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    _activate_bundled_binaries()
    assert os.environ["PATH"].split(os.pathsep)[0] == str(bin_dir)
    assert "/usr/bin" in os.environ["PATH"]
