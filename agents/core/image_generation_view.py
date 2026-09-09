"""Minimal owner-visible state, never a serialization of a raw autonomy row."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel


class ImageArtifactView(BaseModel):
    id: str
    bytes: int
    width: int
    height: int


class ImageTaskView(BaseModel):
    task_id: int
    state: Literal["awaiting_approval", "queued", "generating", "ready", "rejected", "deferred", "refused", "uncertain"]
    artifact: ImageArtifactView | None = None


def project_image_task(task) -> ImageTaskView:
    states = {"blocked": "awaiting_approval", "proposed": "awaiting_approval",
              "approved": "queued", "running": "generating", "rejected": "rejected",
              "deferred": "deferred", "quarantined": "refused"}
    result = ImageTaskView(task_id=task.id, state=states.get(task.status, "uncertain"))
    if task.status != "done":
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
        for key, limit in (("bytes", 16 * 1024 * 1024), ("width", 1024), ("height", 1024)):
            if type(artifact[key]) is not int or not 1 <= artifact[key] <= limit:
                return result
        result.artifact = ImageArtifactView(id=artifact["artifact_id"], bytes=artifact["bytes"], width=artifact["width"], height=artifact["height"])
        result.state = "ready"
    except (KeyError, TypeError):
        return result
    return result
