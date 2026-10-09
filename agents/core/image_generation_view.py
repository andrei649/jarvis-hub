"""Minimal owner-visible state, never a serialization of a raw autonomy row."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from agents.core.media_backends.comfyui import _HISTORY_ERROR_MARKER, _HISTORY_ERROR_REASON
from agents.core.media_backends.local_openai_image import (
    _RESPONSE_FAILURE_MARKER,
    _RESPONSE_FAILURE_REASONS,
)
from agents.core.media_backends.openai_image import ENDPOINT

_CLOUD_PROVIDER_FAILURES = frozenset({
    "cloud_image_provider_error",
    "cloud_image_response_too_large",
    "cloud_image_invalid_response",
})


class ImageArtifactView(BaseModel):
    id: str
    bytes: int
    width: int
    height: int


class ImageTaskView(BaseModel):
    task_id: int
    state: Literal["awaiting_approval", "queued", "generating", "ready", "failed", "rejected", "deferred", "refused", "uncertain"]
    artifact: ImageArtifactView | None = None


def _cloud_provider_response_failed(task) -> bool:
    """Recognize only the fixed cloud provider-response failure envelope."""
    payload = task.payload
    execution = task.result
    return (
        task.kind == "plugin.egress"
        and type(payload) is dict
        and payload.get("plugin") == "cloud-image"
        and payload.get("method") == "POST"
        and payload.get("url") == ENDPOINT
        and type(execution) is dict
        and set(execution) == {"status", "reason"}
        and execution["status"] == "failed"
        and type(execution["reason"]) is str
        and execution["reason"] in _CLOUD_PROVIDER_FAILURES
    )


def _local_provider_response_failed(task) -> bool:
    """Recognize only the canonical local backend marker and reason pairs."""
    payload = task.payload
    execution = task.result
    if not (task.kind == "tool.rpc"
            and type(payload) is dict
            and payload.get("tool") == "image_generate"
            and payload.get("target") == "image_generate"
            and type(execution) is dict
            and set(execution) == {"status", "reason", "tool", "result"}
            and execution["status"] == "failed"
            and execution["tool"] == "image_generate"
            and type(execution["reason"]) is str):
        return False
    media = execution["result"]
    return (type(media) is dict
            and set(media) == {"ok", "reason", "provider_response_failed"}
            and media["ok"] is False
            and type(media["reason"]) is str
            and media["reason"] == execution["reason"]
            and type(media["provider_response_failed"]) is str
            and ((media["provider_response_failed"] == _RESPONSE_FAILURE_MARKER
                  and execution["reason"] in _RESPONSE_FAILURE_REASONS)
                 or (media["provider_response_failed"] == _HISTORY_ERROR_MARKER
                     and execution["reason"] == _HISTORY_ERROR_REASON)))


def project_image_task(task) -> ImageTaskView:
    states = {"blocked": "awaiting_approval", "proposed": "awaiting_approval",
              "approved": "queued", "running": "generating", "rejected": "rejected",
              "deferred": "deferred", "quarantined": "refused"}
    result = ImageTaskView(task_id=task.id, state=states.get(task.status, "uncertain"))
    if task.status != "done":
        return result
    if _cloud_provider_response_failed(task):
        result.state = "failed"
        return result
    # Cloud completion is established only by CloudImageRuntime.recover, which
    # checks the durable artifact. A local-tool-shaped result is not cloud proof.
    if task.kind == "plugin.egress":
        return result
    if _local_provider_response_failed(task):
        result.state = "failed"
        return result
    try:
        execution = task.result
        media = execution["result"]
        artifact = media["result"]
        if not (execution["status"] == "ok" and execution["tool"] == "image_generate"
                and media["ok"] is True and media["kind"] == "image"
                and isinstance(artifact["artifact_id"], str)
                and re.fullmatch(r"[a-f0-9]{32}", artifact["artifact_id"])):
            return result
        for key, limit in (("bytes", 16 * 1024 * 1024), ("width", 2048), ("height", 2048)):
            if type(artifact[key]) is not int or not 1 <= artifact[key] <= limit:
                return result
        result.artifact = ImageArtifactView(id=artifact["artifact_id"], bytes=artifact["bytes"], width=artifact["width"], height=artifact["height"])
        result.state = "ready"
    except (KeyError, TypeError):
        return result
    return result
