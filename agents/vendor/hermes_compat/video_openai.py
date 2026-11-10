"""``openai`` for the adopted video files (rewrite rule ``video-openai-sdk``): the videos API.

``OpenAICompatibleVideoGenProvider`` (DeepInfra in Nerva) uses three calls of the OpenAI
SDK's ``client.videos``: ``create`` (submit a job), ``retrieve`` (poll it) and
``download_content`` (fetch the finished file). The real SDK builds its own HTTP client,
so it is never imported. This stand-in sends the same three requests through the compat
``httpx`` (the approved task's egress client):

* ``POST {base_url}/videos`` with a JSON body: ``model``, ``prompt``, ``seconds``, ``size``
  and the ``extra_body`` fields merged in (DeepInfra reads ``image_url``,
  ``negative_prompt``, ``aspect_ratio``, ``seed`` there);
* ``GET {base_url}/videos/{id}``;
* ``GET {base_url}/videos/{id}/content``, a capped stream into the task's video sink.

A job id from the provider is untrusted: it must be a plain token before it becomes part
of a path. Answers are plain objects with attribute access (``status``, ``id``, ``data``,
``error``), like the SDK's models. The key goes only in ``Authorization`` and is never in
a repr or an error.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from agents.vendor.hermes_compat import httpx, video_media

TIMEOUT_SECONDS = 60
_JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}")


class OpenAIError(Exception):
    """The stand-in's error (the SDK's ``openai.OpenAIError``)."""


def _model(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{str(k): v for k, v in value.items() if str(k).isidentifier()})
    return value


def _job_id(value: Any) -> str:
    text = str(value or "")
    if not _JOB_ID.fullmatch(text) or ".." in text:
        raise OpenAIError("invalid job id")
    return text


class _Content:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _Videos:
    def __init__(self, client: OpenAI) -> None:
        self._client = client

    def create(self, *, model: str, prompt: str, seconds: str | None = None,
               size: str | None = None, extra_body: dict | None = None, **_unused: Any) -> Any:
        body: dict[str, Any] = {"model": model, "prompt": prompt}
        if seconds is not None:
            body["seconds"] = seconds
        if size is not None:
            body["size"] = size
        for key, value in dict(extra_body or {}).items():
            body.setdefault(str(key), value)
        resp = httpx.post(f"{self._client.base_url}/videos", json=body,
                          headers=self._client._headers(), timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        return _model(resp.json())

    def retrieve(self, video_id: Any) -> Any:
        resp = httpx.get(f"{self._client.base_url}/videos/{_job_id(video_id)}",
                         headers=self._client._headers(), timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        return _model(resp.json())

    def download_content(self, video_id: Any) -> _Content:
        sink = video_media.current_sink()
        if sink is None:
            raise OpenAIError("no approved video task is bound")
        status, body, _kind = httpx.download(
            f"{self._client.base_url}/videos/{_job_id(video_id)}/content",
            max_bytes=sink.max_bytes, headers=self._client._headers(), timeout=85)
        if status != 200:
            raise OpenAIError(f"HTTP {status}")
        return _Content(body)


class OpenAI:
    def __init__(self, *, api_key: str = "", base_url: str = "", http_client: Any = None,
                 **_unused: Any) -> None:
        del http_client
        self._api_key = str(api_key or "")
        self.base_url = str(base_url or "").rstrip("/")
        self.videos = _Videos(self)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def close(self) -> None:
        return None

    def __repr__(self) -> str:
        return "<OpenAI videos (compat)>"


__all__ = ["OpenAI", "OpenAIError"]
