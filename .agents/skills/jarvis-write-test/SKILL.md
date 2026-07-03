---
name: jarvis-write-test
description: Use when writing or fixing a pytest test in the jarvis hub (tests/test_*.py), or when a test fails on import/path/async-decorator issues. Triggers on "write a test", "add coverage", ModuleNotFoundError in tests, or "test hangs".
---

# Writing a jarvis test (offline, async-auto)

The suite is **offline by default** and runs `async def test_*` without decorators (`pytest.ini: asyncio_mode = auto`).

1. **sys.path bootstrap** — every test file starts with:
   ```python
   import sys
   from pathlib import Path
   repo_root = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(repo_root))
   sys.path.insert(0, str(repo_root / "agents"))
   ```
   Use this, never relative imports.
2. **No real network/LLM** — inject fakes (`FakeBackend(LLMBackend)`, `FakeLMStudioClient`). A test that hits the network is a bug.
3. **Async tests** are plain `async def test_*` — no `@pytest.mark.asyncio`.
4. **Heavy Orchestrator** — avoid `Orchestrator(config)` in unit tests. Use `Orchestrator.__new__(Orchestrator)` + manual attribute assignment, or `conftest.py:make_app` for a lightweight FastAPI app.
5. **Location:** `tests/test_<module_name>.py`. Run `pytest -q` from repo root.

## Common mistakes
- Relative imports → collection error; use the sys.path bootstrap.
- Adding `@pytest.mark.asyncio` → redundant under auto mode.
- Instantiating the full Orchestrator → slow/flaky; use `__new__` + fakes.
