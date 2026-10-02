#!/usr/bin/env python3
"""Replay exact-commit Ollama image-wire mutations with the shared offline runner."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ENGINE = Path(__file__).with_name("h277-selected-route-mutations-2026-10-02.py")
spec = importlib.util.spec_from_file_location("h277_mutation_engine", ENGINE)
if spec is None or spec.loader is None:
    raise RuntimeError("H277 mutation engine unavailable")
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)

engine.REPO = Path(__file__).resolve().parents[3]
engine.TEST = "tests/test_h277_ollama_vision.py"
engine.SCOPE = {
    "agents/core/llm/vision_ollama_wire.py",
    "agents/core/llm/vlm.py",
    "agents/core/llm/vision_auto.py",
    "agents/core/llm/vision_policy.py",
    "agents/core/routers/composer_vision.py",
}
engine.CASES = [
    engine.case(
        "01_ollama_image_bytes", "Drop the reviewed image bytes from Ollama's native body.",
        ["test_selected_ollama_image_uses_native_chat_wire"],
        ("agents/core/llm/vision_ollama_wire.py", "images.append(data)", "images.append('')"),
    ),
    engine.case(
        "02_ollama_native_endpoint", "Send selected Ollama images to a chat-completions path.",
        ["test_selected_ollama_image_uses_native_chat_wire"],
        ("agents/core/llm/vlm.py", '"/api/chat" if native_ollama else',
         '"/chat/completions" if native_ollama else'),
    ),
    engine.case(
        "03_main_selection", "Omit Ollama from the selected-main vision candidates.",
        ["test_selected_ollama_image_uses_native_chat_wire"],
        ("agents/core/llm/vision_auto.py", '"lmstudio", "ollama", "custom"',
         '"lmstudio", "custom"'),
    ),
    engine.case(
        "04_remote_ack", "Send remote Ollama images without remote acknowledgement.",
        ["test_remote_ollama_requires_explicit_acknowledgement"],
        ("agents/core/routers/composer_vision.py", "if not config.is_local and not body.remote_ack:",
         "if False:"),
    ),
    engine.case(
        "05_final_body_guard", "Skip image-body digest verification at physical egress.",
        ["test_late_ollama_image_body_mutation_never_reaches_transport"],
        ("agents/core/llm/vision_policy.py", "if recovery.started or image_bearing:",
         "if False:"),
    ),
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True, help="exact frozen source commit SHA")
    engine.main(parser.parse_args().commit)
