#!/usr/bin/env python3
"""Replay exact-commit selected-image review mutations in a disposable archive."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ENGINE = Path(__file__).with_name("h277-selected-route-mutations-2026-10-02.py")
spec = importlib.util.spec_from_file_location("h277_image_mutation_engine", ENGINE)
if spec is None or spec.loader is None:
    raise RuntimeError("H277 mutation engine unavailable")
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)

engine.REPO = Path(__file__).resolve().parents[3]
engine.TEST = "tests/test_h277_selected_composer.py"
engine.SCOPE = {"agents/core/routers/composer_vision.py"}
COMPOSER = "agents/core/routers/composer_vision.py"
engine.CASES = [
    engine.case(
        "01_drop_image_binding", "Issue a selected review without binding image data.",
        ["test_selected_review_refuses_a_different_image_after_preflight"],
        (COMPOSER,
         'return identity.binding + ("reviewed-image-digests:v1", tuple(image_digests))',
         "return identity.binding"),
    ),
    engine.case(
        "02_allow_missing_digest", "Issue a selected review without image digests.",
        ["test_selected_review_requires_image_digests_before_issuing_token"],
        (COMPOSER, "if self.selected_turn and not self.image_digests:", "if False:"),
        (COMPOSER, "tuple(image_digests))", "tuple(image_digests or ()))"),
    ),
    engine.case(
        "03_forget_image_order", "Treat reordered reviewed images as equivalent.",
        ["test_selected_review_refuses_reordered_images"],
        (COMPOSER, "tuple(image_digests))", "tuple(sorted(image_digests)))"),
    ),
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True, help="full frozen source commit SHA")
    engine.main(parser.parse_args().commit)
