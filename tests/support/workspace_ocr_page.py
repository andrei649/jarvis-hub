"""Synthetic native OCR engine and descendants for owned-worker tests."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path


def fake_engine(data: bytes, index: int, seconds: float) -> str:
    mode = os.environ.get("NERVA_TEST_OCR_MODE", "text")
    if "descendant" in mode:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        Path(os.environ["NERVA_TEST_OCR_PID_FILE"]).write_text(str(child.pid))
    if mode == "c_stall" or mode == "hang_descendant":
        hashlib.pbkdf2_hmac("sha256", b"password", b"salt", 5_000_000)
    if mode == "error" or mode == "error_descendant":
        raise RuntimeError("synthetic page failure")
    if mode == "fail_second" and index == 1:
        raise RuntimeError("synthetic second-page failure")
    if mode == "early_exit_descendant":
        os._exit(7)
    if mode == "sleep_descendant":
        time.sleep(120)
    return f"Scannedword page {index + 1}"
