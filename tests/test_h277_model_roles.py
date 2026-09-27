"""H277 — separate models for separate jobs: the named-role table.

``agents/core/llm/model_roles.py`` is a frozen table of five roles (main, deep, vision,
video, approval_judge). Each resolves ``{provider_id, model, base_url}`` from
``JARVIS_ROLE_<NAME>_PROVIDER/_MODEL/_BASE_URL``, with the existing ``JARVIS_VLM_*`` and
``JARVIS_DEEP_MODEL`` names as fallbacks so an install that sets only those behaves
exactly as before. Provider ids are validated against the ProviderProfile ids.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agents.core.llm import model_config, model_roles, vlm
from agents.core.llm.model_roles import RoleConfigError
from agents.core.llm.vlm import LMSTUDIO_VLM_BASE, VLMConfig, VLMNotConfigured, resolve_vlm_config

REPO = Path(__file__).resolve().parent.parent

_ENV_NAMES = (
    "JARVIS_VLM_BACKEND", "JARVIS_VLM_URL", "JARVIS_VLM_MODEL", "JARVIS_VLM_KEY", "JARVIS_VLM_PRESET",
    "JARVIS_DEEP_MODEL", "JARVIS_LM_STUDIO_URL", "JARVIS_OLLAMA_URL", "OPENAI_BASE_URL",
    "JARVIS_STRICT_LOCAL", "JARVIS_SAFE_MODE",
    *(f"JARVIS_ROLE_{role}_{field}" for role in ("MAIN", "DEEP", "VISION", "VIDEO", "APPROVAL_JUDGE")
      for field in ("PROVIDER", "MODEL", "BASE_URL")),
    "JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE", "JARVIS_ROLE_APPROVAL_JUDGE_TIMEOUT",
    "JARVIS_ROLE_VISION_KEY", "JARVIS_ROLE_APPROVAL_JUDGE_KEY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


# ── the frozen pre-H277 resolve_vlm_config, for the byte-identical matrix ──────────────

def _old_resolve_vlm_config(env: dict) -> VLMConfig:
    def _get(name, default=""):
        return str(env.get(name, default) or default)

    backend = _get("JARVIS_VLM_BACKEND").strip().lower()
    url = _get("JARVIS_VLM_URL").strip()
    model = _get("JARVIS_VLM_MODEL").strip()
    api_key = _get("JARVIS_VLM_KEY")
    preset_name = _get("JARVIS_VLM_PRESET").strip().lower()
    if backend in {"", "off"} and not (backend == "" and url):
        raise VLMNotConfigured("vlm_disabled")
    if backend not in {"", "lmstudio", "custom"}:
        raise VLMNotConfigured("vlm_backend_unknown")
    preset_fields: dict = {}
    if preset_name:
        preset = vlm.resolve_vlm_preset(preset_name)
        if not model:
            raise VLMNotConfigured("vlm_model_unset")
        preset_fields = {"preset": preset.id, "convention": preset.convention}
    if backend == "lmstudio":
        if not model:
            raise VLMNotConfigured("vlm_model_unset")
        base = url or "http://localhost:1234/v1"
        return VLMConfig(backend="lmstudio", base_url=base, model=model, api_key=api_key,
                         is_local=vlm._is_loopback_base(base), **preset_fields)
    if not url:
        raise VLMNotConfigured("vlm_url_unset")
    return VLMConfig(backend="custom", base_url=url, model=model or "qwen2-vl", api_key=api_key,
                     is_local=vlm._is_loopback_base(url), **preset_fields)


LEGACY_MATRIX = [
    {},
    {"JARVIS_VLM_BACKEND": "off"},
    {"JARVIS_VLM_BACKEND": "off", "JARVIS_VLM_URL": "http://127.0.0.1:8000/v1"},
    {"JARVIS_VLM_BACKEND": ""},
    {"JARVIS_VLM_URL": "http://127.0.0.1:8000/v1"},
    {"JARVIS_VLM_URL": "https://vision.example.test/v1", "JARVIS_VLM_KEY": "k"},
    {"JARVIS_VLM_BACKEND": "custom"},
    {"JARVIS_VLM_BACKEND": "custom", "JARVIS_VLM_URL": "http://127.0.0.1:8000/v1"},
    {"JARVIS_VLM_BACKEND": "CUSTOM", "JARVIS_VLM_URL": " http://127.0.0.1:8000/v1 ", "JARVIS_VLM_MODEL": "qwen3-vl"},
    {"JARVIS_VLM_BACKEND": "lmstudio"},
    {"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_MODEL": "qwen3-vl-8b"},
    {"JARVIS_VLM_BACKEND": " LMStudio ", "JARVIS_VLM_MODEL": "qwen3-vl-8b", "JARVIS_VLM_URL": "http://192.168.1.9:1234/v1"},
    {"JARVIS_VLM_BACKEND": "vllm", "JARVIS_VLM_URL": "http://127.0.0.1:8000/v1"},
    {"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_PRESET": "qwen3-vl-8b"},
    {"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_PRESET": "qwen3-vl-8b", "JARVIS_VLM_MODEL": "qwen/qwen3-vl-8b"},
    {"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_PRESET": "nope", "JARVIS_VLM_MODEL": "m"},
]


def _outcome(fn, env):
    try:
        return ("ok", fn(env))
    except VLMNotConfigured as exc:
        return ("refused", exc.reason)


@pytest.mark.parametrize("env", LEGACY_MATRIX, ids=[str(i) for i in range(len(LEGACY_MATRIX))])
def test_legacy_vlm_env_resolves_byte_identically_through_an_env_mapping(env):
    assert _outcome(lambda e: resolve_vlm_config(env=e), env) == _outcome(_old_resolve_vlm_config, env)


@pytest.mark.parametrize("env", LEGACY_MATRIX, ids=[str(i) for i in range(len(LEGACY_MATRIX))])
def test_legacy_vlm_env_resolves_byte_identically_from_the_process_env(env, monkeypatch):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert _outcome(lambda _e: resolve_vlm_config(), env) == _outcome(_old_resolve_vlm_config, env)


# ── 1. the vision role falls back to the legacy names ─────────────────────────────────

def test_vision_role_falls_back_to_jarvis_vlm_model(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_BACKEND", "lmstudio")
    monkeypatch.setenv("JARVIS_VLM_MODEL", "qwen3-vl-8b")
    role = model_roles.resolve("vision")
    assert role.configured is True
    assert role.provider_id == "lm-studio"
    assert role.model == "qwen3-vl-8b"
    assert role.source["model"] == "JARVIS_VLM_MODEL"
    assert role.source["provider"] == "JARVIS_VLM_BACKEND"
    assert role.base_url == LMSTUDIO_VLM_BASE
    assert role.local is True and role.data_policy == "local"
    config = resolve_vlm_config()
    assert config == VLMConfig(backend="lmstudio", base_url=LMSTUDIO_VLM_BASE, model="qwen3-vl-8b",
                               api_key="", is_local=True)


def test_vision_role_off_by_default():
    role = model_roles.resolve("vision")
    assert role.configured is False and role.provider_id == "" and role.reason == "vlm_disabled"


# ── 3. the new name wins ──────────────────────────────────────────────────────────────

def test_role_model_overrides_the_legacy_model_and_names_the_shadowed_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_BACKEND", "lmstudio")
    monkeypatch.setenv("JARVIS_VLM_MODEL", "old-vl")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "new-vl")
    role = model_roles.resolve("vision")
    assert role.model == "new-vl" and role.source["model"] == "JARVIS_ROLE_VISION_MODEL"
    assert "JARVIS_VLM_MODEL" in role.ignored
    assert resolve_vlm_config().model == "new-vl"


def test_role_provider_openai_compatible_with_base_url_is_the_custom_backend(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "qwen3-vl")
    config = resolve_vlm_config()
    assert config.backend == "custom" and config.base_url == "http://127.0.0.1:8000/v1"
    assert config.model == "qwen3-vl" and config.is_local is True
    role = model_roles.resolve("vision")
    assert role.provider_id == "openai-compatible" and role.source["provider"] == "JARVIS_ROLE_VISION_PROVIDER"
    # the vision row carries the runtime's own label (VLMConfig.is_local), review F7
    assert role.local is config.is_local is True


def test_role_provider_lm_studio_maps_to_the_lmstudio_backend(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "LM-Studio")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "qwen3-vl-4b")
    monkeypatch.setenv("JARVIS_VLM_BACKEND", "off")   # the new name wins over a legacy off
    config = resolve_vlm_config()
    assert config.backend == "lmstudio" and config.base_url == LMSTUDIO_VLM_BASE
    assert "JARVIS_VLM_BACKEND" in model_roles.resolve("vision").ignored


def test_role_env_mapping_is_honoured(monkeypatch):
    env = {"JARVIS_ROLE_VISION_PROVIDER": "lm-studio", "JARVIS_ROLE_VISION_MODEL": "m"}
    assert resolve_vlm_config(env=env).backend == "lmstudio"
    assert model_roles.resolve("vision", env=env).model == "m"


# ── 4. an unknown provider is rejected ────────────────────────────────────────────────

def test_unknown_vision_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "lmstudio")   # a typo for lm-studio
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "m")
    with pytest.raises(RoleConfigError) as exc:
        model_roles.resolve("vision")
    assert exc.value.reason == "role_provider_unknown"
    assert "lm-studio" in exc.value.detail
    with pytest.raises(VLMNotConfigured) as refused:
        resolve_vlm_config()
    assert refused.value.reason == "role_provider_unknown"


def test_a_real_provider_the_vision_path_cannot_speak_is_unsupported(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "anthropic")
    with pytest.raises(RoleConfigError) as exc:
        model_roles.resolve("vision")
    assert exc.value.reason == "role_provider_unsupported"
    with pytest.raises(VLMNotConfigured) as refused:
        resolve_vlm_config()
    assert refused.value.reason == "role_provider_unsupported"


def test_provider_ids_are_the_provider_profile_ids():
    from agents.core.llm.providers import BUILTIN_PROVIDER_IDS

    for role in model_roles.ROLES.values():
        if role.providers is not None:
            assert role.providers <= frozenset(BUILTIN_PROVIDER_IDS), role.name


# ── 5. the deep role ─────────────────────────────────────────────────────────────────

def test_deep_role_defaults_and_is_not_pinned():
    assert model_config.deep_model_name() == model_config.DEFAULT_DEEP_MODEL
    assert model_config.deep_model_override_configured() is False
    assert model_roles.resolve("deep").source["model"] == "default"


def test_deep_role_legacy_pin(monkeypatch):
    monkeypatch.setenv("JARVIS_DEEP_MODEL", "local/deep-custom")
    assert model_config.deep_model_name() == "local/deep-custom"
    assert model_config.deep_model_override_configured() is True


def test_deep_role_new_name_wins(monkeypatch):
    monkeypatch.setenv("JARVIS_DEEP_MODEL", "local/old")
    monkeypatch.setenv("JARVIS_ROLE_DEEP_MODEL", "local/new")
    assert model_config.deep_model_name() == "local/new"
    assert model_config.deep_model_override_configured() is True
    assert "JARVIS_DEEP_MODEL" in model_roles.resolve("deep").ignored


def test_deep_role_whitespace_is_not_a_pin(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_DEEP_MODEL", "   ")
    monkeypatch.setenv("JARVIS_DEEP_MODEL", "  ")
    assert model_config.deep_model_name() == model_config.DEFAULT_DEEP_MODEL
    assert model_config.deep_model_override_configured() is False


def test_deep_role_provider_is_ignored_and_listed_never_raised(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_DEEP_PROVIDER", "no-such-provider")
    monkeypatch.setenv("JARVIS_ROLE_DEEP_BASE_URL", "http://x.test")
    role = model_roles.resolve("deep")
    assert set(role.ignored) >= {"JARVIS_ROLE_DEEP_PROVIDER", "JARVIS_ROLE_DEEP_BASE_URL"}
    assert role.provider_id == ""
    assert model_config.deep_model_name() == model_config.DEFAULT_DEEP_MODEL


# ── 6. main is not env-selectable ─────────────────────────────────────────────────────

def test_main_role_is_not_env_selectable(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_MAIN_MODEL", "x")
    monkeypatch.setenv("JARVIS_ROLE_MAIN_PROVIDER", "anthropic")
    role = model_roles.resolve("main")
    assert role.configured is False and role.model == "" and role.provider_id == ""
    assert role.reason == "role_not_env_selectable"
    assert set(role.ignored) == {"JARVIS_ROLE_MAIN_MODEL", "JARVIS_ROLE_MAIN_PROVIDER"}
    assert model_roles.ROLES["main"].providers is None


# ── 7. video is declared honestly ─────────────────────────────────────────────────────

def test_video_role_has_no_consumer_and_says_so(monkeypatch):
    assert model_roles.ROLES["video"].consumers == ()
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "ollama")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "llava")
    role = model_roles.resolve("video")
    assert role.configured is True and role.provider_id == "ollama"
    assert role.base_url == "http://localhost:11434" and role.local is True
    row = next(r for r in model_roles.describe() if r["role"] == "video")
    assert "nothing reads video yet" in row["note"]


def test_video_role_validates_its_provider(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "gemini")
    with pytest.raises(RoleConfigError) as exc:
        model_roles.resolve("video")
    assert exc.value.reason == "role_provider_unsupported"


def test_nothing_outside_model_roles_consumes_the_video_role():
    offenders = []
    for path in (REPO / "agents").rglob("*.py"):
        if path.name == "model_roles.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"resolve\(\s*[\"']video[\"']", text) or "JARVIS_ROLE_VIDEO" in text:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


# ── 8. the table is frozen ────────────────────────────────────────────────────────────

def test_role_table_is_frozen_and_has_exactly_five_roles():
    assert set(model_roles.ROLES) == {"main", "deep", "vision", "video", "approval_judge"}
    with pytest.raises(TypeError):
        model_roles.ROLES["extra"] = model_roles.ROLES["main"]   # type: ignore[index]
    with pytest.raises(AttributeError):
        model_roles.ROLES["main"].name = "x"                     # type: ignore[misc]


def test_unknown_role_name_is_a_key_error():
    with pytest.raises(KeyError):
        model_roles.resolve("audio")


# ── judge role resolution (the gating is in the approval-judge tests) ────────────────

def test_judge_role_uses_the_provider_profile_base_url(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "judge-m")
    role = model_roles.resolve("approval_judge")
    assert role.provider_id == "lm-studio" and role.source["provider"] == "default"
    assert role.base_url == "http://localhost:1234" and role.local is True
    monkeypatch.setenv("JARVIS_LM_STUDIO_URL", "http://192.168.1.20:1234")
    lan = model_roles.resolve("approval_judge")
    assert lan.base_url == "http://192.168.1.20:1234" and lan.local is False   # LAN is not local


def test_judge_role_rejects_a_cloud_vendor_this_cut_cannot_speak(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER", "anthropic")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "claude")
    with pytest.raises(RoleConfigError) as exc:
        model_roles.resolve("approval_judge")
    assert exc.value.reason == "role_provider_unsupported"


def test_describe_never_raises_and_reports_a_bad_role(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "nope")
    rows = {r["role"]: r for r in model_roles.describe()}
    assert set(rows) == set(model_roles.ROLES)
    assert rows["vision"]["configured"] is False and rows["vision"]["reason"] == "role_provider_unknown"
    assert rows["vision"]["error"] is True


def test_describe_carries_no_secret(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_BACKEND", "custom")
    monkeypatch.setenv("JARVIS_VLM_URL", "https://vision.example.test/v1")
    monkeypatch.setenv("JARVIS_VLM_KEY", "sk-secret-value")
    assert "sk-secret-value" not in repr(model_roles.describe())


# ── 9. env discipline ─────────────────────────────────────────────────────────────────

def test_model_roles_reads_no_raw_environment():
    src = Path(model_roles.__file__).read_text(encoding="utf-8")
    assert "os.environ" not in src and "os.getenv" not in src


def test_vlm_keeps_the_loopback_label_by_name():
    assert vlm._is_loopback_base is model_roles._is_loopback_base
    assert vlm.LMSTUDIO_VLM_BASE == "http://localhost:1234/v1"


# ── 10. the doctor row ────────────────────────────────────────────────────────────────

def test_doctor_model_roles_row_ok_by_default():
    from scripts import doctor

    check = doctor.check_model_roles({})
    assert check.name == "model_roles" and check.status == doctor.OK
    assert "approval_judge: off" in check.detail
    assert "model_roles" in doctor.ADVISORY


def test_doctor_model_roles_row_warns_on_a_bad_provider():
    from scripts import doctor

    check = doctor.check_model_roles({"JARVIS_ROLE_VISION_PROVIDER": "lmstudio"})
    assert check.status == doctor.WARN
    assert "role_provider_unknown" in check.reason + check.detail


def test_doctor_model_roles_row_warns_on_an_ignored_main_variable():
    from scripts import doctor

    check = doctor.check_model_roles({"JARVIS_ROLE_MAIN_MODEL": "x"})
    assert check.status == doctor.WARN and "JARVIS_ROLE_MAIN_MODEL" in check.detail


def test_doctor_model_roles_row_notes_a_second_lm_studio_model():
    from scripts import doctor

    check = doctor.check_model_roles({"JARVIS_ROLE_APPROVAL_JUDGE_MODEL": "qwen3-4b"})
    assert "may load a second model" in check.detail
    active = doctor.check_model_roles({"JARVIS_ROLE_APPROVAL_JUDGE_MODEL": "active"})
    assert "may load a second model" not in active.detail


# ══ review round (h277_review.json findings 3, 6, 7, 8) ════════════════════════════════

# F6/F7 — the doctor's vision row is built from resolve_vlm_config itself.

AGREEMENT_MATRIX = LEGACY_MATRIX + [
    {"JARVIS_VLM_BACKEND": "custom", "JARVIS_VLM_URL": "http://localhost:8000/v1"},
    {"JARVIS_VLM_URL": "http://localhost:8000/v1"},
    {"JARVIS_ROLE_VISION_PROVIDER": "openai-compatible"},
    {"JARVIS_ROLE_VISION_PROVIDER": "openai-compatible", "JARVIS_ROLE_VISION_BASE_URL": "https://v.example/v1"},
    {"JARVIS_ROLE_VISION_PROVIDER": "lm-studio"},
    {"JARVIS_ROLE_VISION_PROVIDER": "lm-studio", "JARVIS_ROLE_VISION_MODEL": "q"},
    {"JARVIS_ROLE_VISION_PROVIDER": "nope"},
    {"JARVIS_ROLE_VISION_PROVIDER": "anthropic"},
    {"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_MODEL": "q", "JARVIS_VLM_PRESET": "nope"},
]


def _role_outcome(env):
    try:
        return model_roles.resolve("vision", env=env)
    except RoleConfigError as exc:
        return exc.reason


@pytest.mark.parametrize("env", AGREEMENT_MATRIX, ids=[str(i) for i in range(len(AGREEMENT_MATRIX))])
def test_the_vision_row_agrees_with_resolve_vlm_config(env):
    from scripts import doctor

    runtime = _outcome(lambda e: resolve_vlm_config(env=e), env)
    role = _role_outcome(env)
    check = doctor.check_model_roles(env)
    vision = next(line for line in check.detail.split("; ") if line.startswith("vision:"))
    if runtime[0] == "refused":
        reason = runtime[1]
        assert (role if isinstance(role, str) else role.reason) == reason
        if not isinstance(role, str):
            assert role.configured is False
        assert vision.startswith(f"vision: off ({reason}")
        if reason != "vlm_disabled":
            assert check.status == doctor.WARN
        return
    config = runtime[1]
    assert role.configured is True
    assert role.provider_id == {"lmstudio": "lm-studio", "custom": "openai-compatible"}[config.backend]
    assert (role.model, role.base_url, role.local) == (config.model, config.base_url, config.is_local)
    assert f"({'local' if config.is_local else 'remote'}" in vision


def test_a_loopback_custom_vlm_is_listed_as_local():
    from scripts import doctor

    check = doctor.check_model_roles({"JARVIS_VLM_URL": "http://localhost:8000/v1"})
    assert "vision: openai-compatible/qwen2-vl (local" in check.detail


# F8 — model and base URL are compared exactly; only the provider selector is case-folded.

def test_a_legacy_model_differing_only_by_case_is_reported_as_shadowed(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_BACKEND", "lmstudio")
    monkeypatch.setenv("JARVIS_VLM_MODEL", "qwen3-vl")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "Qwen3-VL")
    assert "JARVIS_VLM_MODEL" in model_roles.resolve("vision").ignored
    monkeypatch.setenv("JARVIS_DEEP_MODEL", "X")
    monkeypatch.setenv("JARVIS_ROLE_DEEP_MODEL", "x")
    assert "JARVIS_DEEP_MODEL" in model_roles.resolve("deep").ignored


def test_a_legacy_base_url_differing_only_by_case_is_reported_as_shadowed(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_BACKEND", "custom")
    monkeypatch.setenv("JARVIS_VLM_URL", "http://127.0.0.1:8000/V1")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "http://127.0.0.1:8000/v1")
    assert "JARVIS_VLM_URL" in model_roles.resolve("vision").ignored


def test_the_provider_selector_still_compares_case_insensitively(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_BACKEND", "LMStudio")
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "LM-Studio")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "q")
    assert "JARVIS_VLM_BACKEND" not in model_roles.resolve("vision").ignored


# F3 (vision, same class) — JARVIS_VLM_KEY never follows a role base URL to another origin.

def test_the_legacy_vlm_key_never_goes_to_a_foreign_role_base_url(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_URL", "https://a.example/v1")
    monkeypatch.setenv("JARVIS_VLM_KEY", "sk-vision-a")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "https://b.example/v1")
    config = resolve_vlm_config()
    assert config.base_url == "https://b.example/v1" and config.api_key == ""


def test_the_dedicated_vision_role_key_goes_to_the_role_base_url(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_URL", "https://a.example/v1")
    monkeypatch.setenv("JARVIS_VLM_KEY", "sk-vision-a")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "https://b.example/v1")
    monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "sk-vision-b")
    assert resolve_vlm_config().api_key == "sk-vision-b"


@pytest.mark.parametrize("legacy, role_url, sent", [
    ({"JARVIS_VLM_URL": "https://a.example/v1"}, "https://a.example/v2", True),
    ({"JARVIS_VLM_URL": "https://a.example/v1"}, "https://a.example:8443/v1", False),
    ({"JARVIS_VLM_URL": "https://a.example/v1"}, "http://a.example/v1", False),
    ({"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_MODEL": "q"}, "http://localhost:1234/v1", True),
    ({"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_MODEL": "q"}, "http://192.168.1.9:1234/v1", False),
    ({"JARVIS_VLM_BACKEND": "custom"}, "https://b.example/v1", False),
])
def test_the_legacy_vlm_key_follows_only_its_own_origin(monkeypatch, legacy, role_url, sent):
    for name, value in legacy.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("JARVIS_VLM_KEY", "sk-vision-a")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", role_url)
    assert resolve_vlm_config().api_key == ("sk-vision-a" if sent else "")


def test_the_vision_role_key_is_ignored_without_a_role_base_url(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_URL", "https://a.example/v1")
    monkeypatch.setenv("JARVIS_VLM_KEY", "sk-vision-a")
    monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "sk-vision-b")
    assert resolve_vlm_config().api_key == "sk-vision-a"
    assert "JARVIS_ROLE_VISION_KEY" in model_roles.resolve("vision").ignored
    assert "sk-vision-b" not in repr(model_roles.describe())
