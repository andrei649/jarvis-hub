"""Start the real hub for the Nerva Workspace Playwright lane (``playwright.workspace.config.ts``).

Why a launcher and not a bare ``serve.py`` command: Playwright merges ``process.env`` into a
web server's environment, so a developer's cloud keys, a ``JARVIS_HOME`` or a ``.env`` would
leak into the run and the journey would talk to a real provider or an old database. This
script builds the environment the lane needs from nothing but the run directory:

* ``JARVIS_HOME=<run>/home`` and ``JARVIS_KEY_DIR=<run>/keys`` — a fresh data root and a fresh
  audit/backup key folder for every run (the run directory is new each time, see the config);
* the workspace on, with a fixed setup code; the model is the fake OpenAI-compatible server
  (``JARVIS_LM_STUDIO_URL``), Ollama points at a closed port, warm-up is off;
* every ``*_API_KEY`` / ``*_API_TOKEN`` and every provider-prefixed variable is removed, other
  ``JARVIS_*`` / ``NERVA_*`` settings are dropped, and python-dotenv is switched off, so no
  ``.env`` file adds them back.

The hub's stdout and stderr are copied line by line to ``<run>/hub.log`` (the journey's last
step reads it for tracebacks) and to this process's stdout. SIGTERM and SIGINT are forwarded
to the hub, and the launcher exits with the hub's exit code; when that is not 0 it prints the
end of the log to stderr, the stream the Playwright config shows.

Usage (from the repository root): ``python frontend/e2e/support/workspace_hub.py`` with
``WS_E2E_RUN_DIR``, ``WS_E2E_HUB_PORT``, ``WS_E2E_MODEL_PORT`` and ``WS_E2E_SETUP_CODE`` set.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: Prefixes of provider settings the hub could use to reach a cloud model.
PROVIDER_PREFIXES = (
    "ANTHROPIC_", "CLAUDE_", "GEMINI_", "GOOGLE_API", "GOOGLE_GENAI", "OPENAI_", "OPENROUTER_",
    "DEEPINFRA_", "DEEPSEEK_", "XAI_", "MISTRAL_", "GROQ_", "TOGETHER_", "FIREWORKS_",
    "COHERE_", "PERPLEXITY_", "AZURE_OPENAI", "OLLAMA_",
)
#: Hub and workspace settings are owned by this launcher; inherited ones are dropped.
OWNED_PREFIXES = ("JARVIS_", "NERVA_")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"workspace_hub.py: {name} is not set (the Playwright config sets it)")
    return value


def scrubbed(environ: dict[str, str]) -> dict[str, str]:
    """*environ* without provider credentials and without inherited hub settings."""
    kept: dict[str, str] = {}
    for name, value in environ.items():
        upper = name.upper()
        if upper.endswith(("_API_KEY", "_API_TOKEN", "_AUTH_TOKEN")):
            continue
        if upper.startswith(PROVIDER_PREFIXES) or upper.startswith(OWNED_PREFIXES):
            continue
        kept[name] = value
    return kept


def hub_environment(run_dir: Path) -> dict[str, str]:
    home = run_dir / "home"
    keys = run_dir / "keys"
    home.mkdir(parents=True, exist_ok=True)
    keys.mkdir(parents=True, exist_ok=True)
    env = scrubbed(dict(os.environ))
    env.update({
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
        "JARVIS_HOME": str(home),
        "JARVIS_KEY_DIR": str(keys),
        "JARVIS_PORT": required("WS_E2E_HUB_PORT"),
        "JARVIS_LOG_LEVEL": "warning",
        "JARVIS_LLM_WARMUP": "0",
        "JARVIS_LM_STUDIO_URL": f"http://127.0.0.1:{required('WS_E2E_MODEL_PORT')}",
        "JARVIS_OLLAMA_URL": "http://127.0.0.1:9",
        "NERVA_WORKSPACE": "1",
        "NERVA_WORKSPACE_SETUP_CODE": required("WS_E2E_SETUP_CODE"),
    })
    return env


def main() -> int:
    run_dir = Path(required("WS_E2E_RUN_DIR"))
    log_path = run_dir / "hub.log"
    hub = subprocess.Popen(  # noqa: S603 — fixed argv: this interpreter and the repo's serve.py
        [sys.executable, str(REPO / "serve.py")], cwd=REPO, env=hub_environment(run_dir),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
    )

    def forward(signum: int, _frame: object) -> None:
        if hub.poll() is None:
            hub.send_signal(signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    def copy() -> None:
        stream = hub.stdout  # set: stdout=PIPE
        if stream is None:
            return
        with log_path.open("ab") as log:
            for line in iter(stream.readline, b""):
                log.write(line)
                log.flush()
                sys.stdout.buffer.write(line)
                sys.stdout.flush()

    copier = threading.Thread(target=copy, name="hub-log", daemon=True)
    copier.start()
    code = hub.wait()
    copier.join(timeout=5)
    if code:
        # Playwright shows this process's stderr only: say why the hub stopped and where to look.
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        print(f"workspace_hub.py: the hub exited with code {code}; last lines of {log_path}:",
              *tail, sep="\n", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
