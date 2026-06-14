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


__all__ = [
    "Engine",
    "EngineCategory",
    "EngineStatus",
    "ALL_ENGINES",
    "get_engine",
    "default_enabled_ids",
]
