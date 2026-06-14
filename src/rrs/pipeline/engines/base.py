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
