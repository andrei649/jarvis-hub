"""0.45 Batch B1: supply-chain and host-control live contract gates."""

from __future__ import annotations

import pytest

from agents.core import automation_contracts
from agents.core.automation_contracts import ContractDecision
from agents.core.autonomy import remediation
from agents.core.autonomy.remediation import ExecResult, RemediationRunner, ServiceCommand
from agents.core.llm import lmstudio_control
from agents.core.llm.lmstudio_control import LMStudioController
from agents.core.skills import loader as loader_mod
from agents.core.skills import marketplace as marketplace_mod
from agents.core.skills.loader import SkillLoader
from agents.core.skills.marketplace import SkillMarketplace


class _DenyContract:
    def __init__(self, reason: str = "contract_blocked"):
        self.reason = reason
        self.calls = []

    def evaluate(self, payload, **kwargs):
        self.calls.append((dict(payload), dict(kwargs)))
        return ContractDecision(
            kind=payload.get("kind", "test"),
            admissible=False,
            requires_approval=True,
            reason=self.reason,
        )


def _marketplace(tmp_path):
    return SkillMarketplace(skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "mk.db"))


def _skill_dir(mk, folder="myskill", title="My Skill"):
    path = mk.skills_dir / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"# {title}\nversion: 1.0\n", encoding="utf-8")
    (path / "main.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    return path


def test_contract_denial_helper_returns_stable_reasons():
    denied = ContractDecision("x", admissible=False, requires_approval=True, reason="nope")
    denied_without_reason = ContractDecision("x", admissible=False, requires_approval=True)
    allowed = ContractDecision("x", admissible=True, requires_approval=True)

    assert automation_contracts.contract_denial(denied) == "nope"
    assert automation_contracts.contract_denial(denied_without_reason) == "contract_denied"
    assert automation_contracts.contract_denial(allowed) is None


def test_marketplace_publish_obeys_live_skill_contract(tmp_path, monkeypatch):
    mk = _marketplace(tmp_path)
    _skill_dir(mk)
    contract = _DenyContract()
    monkeypatch.setattr(marketplace_mod, "SKILL_INSTALL_CONTRACT", contract, raising=False)

    with pytest.raises(PermissionError) as exc:
        mk.publish_skill("myskill")

    assert "contract_blocked" in str(exc.value)
    assert contract.calls[0][0]["action"] == "publish"


def test_marketplace_install_obeys_live_skill_contract(tmp_path, monkeypatch):
    mk = _marketplace(tmp_path)
    _skill_dir(mk)
    mk.publish_skill("myskill")
    name = mk.list_skills()[0]["name"]
    contract = _DenyContract()
    monkeypatch.setattr(marketplace_mod, "SKILL_INSTALL_CONTRACT", contract, raising=False)

    with pytest.raises(PermissionError) as exc:
        mk.install_skill(name)

    assert "contract_blocked" in str(exc.value)
    assert contract.calls[0][0]["action"] == "install"


def test_marketplace_uninstall_obeys_live_skill_contract(tmp_path, monkeypatch):
    mk = _marketplace(tmp_path)
    skill_path = _skill_dir(mk, folder="foo", title="Foo")
    contract = _DenyContract()
    monkeypatch.setattr(marketplace_mod, "SKILL_INSTALL_CONTRACT", contract, raising=False)

    with pytest.raises(PermissionError) as exc:
        mk.uninstall_skill("foo")

    assert "contract_blocked" in str(exc.value)
    assert skill_path.exists()
    assert contract.calls[0][0]["action"] == "uninstall"


def test_generated_skill_creation_obeys_live_generation_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path)
    loader = SkillLoader()
    contract = _DenyContract()
    monkeypatch.setattr(loader_mod, "SKILL_GENERATION_CONTRACT", contract, raising=False)

    name = loader.generate_skill(
        agent_id="pepper",
        task_description="organize the morning inbox",
        solution_steps=["read inbox"],
        command_name="tidy_inbox",
    )

    assert name is None
    assert not any(tmp_path.iterdir())
    assert contract.calls[0][0]["action"] == "generate"


def test_generated_skill_approval_obeys_live_generation_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path)
    loader = SkillLoader()
    name = loader.generate_skill(
        agent_id="pepper",
        task_description="organize the morning inbox",
        solution_steps=["read inbox"],
        command_name="tidy_inbox",
    )
    contract = _DenyContract()
    monkeypatch.setattr(loader_mod, "SKILL_GENERATION_CONTRACT", contract, raising=False)

    assert loader.approve_generated_skill(name) is False
    assert (tmp_path / name / "PENDING_REVIEW").exists()
    assert contract.calls[0][0]["action"] == "approve"


@pytest.mark.asyncio
async def test_remediation_restart_obeys_live_host_contract(monkeypatch):
    contract = _DenyContract()
    monkeypatch.setattr(remediation, "HOST_CONTROL_CONTRACT", contract, raising=False)
    exec_calls = []

    async def exec_fn(argv, timeout, detach):
        exec_calls.append(argv)
        return ExecResult(exit_code=0)

    runner = RemediationRunner(
        allowlist={"qdrant": ServiceCommand(["docker", "restart", "qdrant"])},
        exec_fn=exec_fn,
    )

    result = await runner.restart("qdrant", agent="steve")

    assert result["status"] == "blocked"
    assert result["reason"] == "contract_blocked"
    assert exec_calls == []
    assert contract.calls[0][0]["action"] == "restart_service"


@pytest.mark.asyncio
async def test_lmstudio_control_obeys_live_host_contract(monkeypatch):
    contract = _DenyContract()
    monkeypatch.setattr(lmstudio_control, "HOST_CONTROL_CONTRACT", contract, raising=False)
    exec_calls = []

    async def exec_fn(argv, timeout, detach):
        exec_calls.append(argv)
        return ExecResult(exit_code=0)

    ctrl = LMStudioController(
        enabled=True,
        exec_fn=exec_fn,
        probe_fn=lambda _host, _port: False,
    )

    result = await ctrl.start_server(agent="jarvis")

    assert result["status"] == "blocked"
    assert result["reason"] == "contract_blocked"
    assert exec_calls == []
    assert contract.calls[0][0]["action"] == "lmstudio.start"
