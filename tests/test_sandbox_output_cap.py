"""The sandbox output cap must bound peak HOST memory, not just what's returned.

Before this fix every backend did ``proc.communicate()``, which drains the child
to EOF into host memory *before* truncating — so a runaway/hostile sandboxed
child (this runs agent-generated code) could balloon host RSS for the whole
timeout window even though ``max_output_bytes`` limited the returned string.
``_read_output_capped`` now streams head+tail within the budget, so a child that
emits far more than the cap is bounded as it is read.
"""

import asyncio
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.sandbox import Sandbox  # noqa: E402


async def test_read_output_capped_bounds_a_real_runaway_child():
    sb = Sandbox(max_output_bytes=100)
    # A real child that writes 500 KB to stdout in one shot.
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('x' * 500000)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await sb._read_output_capped(proc)

    # Returned output is bounded to ~the budget, not the child's 500 KB.
    assert len(out) < 2000
    # The truncation notice reports the TRUE total, so it can't understate.
    assert "TRUNCATED" in out
    assert "500,000" in out
    assert err == ""


async def test_read_output_capped_passes_small_output_through():
    sb = Sandbox(max_output_bytes=1000)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "print('hello from the child')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await sb._read_output_capped(proc)

    assert out.strip() == "hello from the child"
    assert "TRUNCATED" not in out
    assert err == ""
