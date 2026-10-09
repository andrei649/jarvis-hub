#!/usr/bin/env python3
"""Exact-commit automatic vision mutation campaign using the H277 harness."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "h277_mutation_harness", HERE / "h277-vision-normalization-mutations-2026-10-02.py"
)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)

AUTO = "agents/core/llm/vision_auto.py"
COMPOSER = "agents/core/routers/composer_vision.py"
RESOLUTION = "tests/test_h277_vision_auto_resolution.py"
CONSUMER = "tests/test_h277_vision_auto_consumer.py"

harness.SOURCE_SCOPE = [AUTO, COMPOSER]
harness.TESTS = [RESOLUTION, CONSUMER]
harness.CASES = [
    {
        "id": "01_role_key_scope", "file": AUTO,
        "anchor": '            if key == "JARVIS_ROLE_VISION_KEY":\n                # A role key is authority for an explicit endpoint, not for an\n                # automatically discovered provider\'s canonical origin.\n                return ""\n',
        "replacement": '            if key == "JARVIS_ROLE_VISION_KEY":\n                return _read(self.env, key)\n',
        "intent": "Allow an explicit role key to leak into discovered provider selection.",
        "tests": [f"{RESOLUTION}::test_prepare_skips_unavailable_providers_in_order"],
    },
    {
        "id": "02_explicit_override", "file": AUTO,
        "anchor": '    if override is not None:\n        return override\n    main = _main(main_config, model)\n    if main is not None:\n        return main\n    for provider in',
        "replacement": '    if False:\n        return override\n    main = _main(main_config, model)\n    if main is not None:\n        return main\n    for provider in',
        "intent": "Ignore the owner's explicit vision endpoint in pure resolution.",
        "tests": [f"{RESOLUTION}::test_explicit_base_is_authoritative_and_requires_model_and_scoped_key"],
    },
    {
        "id": "03_selected_main", "file": AUTO,
        "anchor": '    if main is not None:\n        return main\n    for provider in',
        "replacement": '    if False:\n        return main\n    for provider in',
        "intent": "Discard the actual selected main vision route.",
        "tests": [f"{RESOLUTION}::test_main_candidate_requires_an_explicit_selected_config"],
    },
    {
        "id": "04_role_model", "file": AUTO,
        "anchor": '        return replace(main_config, model=model or main_config.model, route_source="auto:main")\n',
        "replacement": '        return replace(main_config, model=main_config.model, route_source="auto:main")\n',
        "intent": "Ignore the explicit vision-role model on the selected main route.",
        "tests": [f"{RESOLUTION}::test_explicit_role_model_overrides_selected_main_model"],
    },
    {
        "id": "05_policy_fail_closed", "file": AUTO,
        "anchor": '    if provider == "openrouter":\n        _policy()\n        return vision_openrouter.resolve_config(view)\n',
        "replacement": '    if provider == "openrouter":\n        return vision_openrouter.resolve_config(view)\n',
        "intent": "Skip the live OpenRouter provider policy validation.",
        "tests": [f"{RESOLUTION}::test_malformed_provider_policy_refuses_without_fallback"],
    },
    {
        "id": "06_prepare_order", "file": AUTO,
        "anchor": '    for provider, module in (("nous", vision_nous), ("deepinfra", vision_deepinfra)):\n',
        "replacement": '    for provider, module in (("deepinfra", vision_deepinfra), ("nous", vision_nous)):\n',
        "intent": "Prefer DeepInfra over Nous after OpenRouter is unavailable.",
        "tests": [f"{RESOLUTION}::test_prepare_skips_unavailable_providers_in_order"],
    },
    {
        "id": "07_priority_recheck", "file": AUTO,
        "anchor": '        if current != prepared:\n            raise VLMNotConfigured("vlm_selection_changed")\n',
        "replacement": '        if False:\n            raise VLMNotConfigured("vlm_selection_changed")\n',
        "intent": "Keep a prepared lower-priority account after a higher-priority one appears.",
        "tests": [f"{RESOLUTION}::test_preparation_rechecks_higher_priority_account_state"],
    },
    {
        "id": "08_status_no_prepare", "file": COMPOSER,
        "anchor": '        elif env_str("JARVIS_ROLE_VISION_PROVIDER", "").strip().lower() == "auto":\n            from agents.core.llm.vision_auto import prepare_config\n            config = await prepare_config(force_refresh=refresh_catalog)\n',
        "replacement": '        elif env_str("JARVIS_ROLE_VISION_PROVIDER", "").strip().lower() == "auto":\n            config = resolve_vlm_config()\n',
        "intent": "Omit metadata preparation before showing the chosen destination.",
        "tests": [f"{CONSUMER}::test_auto_status_prepares_deepinfra_catalog_before_review"],
    },
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("baseline", "mutations"))
    parser.add_argument("--commit", required=True)
    arguments = parser.parse_args()
    harness.COMMIT = arguments.commit
    harness.OUT = Path(f"/tmp/nerva-vision-auto-mutations-20261002-{arguments.commit[:12]}")
    if arguments.phase == "baseline":
        harness.baseline()
    else:
        harness.mutations()
