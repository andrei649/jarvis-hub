"""Mixture-of-Agents (MoA) committee presets & resilient hybrid runtime (H032).

Lets the owner define named committee presets (2–6 proposer model specs plus an
aggregator model spec), manage them from CLI (`nerva moa`) or HUD (`MoaPresetsPanel`),
and select a preset as a single model (`moa:<name>`) in chat/provider routing,
scheduled jobs, and sub-agents.

Nerva differentiators over naive upstream MoA:
- **Parallel quorum execution**: proposers run concurrently under a bounded per-proposer
  timeout (`timeout_s`); slow or failed proposers are tolerated when `>= min_quorum`
  succeed with non-degraded drafts.
- **Full governance & privacy inheritance**: strict-local agents (`LOCAL_ONLY_AGENTS`,
  `POLICY_LOCAL`, `JARVIS_STRICT_LOCAL`), `approved_models`, and H513 data-handling
  consent (`check_data_handling`) are verified for **every** proposer and the aggregator
  before any member executes.
- **Metadata-only telemetry**: bounded in-memory ring buffer records per-proposer latency,
  quorum health, and parallel speedup factor without storing prompt or answer text.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.core.env_config import env_flag
from agents.core.paths import data_root

from .base import LLMBackend, is_degraded_reply
from .tokenizer import estimate_tokens

PRESET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
MEMBER_SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
MOA_MODEL_PREFIX = "moa:"
MAX_PRESETS = 64
MIN_PROPOSERS = 2
MAX_PROPOSERS = 6
MAX_RECENT_RUNS = 50

_STORE_LOCK = threading.RLock()
_RECENT_RUNS: collections.deque[dict[str, Any]] = collections.deque(maxlen=MAX_RECENT_RUNS)

_LOCAL_SPECS = frozenset({"local", "local-deep", "ollama"})
_LOCAL_PREFIXES = ("lm-studio:", "ollama:", "local:")


class MoAConfigError(ValueError):
    """Invalid Mixture-of-Agents preset configuration or unknown preset."""


@dataclass(frozen=True)
class MoAPreset:
    name: str
    proposers: tuple[str, ...]
    aggregator: str
    description: str = ""
    min_quorum: int = 2
    timeout_s: float = 45.0
    temperature: float = 0.6

    @property
    def model_id(self) -> str:
        return f"{MOA_MODEL_PREFIX}{self.name}"

    @property
    def is_pure_local(self) -> bool:
        return all(_spec_is_local_only(s) for s in (*self.proposers, self.aggregator))

    @property
    def digest(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "description": self.description,
            "proposers": list(self.proposers),
            "aggregator": self.aggregator,
            "min_quorum": self.min_quorum,
            "timeout_s": self.timeout_s,
            "temperature": self.temperature,
            "pure_local": self.is_pure_local,
        }


def _spec_is_local_only(spec: str) -> bool:
    low = spec.strip().lower()
    if low in _LOCAL_SPECS or low.startswith(_LOCAL_PREFIXES):
        return True
    # Bare model id without a cloud prefix resolves against the local backend slot.
    return not (
        low in {"gemini", "claude", "cloud", "compatible"}
        or low.startswith(("gemini:", "claude:", "anthropic:", "openai:", "openrouter:", "compatible:"))
    )


def validate_preset(
    name: str,
    *,
    proposers: list[str] | tuple[str, ...],
    aggregator: str,
    description: str = "",
    min_quorum: int | None = None,
    timeout_s: float = 45.0,
    temperature: float = 0.6,
) -> MoAPreset:
    clean_name = (name or "").strip()
    if not PRESET_NAME_RE.fullmatch(clean_name):
        raise MoAConfigError("preset name must match ^[a-z0-9][a-z0-9_-]{0,47}$")
    if not isinstance(proposers, (list, tuple)):
        raise MoAConfigError("proposers must be a list of 2 to 6 model specs")
    clean_props = tuple(str(p).strip() for p in proposers if str(p).strip())
    if not (MIN_PROPOSERS <= len(clean_props) <= MAX_PROPOSERS):
        raise MoAConfigError(f"proposers must contain {MIN_PROPOSERS} to {MAX_PROPOSERS} model specs")
    for spec in clean_props:
        if not MEMBER_SPEC_RE.fullmatch(spec) or spec.lower().startswith(MOA_MODEL_PREFIX):
            raise MoAConfigError(f"invalid or recursive proposer spec: '{spec}'")
    clean_agg = (aggregator or "").strip()
    if not MEMBER_SPEC_RE.fullmatch(clean_agg) or clean_agg.lower().startswith(MOA_MODEL_PREFIX):
        raise MoAConfigError(f"invalid or recursive aggregator spec: '{clean_agg}'")
    clean_desc = str(description or "").strip()[:240]
    quorum = ((len(clean_props) + 1) // 2) if min_quorum is None else int(min_quorum)
    if isinstance(min_quorum, bool) or not (1 <= quorum <= len(clean_props)):
        raise MoAConfigError(f"min_quorum must be between 1 and {len(clean_props)}")
    if isinstance(timeout_s, bool) or not (2.0 <= float(timeout_s) <= 180.0):
        raise MoAConfigError("timeout_s must be between 2 and 180 seconds")
    if isinstance(temperature, bool) or not (0.0 <= float(temperature) <= 1.5):
        raise MoAConfigError("temperature must be between 0.0 and 1.5")
    return MoAPreset(
        name=clean_name,
        proposers=clean_props,
        aggregator=clean_agg,
        description=clean_desc,
        min_quorum=quorum,
        timeout_s=round(float(timeout_s), 2),
        temperature=round(float(temperature), 2),
    )


def _store_path() -> Path:
    if env_flag("JARVIS_TESTING", False) and not os.environ.get("JARVIS_HOME", "").strip():
        # Keep unconfigured unit tests hermetic against a developer's local memory_logs/.
        return data_root() / ".test_isolated_moa_presets.json"
    return data_root() / "moa_presets.json"


def _read_raw() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"presets": {}, "active": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"presets": {}, "active": None}
    if not isinstance(data, dict):
        return {"presets": {}, "active": None}
    presets = data.get("presets")
    active = data.get("active")
    return {
        "presets": presets if isinstance(presets, dict) else {},
        "active": active if isinstance(active, str) and PRESET_NAME_RE.fullmatch(active) else None,
    }


def _write_raw(state: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}")
    payload = json.dumps(state, indent=2, sort_keys=True)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()


def list_presets() -> list[MoAPreset]:
    with _STORE_LOCK:
        raw = _read_raw()
        out: list[MoAPreset] = []
        for name, item in sorted(raw["presets"].items()):
            if not isinstance(item, dict):
                continue
            try:
                out.append(
                    validate_preset(
                        name,
                        proposers=item.get("proposers") or [],
                        aggregator=str(item.get("aggregator") or ""),
                        description=str(item.get("description") or ""),
                        min_quorum=item.get("min_quorum"),
                        timeout_s=float(item.get("timeout_s", 45.0)),
                        temperature=float(item.get("temperature", 0.6)),
                    )
                )
            except MoAConfigError:
                continue
        return out


def get_preset(name_or_model: str) -> MoAPreset | None:
    key = parse_moa_model_name(name_or_model) or (name_or_model or "").strip()
    if not PRESET_NAME_RE.fullmatch(key):
        return None
    for p in list_presets():
        if p.name == key:
            return p
    return None


def save_preset(preset: MoAPreset) -> MoAPreset:
    with _STORE_LOCK:
        raw = _read_raw()
        presets = dict(raw["presets"])
        if preset.name not in presets and len(presets) >= MAX_PRESETS:
            raise MoAConfigError(f"maximum of {MAX_PRESETS} MoA presets reached")
        presets[preset.name] = {
            "description": preset.description,
            "proposers": list(preset.proposers),
            "aggregator": preset.aggregator,
            "min_quorum": preset.min_quorum,
            "timeout_s": preset.timeout_s,
            "temperature": preset.temperature,
        }
        raw["presets"] = presets
        _write_raw(raw)
        return preset


def delete_preset(name: str) -> bool:
    clean = (name or "").strip()
    with _STORE_LOCK:
        raw = _read_raw()
        if clean not in raw["presets"]:
            return False
        presets = dict(raw["presets"])
        del presets[clean]
        raw["presets"] = presets
        if raw.get("active") == clean:
            raw["active"] = None
        _write_raw(raw)
        return True


def get_active_preset_name() -> str | None:
    path = _store_path()
    if not path.is_file():
        return None
    with _STORE_LOCK:
        raw = _read_raw()
        active = raw.get("active")
        if active and active in raw["presets"]:
            return active
        return None


def set_active_preset(name: str | None) -> MoAPreset | None:
    with _STORE_LOCK:
        raw = _read_raw()
        if name is None or not str(name).strip():
            raw["active"] = None
            _write_raw(raw)
            return None
        clean = parse_moa_model_name(name) or str(name).strip()
        if clean not in raw["presets"]:
            raise MoAConfigError(f"unknown MoA preset '{clean}'")
        raw["active"] = clean
        _write_raw(raw)
    return get_preset(clean)


def parse_moa_model_name(model: str | None) -> str | None:
    if not isinstance(model, str):
        return None
    trimmed = model.strip()
    if not trimmed.lower().startswith(MOA_MODEL_PREFIX):
        return None
    name = trimmed[len(MOA_MODEL_PREFIX):].strip()
    return name if PRESET_NAME_RE.fullmatch(name) else None


def recent_runs() -> list[dict[str, Any]]:
    return list(_RECENT_RUNS)


def clear_recent_runs() -> None:
    _RECENT_RUNS.clear()


def resolve_member_spec(router: Any, spec: str) -> tuple[LLMBackend, str, str]:
    """Resolve one member spec against *router* into ``(backend, model, route)``."""
    from .hybrid_router import LocalBackendUnavailableError

    s = spec.strip()
    low = s.lower()

    if low == "local":
        if not getattr(router, "_local_available", False) or getattr(router, "_backend", None) is None:
            raise LocalBackendUnavailableError("local backend is unavailable for MoA member 'local'")
        return router._backend, router._local_model, "local"

    if low == "local-deep":
        if not getattr(router, "_local_available", False) or getattr(router, "_backend", None) is None:
            raise LocalBackendUnavailableError("local backend is unavailable for MoA member 'local-deep'")
        return router._backend, router._configured_deep_model(), "local-deep"

    if low == "ollama" or low.startswith("ollama:"):
        explicit = s.split(":", 1)[1].strip() if ":" in s else ""
        ollama = getattr(router, "_ollama_backend", None)
        if not getattr(router, "_ollama_available", False) or ollama is None:
            raise LocalBackendUnavailableError(f"Ollama backend is unavailable for MoA member '{s}'")
        return ollama, (explicit or router.get_howard_model()), "local-ollama"

    if low.startswith(("lm-studio:", "local:")):
        explicit = s.split(":", 1)[1].strip()
        if not getattr(router, "_local_available", False) or getattr(router, "_backend", None) is None:
            raise LocalBackendUnavailableError(f"local backend is unavailable for MoA member '{s}'")
        return router._backend, (explicit or router._local_model), "local"

    if low == "gemini" or low.startswith("gemini:"):
        explicit = s.split(":", 1)[1].strip() if ":" in s else ""
        gem = getattr(router, "_gemini_backend", None)
        if not router._cloud_permitted() or gem is None:
            raise LocalBackendUnavailableError(f"Gemini cloud backend is unavailable or disallowed for '{s}'")
        return gem, (explicit or router._gemini_model), "cloud"

    if low == "claude" or low.startswith(("claude:", "anthropic:")):
        explicit = s.split(":", 1)[1].strip() if ":" in s else ""
        claude = getattr(router, "_claude_backend", None)
        if env_flag("JARVIS_STRICT_LOCAL", False) or not getattr(router, "_claude_available", False) or claude is None:
            raise LocalBackendUnavailableError(f"Claude backend is unavailable or disallowed for '{s}'")
        return claude, (explicit or router._claude_model), "claude"

    if low == "compatible" or low.startswith("compatible:"):
        explicit = s.split(":", 1)[1].strip() if ":" in s else ""
        comp = getattr(router, "_compatible_backend", None)
        if env_flag("JARVIS_STRICT_LOCAL", False) or comp is None:
            raise LocalBackendUnavailableError(f"compatible cloud backend is unavailable for '{s}'")
        model = explicit or getattr(router, "_compatible_model", "")
        router._check_selected_cloud_route(comp, model, "cloud-compatible")
        return comp, model, "cloud-compatible"

    # Bare model identifier -> local backend slot.
    if not getattr(router, "_local_available", False) or getattr(router, "_backend", None) is None:
        raise LocalBackendUnavailableError(f"local backend is unavailable for MoA model '{s}'")
    return router._backend, s, "local"


def _build_synthesis_prompt(original_prompt: str, drafts: list[tuple[str, str, str]]) -> str:
    sections = [
        f"### Candidate {idx} ({spec} · {model})\n{text.strip()}"
        for idx, (spec, model, text) in enumerate(drafts, start=1)
    ]
    joined = "\n\n".join(sections)
    return (
        "You are the synthesis aggregator of a Mixture-of-Agents committee.\n"
        "Review the user's request and the candidate responses below. Cross-check claims, "
        "discard contradictions or unsupported guesses, and synthesize one clear, accurate, "
        "well-structured final response. Do not mention candidate numbers unless helpful.\n\n"
        f"## User Request\n{original_prompt}\n\n"
        f"## Candidate Responses\n{joined}\n\n"
        "## Final Synthesized Answer"
    )


class MoACommitteeBackend(LLMBackend):
    """Executes a Mixture-of-Agents committee preset as a single LLMBackend."""

    def __init__(
        self,
        *,
        router: Any,
        agent_id: str,
        preset: MoAPreset,
        proposer_bindings: list[tuple[str, LLMBackend, str, str]],
        aggregator_binding: tuple[str, LLMBackend, str, str],
    ):
        self._router = router
        self._agent_id = agent_id
        self.preset = preset
        self._proposers = proposer_bindings
        self._agg_spec, self._agg_backend, self._agg_model, self._agg_route = aggregator_binding
        # Expose underlying aggregator for data_handling._unwrap inspection.
        self._backend = self._agg_backend
        self.last_run_telemetry: dict[str, Any] | None = None

    def context_window(self, model: str | None = None) -> int:
        windows: list[int] = []
        for _, backend, member_model, _ in [*self._proposers, (self._agg_spec, self._agg_backend, self._agg_model, self._agg_route)]:
            probe = getattr(backend, "context_window", None)
            if callable(probe):
                try:
                    w = probe(member_model)
                    if isinstance(w, int) and w > 0:
                        windows.append(w)
                except Exception:
                    pass
        return min(windows) if windows else 32768

    async def is_available(self) -> bool:
        return await self._agg_backend.is_available()

    async def list_models(self) -> list[str]:
        return [self.preset.model_id]

    def authorize_data_handling(self, *, actual_use: bool = True) -> dict[str, Any] | None:
        """Authorize H513 data-handling consent across EVERY proposer and the aggregator."""
        from .data_handling import authorize

        all_members = [
            *self._proposers,
            (self._agg_spec, self._agg_backend, self._agg_model, self._agg_route),
        ]
        last: dict[str, Any] | None = None
        for _, backend, member_model, member_route in all_members:
            try:
                last = authorize(
                    self._router, backend, member_model, member_route, actual_use=actual_use,
                )
            except ValueError as exc:
                # Allow unprobed pure-local unit-test fixtures (`_backend_name == "none"`)
                # while keeping every non-local route strictly fail-closed.
                if (
                    member_route.startswith("local")
                    and getattr(self._router, "_backend_name", "none") == "none"
                    and getattr(backend, "profile", None) is None
                    and "unknown" in str(exc)
                ):
                    continue
                raise
        return last

    def _authorize_all_members(self) -> None:
        """Enforce strict-local, approved-models, and H513 data-handling consent for every member."""
        from .hybrid_router import LOCAL_ONLY_AGENTS, POLICY_LOCAL, LocalBackendUnavailableError

        strict_local = (
            env_flag("JARVIS_STRICT_LOCAL", False)
            or self._agent_id in LOCAL_ONLY_AGENTS
            or self._router.get_agent_policy(self._agent_id) == POLICY_LOCAL
        )
        all_members = [
            *self._proposers,
            (self._agg_spec, self._agg_backend, self._agg_model, self._agg_route),
        ]
        for spec, _backend, member_model, member_route in all_members:
            if strict_local and not member_route.startswith("local"):
                raise LocalBackendUnavailableError(
                    f"MoA preset '{self.preset.name}' member '{spec}' uses non-local route "
                    f"'{member_route}', which is forbidden for strict-local agent '{self._agent_id}'"
                )
            self._router._enforce_approved_models(self._agent_id, member_model, member_route)
        check = getattr(self._router, "check_data_handling", None)
        if callable(check):
            check(self, self.preset.model_id, "hybrid-moa" if not self.preset.is_pure_local else "local-moa", actual_use=True)

    async def _run_proposers(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        on_activity: Callable[[], None] | None = None,
    ) -> tuple[list[tuple[str, str, str]], list[dict[str, Any]], float]:
        self._authorize_all_members()
        started = time.perf_counter()

        async def _call_one(spec: str, backend: LLMBackend, member_model: str, member_route: str):
            t0 = time.perf_counter()
            try:
                await self._router.ensure_resident(member_model, member_route)
                text = await asyncio.wait_for(
                    backend.generate(
                        member_model,
                        prompt,
                        system=system,
                        max_tokens=max_tokens,
                        temperature=self.preset.temperature,
                    ),
                    timeout=self.preset.timeout_s,
                )
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                ok = bool(text and text.strip() and not is_degraded_reply(text))
                if callable(on_activity):
                    with contextlib.suppress(Exception):
                        on_activity()
                return (
                    (spec, member_model, text) if ok else None,
                    {
                        "spec": spec,
                        "model": member_model,
                        "route": member_route,
                        "ok": ok,
                        "latency_ms": elapsed_ms,
                        "tokens_est": estimate_tokens(text) if ok else 0,
                        "reason": None if ok else "degraded_or_empty",
                    },
                )
            except TimeoutError:
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                return None, {
                    "spec": spec,
                    "model": member_model,
                    "route": member_route,
                    "ok": False,
                    "latency_ms": elapsed_ms,
                    "tokens_est": 0,
                    "reason": "timeout",
                }
            except Exception as exc:
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                return None, {
                    "spec": spec,
                    "model": member_model,
                    "route": member_route,
                    "ok": False,
                    "latency_ms": elapsed_ms,
                    "tokens_est": 0,
                    "reason": type(exc).__name__,
                }

        pairs = await asyncio.gather(*(_call_one(*m) for m in self._proposers))
        proposer_wall_ms = round((time.perf_counter() - started) * 1000.0, 2)
        drafts = [d for d, _ in pairs if d is not None]
        metrics = [m for _, m in pairs]
        return drafts, metrics, proposer_wall_ms

    def _record_telemetry(
        self,
        *,
        ok: bool,
        drafts_count: int,
        proposer_metrics: list[dict[str, Any]],
        proposer_wall_ms: float,
        agg_ms: float,
        total_ms: float,
    ) -> dict[str, Any]:
        sum_prop_ms = round(sum(float(m["latency_ms"]) for m in proposer_metrics), 2)
        speedup = round(sum_prop_ms / max(proposer_wall_ms, 0.01), 2) if proposer_metrics else 1.0
        entry = {
            "ts": round(time.time(), 3),
            "preset": self.preset.name,
            "agent": self._agent_id,
            "ok": ok,
            "quorum_met": drafts_count >= self.preset.min_quorum,
            "succeeded": drafts_count,
            "min_quorum": self.preset.min_quorum,
            "total_proposers": len(self._proposers),
            "proposer_wall_ms": proposer_wall_ms,
            "sum_proposer_ms": sum_prop_ms,
            "parallel_speedup": speedup,
            "aggregator": {
                "spec": self._agg_spec,
                "model": self._agg_model,
                "route": self._agg_route,
                "latency_ms": agg_ms,
            },
            "total_ms": total_ms,
            "proposers": proposer_metrics,
        }
        self.last_run_telemetry = entry
        _RECENT_RUNS.appendleft(entry)
        return entry

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        t_start = time.perf_counter()
        drafts, metrics, prop_wall_ms = await self._run_proposers(prompt, system, max_tokens)
        if len(drafts) < self.preset.min_quorum:
            total_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
            self._record_telemetry(
                ok=False,
                drafts_count=len(drafts),
                proposer_metrics=metrics,
                proposer_wall_ms=prop_wall_ms,
                agg_ms=0.0,
                total_ms=total_ms,
            )
            raise RuntimeError(
                f"MoA preset '{self.preset.name}' quorum not met "
                f"({len(drafts)}/{self.preset.min_quorum} proposers succeeded)"
            )

        synth_prompt = _build_synthesis_prompt(prompt, drafts)
        await self._router.ensure_resident(self._agg_model, self._agg_route)
        t_agg = time.perf_counter()
        final = await asyncio.wait_for(
            self._agg_backend.generate(
                self._agg_model,
                synth_prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=min(temperature, self.preset.temperature),
            ),
            timeout=self.preset.timeout_s,
        )
        agg_ms = round((time.perf_counter() - t_agg) * 1000.0, 2)
        total_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
        ok = bool(final and final.strip() and not is_degraded_reply(final))
        self._record_telemetry(
            ok=ok,
            drafts_count=len(drafts),
            proposer_metrics=metrics,
            proposer_wall_ms=prop_wall_ms,
            agg_ms=agg_ms,
            total_ms=total_ms,
        )
        return final

    async def generate_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        on_token: Callable[[str], None] | None = None,
        on_activity: Callable[[], None] | None = None,
        **kwargs,
    ) -> str:
        t_start = time.perf_counter()
        drafts, metrics, prop_wall_ms = await self._run_proposers(
            prompt, system, max_tokens, on_activity=on_activity,
        )
        if len(drafts) < self.preset.min_quorum:
            total_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
            self._record_telemetry(
                ok=False,
                drafts_count=len(drafts),
                proposer_metrics=metrics,
                proposer_wall_ms=prop_wall_ms,
                agg_ms=0.0,
                total_ms=total_ms,
            )
            raise RuntimeError(
                f"MoA preset '{self.preset.name}' quorum not met "
                f"({len(drafts)}/{self.preset.min_quorum} proposers succeeded)"
            )

        synth_prompt = _build_synthesis_prompt(prompt, drafts)
        await self._router.ensure_resident(self._agg_model, self._agg_route)
        t_agg = time.perf_counter()
        final = ""
        try:
            final = await asyncio.wait_for(
                self._agg_backend.generate_stream(
                    self._agg_model,
                    synth_prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=min(temperature, self.preset.temperature),
                    on_token=on_token,
                    on_activity=on_activity,
                ),
                timeout=self.preset.timeout_s,
            )
            return final
        finally:
            agg_ms = round((time.perf_counter() - t_agg) * 1000.0, 2)
            total_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
            ok = bool(final and final.strip() and not is_degraded_reply(final))
            self._record_telemetry(
                ok=ok,
                drafts_count=len(drafts),
                proposer_metrics=metrics,
                proposer_wall_ms=prop_wall_ms,
                agg_ms=agg_ms,
                total_ms=total_ms,
            )


def build_moa_backend(router: Any, agent_id: str, name_or_model: str) -> tuple[MoACommitteeBackend, str, str]:
    """Resolve *name_or_model* (`moa:<name>` or `<name>`) into a cached `(MoACommitteeBackend, model_id, route)`."""
    from .hybrid_router import LOCAL_ONLY_AGENTS, POLICY_LOCAL, LocalBackendUnavailableError

    preset = get_preset(name_or_model)
    if preset is None:
        raise MoAConfigError(f"unknown MoA preset '{name_or_model}'")

    proposer_bindings = [(spec, *resolve_member_spec(router, spec)) for spec in preset.proposers]
    agg_binding = (preset.aggregator, *resolve_member_spec(router, preset.aggregator))

    all_routes = [r for _, _, _, r in [*proposer_bindings, agg_binding]]
    pure_local = all(r.startswith("local") for r in all_routes)
    strict_local = (
        env_flag("JARVIS_STRICT_LOCAL", False)
        or agent_id in LOCAL_ONLY_AGENTS
        or router.get_agent_policy(agent_id) == POLICY_LOCAL
    )
    if strict_local and not pure_local:
        raise LocalBackendUnavailableError(
            f"MoA preset '{preset.name}' includes cloud member(s) and cannot run for strict-local agent '{agent_id}'"
        )
    for _, _, member_model, member_route in [*proposer_bindings, agg_binding]:
        router._enforce_approved_models(agent_id, member_model, member_route)

    route = "local-moa" if pure_local else "hybrid-moa"
    cache: dict[tuple[str, str, str], MoACommitteeBackend] = getattr(router, "_moa_backend_cache", None)
    if cache is None:
        cache = {}
        router._moa_backend_cache = cache
    cache_key = (agent_id, preset.name, preset.digest)
    instance = cache.get(cache_key)
    if instance is None:
        instance = MoACommitteeBackend(
            router=router,
            agent_id=agent_id,
            preset=preset,
            proposer_bindings=proposer_bindings,
            aggregator_binding=agg_binding,
        )
        cache[cache_key] = instance
    return instance, preset.model_id, route
