"""Sandbox child environment hardening."""

import pytest

from agents.core.sandbox import Sandbox


@pytest.mark.asyncio
async def test_subprocess_python_uses_scrubbed_utf8_child_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    sandbox = Sandbox(allow_subprocess=True, work_dir=str(tmp_path))
    sandbox._has_docker = False
    sandbox._has_wasmtime = False

    result = await sandbox.execute_python(
        "import os\n"
        "print(os.environ.get('OPENAI_API_KEY', 'missing'))\n"
        "print('arrow \\u2192 ok')\n"
    )

    assert result.success
    assert "sk-test-secret" not in result.stdout
    assert "missing" in result.stdout
    assert "arrow \u2192 ok" in result.stdout
