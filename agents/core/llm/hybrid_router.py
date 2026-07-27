"""
hybrid_router.py — Multi-factor LLM router with model tiering.

Decides per-request which backend and model to use based on:
1. Token budget (context length)
2. Agent policy (local-only / cloud-only / claude / auto)
3. Backend availability (graceful degradation)
4. Howard special case: uses Ollama with fine-tuned model
5. Heavy agents (Vision, Steve) → Claude API via Anthropic
6. Deep-think agents → second LM Studio model slot (DDR5, async-only)
7. Complexity-based escalation → auto agents with heavy/complex prompts
   routed to deep slot (controlled by JARVIS_AUTO_DEEP env flag)

Tier layout (LM Studio multi-model):
  Slot 1 (VRAM, fast):  DEFAULT_LOCAL_MODEL  — interactive agents, voice
  Slot 2 (DDR5, deep):  DEFAULT_DEEP_MODEL   — frigga, hephaestus, hercules
                                                + auto agents w/ heavy prompts
  Ollama (VRAM/RAM):    HOWARD_OLLAMA_MODEL  — Howard fine-tuned

Set JARVIS_DEEP_MODEL env var to override the deep-slot model name.
Set JARVIS_AUTO_DEEP=0 to disable complexity-based escalation.
"""

import logging
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..env_config import env_flag
from . import model_config
from .base import LLMBackend, OllamaBackend
from .router import LLMRouter
from .tokenizer import estimate_tokens

logger = logging.getLogger("jarvis.llm.hybrid")

# Token thresholds
LOCAL_MAX_TOKENS = 8_000
FLASH_MAX_TOKENS = 128_000

# H7.5 — Complexity-based escalation thresholds and keywords.
# Prompts exceeding HEAVY_TOKEN_THRESHOLD tokens OR containing any keyword
# from HEAVY_KEYWORDS are considered "heavy" and routed to the deep local slot
# for auto-policy agents (when JARVIS_AUTO_DEEP is enabled).
HEAVY_TOKEN_THRESHOLD = 2_000

# Bilingual RO/EN keyword set — matched case-insensitively as substrings.
HEAVY_KEYWORDS: frozenset[str] = frozenset(
    {
        # Romanian
        "analiz",  # analiză / analizare / analizez
        "raionament",  # raționament (diacritic-free variant)
        "raționament",  # raționament (with diacritic)
        "strategi",  # strategie / strategică / strategic
        "corelare",  # corelare
        "planific",  # planificare / planific
        "sintez",  # sinteză / sintetizare
        "demonstr",  # demonstrare / demonstrez
        "deduc",  # deducție / deduc
        # English
        "analys",  # analysis / analyse / analyzes
        "analyz",  # analyze / analyzed
        "rationament",  # alias without diacritic
        "reasoning",
        "strategy",
        "strateg",  # strategic / strategize
        "correlat",  # correlate / correlation
        "planning",
        "synthes",  # synthesis / synthesize
        "demonstrat",  # demonstrate / demonstration
        "deduct",  # deduction / deduct
    }
)

# Feature flag: set JARVIS_AUTO_DEEP=0 or JARVIS_AUTO_DEEP=false to disable.
# Default is ON (complexity-based escalation active). Import-time constant on
# purpose — tests pin behavior via monkeypatch.setattr on this name.
AUTO_DEEP_ENABLED: bool = env_flag("JARVIS_AUTO_DEEP", True)

# Agent policy constants
POLICY_LOCAL = "local"
POLICY_CLOUD = "cloud"
POLICY_CLAUDE = "claude"
POLICY_AUTO = "auto"

# Which agents are local-only / cloud-only / claude
LOCAL_ONLY_AGENTS = {"frigga", "ultron", "howard"}
CLOUD_ONLY_AGENTS = {"athena"}
CLAUDE_AGENTS = {"vision", "steve"}

# Agents routed to the deep-think model slot (LM Studio slot 2, DDR5).
# These accept high latency in exchange for deeper reasoning.
DEEP_THINK_AGENTS = {"frigga", "hephaestus", "hercules"}


def is_heavy_request(prompt: str, *, token_threshold: int = HEAVY_TOKEN_THRESHOLD) -> bool:
    """Return True if a prompt is considered heavy/complex.

    A prompt is heavy when:
    - Its estimated token count exceeds *token_threshold* (default HEAVY_TOKEN_THRESHOLD), OR
    - It contains at least one keyword from HEAVY_KEYWORDS (case-insensitive substring match).

    This drives complexity-based escalation in select_backend() for POLICY_AUTO agents.
    Note: get_model() is NOT escalated because it has no prompt argument.
    """
    if estimate_tokens(prompt) > token_threshold:
        return True
    lower = prompt.lower()
    return any(kw in lower for kw in HEAVY_KEYWORDS)


# Agents that should use Ollama instead of LM Studio
OLLAMA_PREFERRED_AGENTS = {"howard"}

# Public constants kept here for existing callers/tests; values live in model_config.
DEFAULT_LOCAL_MODEL = model_config.DEFAULT_LOCAL_MODEL
DEFAULT_CLAUDE_MODEL = model_config.DEFAULT_CLAUDE_MODEL
DEFAULT_GEMINI_FLASH_MODEL = model_config.DEFAULT_GEMINI_FLASH_MODEL
DEFAULT_GEMINI_PRO_MODEL = model_config.DEFAULT_GEMINI_PRO_MODEL
DEFAULT_DEEP_MODEL = model_config.DEFAULT_DEEP_MODEL
HOWARD_OLLAMA_MODEL = model_config.HOWARD_OLLAMA_MODEL
HOWARD_FALLBACK_MODEL = model_config.HOWARD_FALLBACK_MODEL


@lru_cache(maxsize=1)
def _registry_policies() -> dict:
    """Per-agent llm_policy from the canonical registry (agents/_system/agents.yaml).

    Cached for the process lifetime; any failure returns {} so routing degrades to
    the in-code policy sets rather than breaking. LOCAL_ONLY_AGENTS is enforced
    *before* this is consulted, so the registry can never pull a strict-local
    agent to the cloud.
    """
    try:
        import yaml as _yaml

        path = Path(__file__).resolve().parents[2] / "_system" / "agents.yaml"
        data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {
            aid: str((cfg or {}).get("llm_policy", "")).strip().lower()
            for aid, cfg in (data.get("agents") or {}).items()
        }
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _registry_approved_models() -> dict:
    """Per-agent ``approved_models`` allowlist from the canonical registry (H23.2).

    Mirrors ``_registry_policies``: cached for the process; any failure returns {} so
    routing degrades to *unrestricted* (the pre-H23.2 behavior) rather than breaking.
    An agent absent here (or with an empty list) is unrestricted.
    """
    try:
        import yaml as _yaml

        path = Path(__file__).resolve().parents[2] / "_system" / "agents.yaml"
        data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out = {}
        for aid, cfg in (data.get("agents") or {}).items():
            models = (cfg or {}).get("approved_models") or []
            if isinstance(models, list) and models:
                out[aid] = [str(m).strip() for m in models if str(m).strip()]
        return out
    except Exception:
        return {}


class ModelNotApprovedError(PermissionError):
    """An agent was routed to a model outside its ``approved_models`` allowlist (H23.2)."""


class LocalBackendUnavailableError(RuntimeError):
    """A strict-local agent could not select an available local backend."""


class HybridRouter(LLMRouter):
    def __init__(self, gemini_api_key: str = "", anthropic_api_key: str = ""):
        super().__init__()
        self.gemini_api_key = gemini_api_key
        self.anthropic_api_key = anthropic_api_key
        self._gemini_backend: Optional[LLMBackend] = None
        self._claude_backend: Optional[LLMBackend] = None
        self._gemini_pool = None  # H12.20 — built in detect()
        self._anthropic_pool = None
        self._local_available = False
        self._cloud_available = False
        self._claude_available = False
        self._daily_cost_cap = 0.0        # /admin → llm.daily_cost_cap_usd (0 = none)
        self._ollama_backend: Optional[OllamaBackend] = None
        self._ollama_available = False
        self._local_model = DEFAULT_LOCAL_MODEL
        # Resolved in detect(): Claude model from /admin config (settings_db);
        # local model prefers the real model loaded in the live backend.
        self._claude_model = DEFAULT_CLAUDE_MODEL
        self._deep_model = model_config.deep_model_name()
        # /admin → llm.cloud_fallback: never | on-demand | always. Governs the
        # FALLBACK/escalation cloud hops for auto-policy agents (explicit cloud
        # policies like athena are policy, not fallback). Re-synced live by the
        # orchestrator's settings watcher via set_cloud_fallback_mode().
        self._cloud_fallback_mode = "on-demand"

        # Routing size thresholds (prompt INPUT tokens), live-tunable from /admin
        # via set_local_max / set_flash_max (settings watcher). Default to the
        # module constants; 0 / non-positive means "no limit" (sys.maxsize) — e.g.
        # a local-only user can let every prompt stay on the local model.
        self._local_max = LOCAL_MAX_TOKENS
        self._flash_max = FLASH_MAX_TOKENS

        # /admin → llm.gemini_model: the Gemini model used for cloud (flash-tier)
        # routes; oversized prompts still escalate to gemini-2.5-pro. Resolved in
        # detect() from settings_db.
        self._gemini_model = DEFAULT_GEMINI_FLASH_MODEL

        # H22.5 — LRU residency manager for the local fast↔deep model swap.
        # Default-off via JARVIS_MODEL_MANAGER; the orchestrator injects the real
        # LMStudioController-backed manager via attach_model_manager(). Kept off
        # the routing *decision* path — it's a best-effort residency side effect
        # the caller invokes right before a local generate.
        self._model_manager = None

    def attach_model_manager(self, manager) -> None:
        """Wire in the H22.5 ModelManager (called by the orchestrator at boot).

        The manager owns its own kill-switch; when off, ensure_resident() is a
        no-op, so attaching it unconditionally is safe."""
        self._model_manager = manager

    @property
    def model_manager(self):
        """The attached H22.5 ModelManager, or None if not wired."""
        return self._model_manager

    async def ensure_resident(self, model: str, route: str) -> None:
        """Best-effort: make `model` resident before a local generate (H22.5).

        Only acts for *local* routes (the fast/deep LM Studio slots); cloud /
        Claude routes have nothing to swap. No-op when no manager is attached or
        its kill-switch is off. Never raises — the manager swallows its own
        errors so routing degrades to the backend's JIT load."""
        mgr = self._model_manager
        if mgr is None or not model or not route:
            return
        if not route.startswith("local"):
            return
        await mgr.ensure_resident(model)

    @staticmethod
    def _admin_setting(key: str, default):
        """Read an `llm` setting from /admin config (settings_db), safely."""
        try:
            from ..settings_db import get_value

            val = get_value("llm", key, default)
            return val if val else default
        except Exception:
            return default

    def _deep_model_available(self) -> bool:
        """Evidence that the deep slot is real (O26-P0.5 / finding F5).

        Before this gate, ANY prompt containing a heavy keyword ("analyze",
        "strategy", ...) rerouted an auto agent to the hardcoded deep model —
        which a default one-model install doesn't have loaded, turning common
        words into invisible latency/failures. Escalate only on evidence:
        (1) the owner explicitly pinned a deep model via JARVIS_DEEP_MODEL
        (deliberate intent — honored even if the listing hasn't refreshed), or
        (2) the live backend's served-model listing contains the deep model.
        """
        if model_config.deep_model_override_configured():
            return True
        served = getattr(self, "_served_models", None) or set()
        deep = self._configured_deep_model().lower()
        return any(deep in m.lower() or m.lower() in deep for m in served)

    def _configured_deep_model(self) -> str:
        """Deep-slot model for this router, compatible with __new__ test fixtures."""
        return (
            getattr(self, "_deep_model", None)
            or model_config.deep_model_name()
            or DEFAULT_DEEP_MODEL
        )

    async def detect(self):
        # Re-detection (admin "reconnect") rebuilds the cloud/Ollama backends;
        # close the prior instances first so their pooled httpx.AsyncClient
        # sockets are not leaked until process exit (mirrors aclose()).
        for _attr in ("_gemini_backend", "_claude_backend", "_ollama_backend"):
            _prev = getattr(self, _attr, None)
            if _prev is not None:
                await self._close_backend(_prev)
                setattr(self, _attr, None)
        # Resolve the connectivity knobs (/admin) before probing so the base
        # detect() honors them: backend pin + URLs.  Explicit process-level URL
        # overrides take precedence so operators and hermetic test runners can
        # isolate local backends without mutating the persisted admin database.
        self.backend_type = self._admin_setting("backend_type", "auto")
        self.lm_studio_url = os.getenv("JARVIS_LM_STUDIO_URL") or self._admin_setting(
            "lm_studio_url", "http://localhost:1234"
        )
        self.ollama_url = os.getenv("JARVIS_OLLAMA_URL") or self._admin_setting(
            "ollama_url", "http://localhost:11434"
        )
        self._deep_model = model_config.deep_model_name()
        self._gemini_model = self._admin_setting("gemini_model", DEFAULT_GEMINI_FLASH_MODEL)
        await super().detect()
        self._local_available = self._backend is not None
        # Use the real model loaded in the live backend; fall back to the /admin
        # default, then the hard-coded default. ("live with the real LLM loaded".)
        self._local_model = self._detected_model or self._admin_setting(
            "default_model", DEFAULT_LOCAL_MODEL
        )
        # H12.20 — build auth-profile pools (multi-key + failover). A *_API_KEYS
        # env var (comma/space separated) supplies extra accounts; falls back to
        # the single *_API_KEY, so single-key deployments are unchanged.
        from .auth_rotation import AuthProfilePool

        self._gemini_pool = AuthProfilePool.from_env("GEMINI_API_KEY", "GEMINI_API_KEYS", "gemini")
        self._anthropic_pool = AuthProfilePool.from_env(
            "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS", "anthropic"
        )

        self._cloud_available = bool(self.gemini_api_key) or self._gemini_pool.size > 0
        if self._cloud_available:
            from .gemini import GeminiBackend

            self._gemini_backend = GeminiBackend(
                api_key=self.gemini_api_key, model=self._gemini_model, auth_pool=self._gemini_pool
            )

        # Claude model is admin-configurable (/admin → llm.claude_model).
        self._claude_model = self._admin_setting("claude_model", DEFAULT_CLAUDE_MODEL)
        self.set_cloud_fallback_mode(self._admin_setting("cloud_fallback", "on-demand"))
        self._claude_available = bool(self.anthropic_api_key) or self._anthropic_pool.size > 0
        if self._claude_available:
            from .anthropic import ClaudeBackend

            self._claude_backend = ClaudeBackend(
                api_key=self.anthropic_api_key,
                model=self._claude_model,
                auth_pool=self._anthropic_pool,
            )
            logger.info(
                f"Claude API available ({self._claude_model}; {self._anthropic_pool.size} auth profile(s))"
            )
        else:
            logger.warning(
                "ANTHROPIC_API_KEY not set — Claude tiering disabled, heavy agents will fall back"
            )

        self._ollama_backend = OllamaBackend(base_url=self.ollama_url)
        self._ollama_available = await self._check(f"{self.ollama_url}/api/tags")
        if self._ollama_available:
            logger.info(f"Ollama available for Howard ({HOWARD_OLLAMA_MODEL})")
        else:
            logger.warning("Ollama not available — Howard will fall back to default backend")

    def get_agent_policy(self, agent_id: str) -> str:
        # Security floor first: code-enforced, the registry cannot override it.
        if agent_id in LOCAL_ONLY_AGENTS:
            return POLICY_LOCAL
        # agents.yaml is the canonical registry (ARCHITECTURE §3) — honor its
        # llm_policy before the in-code sets, which act as fallback defaults.
        registry = _registry_policies().get(agent_id, "")
        if registry in (POLICY_LOCAL, POLICY_CLAUDE, POLICY_CLOUD, POLICY_AUTO):
            return registry
        if agent_id in CLAUDE_AGENTS:
            return POLICY_CLAUDE
        if agent_id in CLOUD_ONLY_AGENTS:
            return POLICY_CLOUD
        return POLICY_AUTO

    # ── H23.2 model pinning / reproducibility ─────────────────────────────────
    def approved_models(self, agent_id: str) -> list[str]:
        """The agent's approved-model allowlist (empty = unrestricted)."""
        return list(_registry_approved_models().get(agent_id, []))

    def is_model_approved(self, agent_id: str, model: str) -> bool:
        """True if *model* is allowed for *agent_id* (an empty allowlist allows all)."""
        allowed = self.approved_models(agent_id)
        return (not allowed) or (model in allowed)

    @staticmethod
    def _models_strict() -> bool:
        # Strict by default (mirrors JARVIS_STRICT_EGRESS); opt out only explicitly.
        return env_flag("JARVIS_STRICT_MODELS", True)

    def _enforce_approved_models(self, agent_id: str, model: str, route: str) -> None:
        """Block (or, opted-out, warn) when routing picks a model off the agent's allowlist."""
        if self.is_model_approved(agent_id, model):
            return
        msg = (
            f"agent '{agent_id}' routed to unapproved model '{model}' "
            f"(route={route}, approved={self.approved_models(agent_id)})"
        )
        if self._models_strict():
            logger.error("model pin violation (blocked): %s", msg)
            raise ModelNotApprovedError(msg)
        logger.warning("model pin violation (JARVIS_STRICT_MODELS=0, allowing): %s", msg)

    def select_backend(self, agent_id: str, prompt: str) -> tuple[LLMBackend, str, str]:
        """Select backend + model + route, then enforce the agent's approved-model
        allowlist (H23.2). Returns: (backend, model_name, route_name)."""
        backend, model, route = self._select_backend_inner(agent_id, prompt)
        self._enforce_approved_models(agent_id, model, route)
        return backend, model, route

    def _select_backend_inner(self, agent_id: str, prompt: str) -> tuple[LLMBackend, str, str]:
        """Core multi-factor routing; wrapped by select_backend for pin enforcement.

        Returns: (backend, model_name, route_name)
        """
        # Howard special case: use Ollama with fine-tuned model
        if agent_id == "howard":
            backend, route = self._select_howard_backend()
            model = HOWARD_OLLAMA_MODEL if self._ollama_available else self._local_model
            return backend, model, route

        # Deep-think agents: same LM Studio backend, different model slot (DDR5).
        # Only when local is available AND the deep model is actually there
        # (O26-P0.5/F5); falls through to normal routing otherwise.
        if agent_id in DEEP_THINK_AGENTS and self._local_available and self._deep_model_available():
            return self._backend, self._configured_deep_model(), "local-deep"

        policy = self.get_agent_policy(agent_id)
        token_count = estimate_tokens(prompt)

        if policy == POLICY_LOCAL:
            if self._local_available:
                return self._backend, self._local_model, "local"
            # NON-NEGOTIABLE (MOONSHOT §5.1 / AGENTS.md): strict-local agents
            # never leave the machine — no cloud fallback, fail closed instead.
            raise LocalBackendUnavailableError(
                f"Local backend unavailable for {agent_id} (policy=local) — "
                "strict-local agents never fall back to cloud; start LM Studio/Ollama"
            )

        if policy == POLICY_CLAUDE:
            if self._claude_available:
                return self._claude_backend, self._claude_model, "claude"
            logger.warning(f"Claude unavailable for {agent_id}, falling back to cloud")
            if self._cloud_permitted() and self._cloud_fallback_mode != "never":
                return self._gemini_backend, self._gemini_model, "cloud-fallback"
            if self._local_available:
                logger.warning(f"No cloud backend for {agent_id}, falling back to local")
                return self._backend, self._local_model, "local-fallback"
            raise RuntimeError(f"No LLM backend available for {agent_id}")

        if policy == POLICY_CLOUD:
            if self._cloud_permitted():
                return self._gemini_backend, self._gemini_model, "cloud"
            logger.warning(
                f"Cloud backend unavailable for {agent_id} (policy=cloud), falling back to local"
            )
            if self._local_available:
                return self._backend, self._local_model, "local-fallback"
            raise RuntimeError(f"No LLM backend available for {agent_id}")

        # POLICY_AUTO: prefer Claude for heavy agents, local for light
        if agent_id in CLAUDE_AGENTS and self._claude_available:
            # A CLAUDE_AGENTS agent always routes to Claude — the token count
            # does not change the backend, model, or route name.
            return self._claude_backend, self._claude_model, "claude"

        # Default: local first, cloud if context too big — governed by the
        # /admin llm.cloud_fallback knob (never | on-demand | always):
        #   never     → auto-policy agents NEVER spill to cloud (local or fail)
        #   on-demand → spill only when the context outgrows the local window
        #   always    → prefer cloud for auto agents whenever it's available
        if self._cloud_fallback_mode == "always" and self._cloud_permitted():
            return self._gemini_backend, self._gemini_model, "cloud-flash"
        # H7.5 — Complexity escalation: heavy prompts for auto-policy agents
        # are routed to the deep local slot (DDR5) when AUTO_DEEP_ENABLED.
        # This only applies here (token_count <= local threshold path) because
        # oversized prompts already spill to cloud via the branches below.
        if token_count <= self._local_max and self._local_available:
            if AUTO_DEEP_ENABLED and self._deep_model_available() and is_heavy_request(prompt):
                logger.debug(
                    "Complexity escalation: routing %s to deep slot (local-deep)", agent_id
                )
                return self._backend, self._configured_deep_model(), "local-deep"
            return self._backend, self._local_model, "local"
        if self._cloud_fallback_mode != "never":
            if token_count <= self._flash_max and self._cloud_permitted():
                return self._gemini_backend, self._gemini_model, "cloud-flash"
            if self._cloud_permitted():
                return self._gemini_backend, DEFAULT_GEMINI_PRO_MODEL, "cloud-pro"

        if self._local_available:
            logger.warning("Cloud unavailable, falling back to local (context may be truncated)")
            return self._backend, self._local_model, "local-fallback"

        raise RuntimeError("No LLM backend available")

    def _select_howard_backend(self) -> tuple[LLMBackend, str]:
        """Select backend for Howard: prefer Ollama with fine-tuned model,
        fall back to main LM Studio backend."""
        if self._ollama_available:
            return self._ollama_backend, "ollama-howard"
        if self._local_available:
            logger.warning("Ollama unavailable for Howard, falling back to LM Studio")
            return self._backend, "local-fallback"
        # NON-NEGOTIABLE (MOONSHOT §5.1): Howard is LOCAL_ONLY — the digital twin's
        # archive never leaves the machine. No cloud fallback; fail closed.
        raise LocalBackendUnavailableError(
            "No local backend available for howard (strict-local) — "
            "start Ollama or LM Studio; cloud fallback is forbidden"
        )

    def set_cloud_fallback_mode(self, mode) -> None:
        """Live update from /admin → llm.cloud_fallback (settings watcher, ≤30s)."""
        mode = str(mode or "on-demand").strip().lower()
        if mode not in ("never", "on-demand", "always"):
            mode = "on-demand"
        if mode != self._cloud_fallback_mode:
            logger.info("Cloud fallback mode → %s", mode)
        self._cloud_fallback_mode = mode

    @staticmethod
    def _resolve_threshold(value, default: int) -> int:
        """Coerce an /admin threshold to an int. Non-positive / blank / bad → no
        limit (sys.maxsize), so '0' in /admin means 'route everything here'."""
        try:
            n = int(value)
        except (TypeError, ValueError):
            return default
        return n if n > 0 else sys.maxsize

    def set_daily_cost_cap(self, value) -> None:
        """Live update from /admin → llm.daily_cost_cap_usd. 0 / unset = no cap."""
        try:
            cap = float(value or 0)
        except (TypeError, ValueError):
            cap = 0.0
        cap = max(0.0, cap)
        if cap != self._daily_cost_cap:
            logger.info("Daily cloud spend cap → %s",
                        f"${cap:.2f}" if cap else "none")
        self._daily_cost_cap = cap

    def _cloud_permitted(self) -> bool:
        """Is a cloud route allowed right now — available AND within the daily cap?

        ADV-078: an unattended night-shift loop on a cloud key had no ceiling anywhere and
        produced no signal, so the first sign of a problem was the provider's invoice.
        The cap is checked HERE, before a cloud backend is selected, rather than after the
        call — the point is not to bill and then complain.

        Default is 0 (no cap), so behaviour is unchanged until the owner sets one. Over
        the cap, routing degrades to local rather than failing: a capped box should get
        slower and more private, not stop answering.
        """
        if not self._cloud_available:
            return False
        if not self._daily_cost_cap:
            return True
        try:
            from agents.core import cost_tracker
            spent = cost_tracker.spend_today_usd()
        except Exception:
            # A meter we cannot read must not silently disable the cap OR the cloud;
            # allowing through is the pre-cap behaviour and the honest default here.
            logger.debug("daily cost cap: spend unreadable", exc_info=True)
            return True
        if spent >= self._daily_cost_cap:
            logger.warning(
                "Daily cloud spend cap reached ($%.2f of $%.2f) — routing local",
                spent, self._daily_cost_cap,
            )
            return False
        return True

    def set_local_max(self, value) -> None:
        """Live update from /admin → llm.hybrid_local_max. Prompts up to this many
        input tokens route to the local model (0 = unlimited)."""
        resolved = self._resolve_threshold(value, LOCAL_MAX_TOKENS)
        if resolved != self._local_max:
            shown = "unlimited" if resolved == sys.maxsize else resolved
            logger.info("Local routing threshold → %s tokens", shown)
        self._local_max = resolved

    def set_flash_max(self, value) -> None:
        """Live update from /admin → llm.hybrid_flash_max. Prompts up to this many
        input tokens route to cloud Flash (above → Pro); 0 = unlimited."""
        resolved = self._resolve_threshold(value, FLASH_MAX_TOKENS)
        if resolved != self._flash_max:
            shown = "unlimited" if resolved == sys.maxsize else resolved
            logger.info("Flash routing threshold → %s tokens", shown)
        self._flash_max = resolved

    def set_active_model(self, model: str) -> None:
        """Switch the active local model used for `local` routing tiers.

        Updates both the auto-detected name (base class) and `_local_model`,
        which drives select_backend()/get_model() for POLICY_AUTO/local agents."""
        super().set_active_model(model)
        self._local_model = model

    def get_howard_model(self) -> str:
        return HOWARD_OLLAMA_MODEL if self._ollama_available else HOWARD_FALLBACK_MODEL

    def get_model(self, agent_id: str) -> str:
        """Return the appropriate model name for this agent."""
        if agent_id == "howard":
            return HOWARD_OLLAMA_MODEL if self._ollama_available else self._local_model
        if agent_id in CLAUDE_AGENTS and self._claude_available:
            return self._claude_model
        if agent_id in DEEP_THINK_AGENTS and self._local_available:
            return self._configured_deep_model()
        return self._local_model

    @property
    def backend(self) -> LLMBackend:
        if not self._local_available and not self._cloud_available:
            raise RuntimeError(
                "No LLM backend available. Start LM Studio/Ollama or configure GEMINI_API_KEY."
            )
        return self._claude_backend or self._backend or self._gemini_backend

    @property
    def name(self) -> str:
        parts = []
        if self._local_available:
            parts.append(self._backend_name)
        if self._ollama_available:
            parts.append("ollama-howard")
        if self._claude_available:
            parts.append("claude")
        if self._cloud_available:
            parts.append("gemini")
        return "+".join(parts) if parts else "none"

    def get_route_name(self, agent_id: str, prompt: str) -> str:
        _, _, route = self.select_backend(agent_id, prompt)
        return route

    def provider_catalog(self) -> list[dict]:
        """Return declared provider profiles without probing network backends."""
        from .providers import provider_catalog

        return provider_catalog()

    async def aclose(self) -> None:
        """Close every backend's HTTP client pool (BUG-7).

        The base class only closes the local LM Studio / Ollama backend; the
        hybrid router also owns Gemini, Claude and the Howard/Ollama backends,
        each holding a pooled httpx.AsyncClient. Best-effort: `_close_backend`
        swallows per-backend errors so shutdown never raises.
        """
        await super().aclose()
        for attr in ("_gemini_backend", "_claude_backend", "_ollama_backend"):
            backend = getattr(self, attr, None)
            if backend is not None:
                await self._close_backend(backend)
                setattr(self, attr, None)
