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
    print("Cabinet v0.2.0 starting at http://127.0.0.1:8000")
    print("Features: 15 agents, skills system, checkpointing, structured sessions, gateway")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
