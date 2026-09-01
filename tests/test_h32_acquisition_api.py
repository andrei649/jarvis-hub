"""H32.6 — honest user status and separate admin lifecycle controls."""

from __future__ import annotations

import json

import pytest

from agents.core.acquisition.runtime import AcquisitionRuntime
from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
from agents.core.routers import acquisition as acquisition_router
from agents.core.skills.marketplace import SkillMarketplace
from agents.core.tool_rpc import ToolRPCServer

PINNED_IMAGE = "python:3.12-slim@sha256:" + "a" * 64


def _payload(response) -> dict:
    return json.loads(response.body)


def test_disabled_status_is_honest_and_does_not_create_runtime_files(tmp_path):
    runtime = AcquisitionRuntime(enabled=lambda: False, root=tmp_path / "acquisition")

    assert runtime.status_snapshot() == {
        "enabled": False,
        "status": "disabled",
        "reason": "acquisition_disabled",
        "states": {},
        "reuse": {
            "reused": 0,
            "generated": 0,
            "blocked": 0,
            "abandoned": 0,
            "reuse_rate": 0.0,
        },
        "packages": [],
        "audit": {
            "status": "disabled",
            "events": 0,
            "summarized_events": 0,
            "chain_valid": True,
        },
    }
    assert not (tmp_path / "acquisition").exists()


def test_enabled_status_reports_blocked_until_managed_signing_is_provisioned(tmp_path):
    root = tmp_path / "acquisition"
    runtime = AcquisitionRuntime(enabled=lambda: True, root=root)
    runtime.bind_promotion(
        tool_rpc=ToolRPCServer(),
        marketplace=SkillMarketplace(
            skills_dir=str(tmp_path / "skills"),
            db_path=str(tmp_path / "marketplace.db"),
        ),
        profile=AcquisitionSandboxProfile(image=PINNED_IMAGE),
    )
    request = runtime.capture_gap(
        {
            "goal": "parse Acme items",
            "agent_id": "jarvis",
            "reason": "tool_not_allowed",
        }
    )
    broker = runtime.ensure_promotion()

    blocked = runtime.status_snapshot()
    assert blocked["enabled"] is True
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "managed_signing_key_required"
    assert blocked["states"] == {"missing": 1}
    assert blocked["audit"]["chain_valid"] is True
    assert runtime.list_audit_events(limit=10)[0]["request_hash"]
    assert "parse Acme" not in json.dumps(runtime.export_audit())

    broker.packages.signing.provision(key_id="owner", version=1, key=b"k" * 32)
    ready = runtime.status_snapshot()
    assert ready["status"] == "ready"
    assert ready["reason"] is None
    assert request.request_id not in json.dumps(ready)


class _Runtime:
    def __init__(self):
        self.calls = []

    def status_snapshot(self):
        return {
            "enabled": True,
            "status": "ready",
            "reason": None,
            "states": {"installed": 1},
            "reuse": {"reused": 1, "generated": 1, "blocked": 0, "abandoned": 0, "reuse_rate": 0.5},
            "packages": [{"name": "acme_parser", "version": "0.1.0", "status": "active", "confidence": 0.1}],
            "audit": {"status": "healthy", "events": 1, "summarized_events": 0, "chain_valid": True},
        }

    def list_audit_events(self, *, limit):
        return [{"event_type": "install.committed", "status": "installed", "sequence": 1}][:limit]

    def export_audit(self):
        return {"schema": 1, "summary": {"count": 0}, "events": self.list_audit_events(limit=10)}

    def purge_audit(self, *, actor):
        self.calls.append(("purge", actor))
        return {"purged": 1, "summarized_events": 1}

    async def revoke(self, name):
        self.calls.append(("revoke", name))
        return {"status": "revoked", "name": name}

    async def rollback(self, name):
        self.calls.append(("rollback", name))
        return {"status": "restored", "name": name, "version": "0.0.9"}


@pytest.mark.asyncio
async def test_user_reads_and_admin_mutations_use_separate_bounded_routes(monkeypatch):
    runtime = _Runtime()
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)

    status = _payload(await acquisition_router.acquisition_status())
    events = _payload(await acquisition_router.acquisition_events(limit=25))
    exported = _payload(await acquisition_router.acquisition_export())
    revoked = _payload(await acquisition_router.acquisition_revoke("acme_parser"))
    rolled_back = _payload(await acquisition_router.acquisition_rollback("acme_parser"))
    purged = _payload(
        await acquisition_router.acquisition_purge(
            acquisition_router.AcquisitionPurgeBody(confirm="PURGE ACQUISITION DETAIL")
        )
    )

    assert status["status"] == "ready"
    assert events == {
        "enabled": True,
        "status": "ready",
        "events": [{"event_type": "install.committed", "status": "installed", "sequence": 1}],
    }
    assert exported["schema"] == 1
    assert revoked == {"status": "revoked", "name": "acme_parser"}
    assert rolled_back["version"] == "0.0.9"
    assert purged == {"status": "purged", "purged": 1, "summarized_events": 1}
    assert runtime.calls == [
        ("revoke", "acme_parser"),
        ("rollback", "acme_parser"),
        ("purge", "owner"),
    ]


@pytest.mark.asyncio
async def test_invalid_admin_control_is_refused_without_calling_runtime(monkeypatch):
    runtime = _Runtime()
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)

    refused = _payload(
        await acquisition_router.acquisition_purge(
            acquisition_router.AcquisitionPurgeBody(confirm="not confirmed")
        )
    )
    assert refused == {
        "status": "refused",
        "reason": "exact_owner_confirmation_required",
    }
    assert runtime.calls == []


def test_router_declares_complete_user_admin_surface():
    assert {route.path for route in acquisition_router.router.routes} == {
        "/api/acquisition/status",
        "/api/acquisition/events",
        "/api/acquisition/ledger/export",
        "/api/acquisition/ledger/purge",
        "/api/acquisition/{name}/revoke",
        "/api/acquisition/{name}/rollback",
        "/api/acquisition/{request_id}/drive",
        # DRA-38: the admin read surface the HUD needs to address a drive target.
        # /drive takes a request_id, but nothing enumerated pending requests, so the
        # control had no way to name one — this is the missing half of that pair.
        "/api/acquisition/requests",
    }
