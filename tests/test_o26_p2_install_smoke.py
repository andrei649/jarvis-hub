"""O26-P2.5 — fast install smoke path."""

import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from scripts import install_smoke  # noqa: E402


@pytest.mark.asyncio
async def test_install_smoke_boots_readyz_and_faked_turn(tmp_path):
    result = await install_smoke.run_install_smoke(state_dir=tmp_path)

    assert result.ok is True
    assert result.ready_status == 200
    assert result.agents >= 1
    assert result.channels >= 0
    assert result.model == install_smoke.FAKE_MODEL
    assert result.reply == install_smoke.DEFAULT_REPLY
    assert result.elapsed_seconds < 30


def test_cli_dev_runs_full_suite_after_fast_smoke(monkeypatch, capsys):
    async def _fake_smoke(**_kwargs):
        return install_smoke.SmokeResult(
            ok=True,
            ready_status=200,
            agents=17,
            channels=0,
            model=install_smoke.FAKE_MODEL,
            reply=install_smoke.DEFAULT_REPLY,
            elapsed_seconds=0.1,
        )

    calls = []
    monkeypatch.setattr(install_smoke, "run_install_smoke", _fake_smoke)
    monkeypatch.setattr(install_smoke, "run_dev_suite", lambda: calls.append("dev") or 0)

    assert install_smoke.main(["--dev", "--json"]) == 0
    assert calls == ["dev"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["model"] == install_smoke.FAKE_MODEL


def test_cli_failure_returns_nonzero(monkeypatch, capsys):
    async def _boom(**_kwargs):
        raise RuntimeError("not ready")

    monkeypatch.setattr(install_smoke, "run_install_smoke", _boom)

    assert install_smoke.main(["--json"]) == 1
    assert "not ready" in capsys.readouterr().err
