"""
serve.py — Launch Cabinet Beta web UI with full feature stack.
Detects dependencies and starts the FastAPI server.
"""

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "agents"))

missing = []
try:
    import yaml
except ImportError:
    missing.append("pyyaml")
try:
    import httpx
except ImportError:
    missing.append("httpx")
try:
    import fastapi
except ImportError:
    missing.append("fastapi")
try:
    import uvicorn
except ImportError:
    missing.append("uvicorn")
try:
    # Hard-imported at module load by agents/core/plugins/oauth.py (pulled in via
    # the orchestrator); without it boot crashes with an opaque ImportError
    # instead of the friendly hint below.
    import cryptography.fernet  # noqa: F401  (availability probe, like the imports above)
except ImportError:
    missing.append("cryptography")

if missing:
    print(f"Missing dependencies: {', '.join(missing)}")
    print(f"Run: pip install -r requirements-beta.txt")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    warnings.warn("numpy not installed — vector store will be slower")

from agents.web import app

if __name__ == "__main__":
    print("Jarvis Hub starting at http://127.0.0.1:8080")
    print("Features: 16 agents, skills system, memory store, cost analytics, CI/CD")
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
