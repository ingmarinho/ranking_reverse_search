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
