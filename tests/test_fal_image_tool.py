"""Registered model FAL proposals retain the existing single approval path."""

import httpx
import pytest

from tests.test_cloud_image import cloud, png  # noqa: F401
from tests.test_cloud_image_fal import fal  # noqa: F401
from tests.test_cloud_image_tool import tool  # noqa: F401


@pytest.mark.asyncio
async def test_registered_image_tool_generates_fal_artifact_after_one_approval(fal, tool):
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    fal.state.response = iter((
        httpx.Response(200, json={"images": [{"url": "https://v3.fal.media/result.png"}]}),
        httpx.Response(200, content=png((512, 512))),
    )).__next__
    token = bind_action_origin("inbound")
    try:
        response = await tool.server.handle({"tool": "image_generate", "args": {
            "cloud": True, "backend": "fal", "prompt": "blue square",
            "model": "fal-ai/flux-2/klein/9b", "seed": 3,
        }}, actor="athena")
    finally:
        reset_action_origin(token)
    assert response.get("reason") == "approval_required", response
    task = fal.queue.get(response["task_id"])
    assert task.agent == "athena" and task.origin == "inbound"
    assert task.payload["tainted"] is True
    assert task.payload["plugin"] == "cloud-image-fal"
    assert fal.queue.verified_mediation_stats()["authorized_enqueue"] == 1
    assert not fal.requests
    fal.runtime.validate(task.payload)
    await fal.worker.apply_decision(task.id, "accept", decided_by="test owner")
    await fal.worker.tick()
    completed = fal.queue.get(task.id)
    assert completed.result.get("status") == "ok", (completed.status, completed.result)
    assert [request.method for request in fal.requests] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_registered_fal_edit_exposes_catalog_reference_capacity(fal, tool):
    refs = [f"https://fal.media/ref-{i}.png" for i in range(16)]
    response = await tool.server.handle({"tool": "image_generate", "args": {
        "cloud": True, "backend": "fal", "model": "fal-ai/gpt-image-2",
        "prompt": "Combine these references", "references": refs,
    }})
    assert response.get("reason") == "approval_required", response
    task = fal.queue.get(response["task_id"])
    assert task.payload["url"] == "https://fal.run/openai/gpt-image-2/edit"
    assert task.payload["image"]["body"]["references"] == refs
    assert not fal.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {"references": ["https://outside.invalid/ref.png"]},
    {"references": ["https://fal.media/a.png"] * 17},
    {"reference": "a" * 32}, {"quality": "high"}, {"width": 512},
    {"backend": "other"},
])
async def test_invalid_fal_model_options_do_not_enqueue(fal, tool, extra):
    result = await tool.server.handle({"tool": "image_generate", "args": {
        "cloud": True, "backend": "fal", "prompt": "blue square", **extra,
    }})
    assert result["ok"] is False and "task_id" not in result
    assert fal.queue.verified_mediation_stats()["authorized_enqueue"] == 0
    assert not fal.requests


@pytest.mark.asyncio
async def test_approved_inbound_openai_image_retains_provenance_and_executes(cloud, tool):
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    token = bind_action_origin("inbound")
    try:
        response = await tool.server.handle({"tool": "image_generate", "args": {
            "cloud": True, "prompt": "blue square",
        }}, actor="athena")
    finally:
        reset_action_origin(token)
    task = cloud.queue.get(response["task_id"])
    assert task.origin == "inbound" and task.payload["taint_source"] == "inbound"
    assert task.payload["tainted"] is True and not cloud.requests
    await cloud.worker.apply_decision(task.id, "accept", decided_by="test owner")
    await cloud.worker.tick()
    completed = cloud.queue.get(task.id)
    assert completed.result.get("status") == "ok", (completed.status, completed.result)
    assert len(cloud.requests) == 1
