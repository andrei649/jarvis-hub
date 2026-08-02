"""
guardrails.py — Security-aware LLM call wrapper with scan/redact/block.
"""

import dataclasses
from dataclasses import dataclass
import hashlib
import inspect
import json
import logging
import threading
from typing import Any, Callable, Sequence

from ..llm.base import LLMBackend
from ..llm.tool_protocol import ToolCall, ToolSpec, ToolTurn
from .scanner import BaseScanner, PIIScanner, SCANNER_RULESET_VERSION, SecretScanner
from .types import RedactionMode, ScanResult

logger = logging.getLogger("jarvis.security")


class SecurityBlockError(Exception):
    pass


class GuardrailBindingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GuardedCacheMaterial:
    system_instruction: str
    history: tuple[str, ...]
    policy_fingerprint: str


def bind_guardrails(
    policy: "GuardrailsEngine | None",
    backend: LLMBackend,
) -> "GuardrailsEngine | LLMBackend":
    return policy.bind(backend) if policy is not None else backend


class GuardrailsEngine:
    def __init__(
        self,
        backend: LLMBackend | None = None,
        mode: RedactionMode = RedactionMode.WARN,
        scan_input: bool = True,
        scan_output: bool = True,
        scanners: Sequence[BaseScanner] | None = None,
        counters: dict | None = None,
    ) -> None:
        self._backend = backend
        self._scanners = tuple(scanners) if scanners is not None else (
            SecretScanner(),
            PIIScanner(),
        )
        self._mode = mode
        self._scan_input = scan_input
        self._scan_output = scan_output
        # Real activity counters. /security/status used to publish literal zeros
        # for redact_count / block_count / findings, which the Console renders as
        # measured security activity — so a hub that had redacted forty PII spans
        # and blocked six outbound requests still reported a clean, untriggered
        # system. Nothing was counting; these are the counters.
        #
        # SHARED with every engine produced by bind(): the HUD wants the process
        # total, and bind() makes a fresh instance per backend, so per-instance
        # counters would each report a fraction.
        self._counters = counters if counters is not None else {
            "scanned": 0, "findings": 0, "warned": 0, "redacted": 0, "blocked": 0,
        }
        self._counters_lock = threading.Lock()

    def bind(self, backend: LLMBackend) -> "GuardrailsEngine":
        return GuardrailsEngine(
            backend=backend,
            mode=self._mode,
            scan_input=self._scan_input,
            scan_output=self._scan_output,
            scanners=self._scanners,
            counters=self._counters,   # share, don't fork
        )

    def _bump(self, key: str, n: int = 1) -> None:
        with self._counters_lock:
            self._counters[key] = self._counters.get(key, 0) + n

    def apply_settings(self, mode=None, scan_input=None, scan_output=None) -> "GuardrailsEngine":
        """Live-resync seam for the settings watcher (SEC-065).

        The mode was frozen at load_agents() time — flipping
        ``security.guardrails_mode`` changed the posture screen but not the
        running engine. ``mode`` accepts a RedactionMode or its NAME (the
        settings row stores uppercase names); an unknown value keeps the
        CURRENT mode, never a silent reset. bind() copies the mode per
        request, so a change takes effect on the next turn.
        """
        if isinstance(mode, RedactionMode):
            self._mode = mode
        elif isinstance(mode, str):
            candidate = RedactionMode.__members__.get(mode.strip().upper())
            if candidate is not None:
                self._mode = candidate
        if scan_input is not None:
            self._scan_input = bool(scan_input)
        if scan_output is not None:
            self._scan_output = bool(scan_output)
        return self

    def stats(self) -> dict:
        """Live guardrail activity + the real scanner rulesets, for /security/status."""
        with self._counters_lock:
            counters = dict(self._counters)
        return {
            "mode": self._mode.value if hasattr(self._mode, "value") else str(self._mode),
            "scan_input": self._scan_input,
            "scan_output": self._scan_output,
            "counters": counters,
            # Pattern counts come from the compiled ruleset, not a hand-written
            # number — the route claimed 10 secret and 6 PII patterns, and both
            # were wrong.
            "scanners": {
                s.scanner_id: {"patterns": len(getattr(s, "_compiled", ()) or ())}
                for s in self._scanners
            },
        }

    def _bound_backend(self) -> LLMBackend:
        if self._backend is None:
            raise GuardrailBindingError("guardrails policy is not bound to a backend")
        return self._backend

    @property
    def supports_tools(self) -> bool:
        return self._bound_backend().supports_tools

    def _scan_text(self, text: str) -> ScanResult:
        merged = ScanResult()
        for scanner in self._scanners:
            result = scanner.scan(text)
            merged.findings.extend(result.findings)
        self._bump("scanned")
        if merged.findings:
            self._bump("findings", len(merged.findings))
        return merged

    def _redact_text(self, text: str) -> str:
        result = text
        for scanner in self._scanners:
            result = scanner.redact(result)
        return result

    def _guard_input(self, text: str) -> str:
        result = self._scan_text(text)
        if result.clean:
            return text
        return self._handle_findings(text, result, "input")

    def _guard_output(self, text: str) -> str:
        result = self._scan_text(text)
        if result.clean:
            return text
        return self._handle_findings(text, result, "output")

    def _handle_findings(self, text: str, result: ScanResult, direction: str) -> str:
        finding_info = [
            {"pattern": f.pattern_name, "threat": f.threat_level.value}
            for f in result.findings
        ]

        if self._mode == RedactionMode.WARN:
            self._bump("warned")
            if result.critical_count > 0:
                logger.warning(f"Security WARN [{direction}]: {finding_info}")
            return text

        if self._mode == RedactionMode.REDACT:
            self._bump("redacted")
            if result.findings:
                logger.info(f"Security REDACT [{direction}]: {finding_info}")
            return self._redact_text(text)

        if self._mode == RedactionMode.BLOCK:
            self._bump("blocked")
            logger.warning(f"Security BLOCK [{direction}]: {finding_info}")
            raise SecurityBlockError(
                f"Security scan blocked {direction}: {len(result.findings)} finding(s)"
            )

        return text

    def _guard_tool_value(self, value):
        if isinstance(value, str):
            return self._guard_output(value)
        if isinstance(value, list):
            return [self._guard_tool_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._guard_tool_value(item) for key, item in value.items()}
        return value

    def _guard_tool_call(self, call: ToolCall) -> ToolCall:
        if self._mode == RedactionMode.WARN:
            raw = json.dumps(call.arguments, sort_keys=True, separators=(",", ":"))
            result = self._scan_text(raw)
            if not result.clean:
                self._handle_findings(raw, result, "output")
            return call

        guarded = self._guard_tool_value(call.arguments)
        raw = json.dumps(guarded, sort_keys=True, separators=(",", ":"))
        result = self._scan_text(raw)
        if self._scan_output and not result.clean:
            raise SecurityBlockError(
                "guarded tool arguments still match a security rule"
            )
        return dataclasses.replace(call, arguments=guarded, raw_arguments=raw)

    def policy_fingerprint(self) -> str:
        material = {
            "mode": self._mode.value,
            "scan_input": self._scan_input,
            "scan_output": self._scan_output,
            "ruleset": SCANNER_RULESET_VERSION,
            "scanners": [scanner.fingerprint() for scanner in self._scanners],
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def prepare_cache_material(
        self,
        system_instruction: str,
        history: Sequence[str],
    ) -> GuardedCacheMaterial:
        guard = self._guard_output if self._scan_output else (lambda value: value)
        return GuardedCacheMaterial(
            system_instruction=guard(str(system_instruction)),
            history=tuple(guard(str(part)) for part in history),
            policy_fingerprint=self.policy_fingerprint(),
        )

    async def generate_tool_turn(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> ToolTurn:
        backend = self._bound_backend()
        guarded_messages = [dict(message) for message in messages]
        if self._scan_input:
            for message in guarded_messages:
                content = message.get("content")
                if isinstance(content, str):
                    message["content"] = self._guard_input(content)

        turn = await backend.generate_tool_turn(
            model=model,
            messages=guarded_messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        if not self._scan_output:
            return turn

        content = self._guard_output(turn.content) if turn.content else turn.content
        tool_calls = tuple(self._guard_tool_call(call) for call in turn.tool_calls)
        return dataclasses.replace(turn, content=content, tool_calls=tool_calls)

    async def generate(self, model: str, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> str:
        backend = self._bound_backend()
        if self._scan_input:
            prompt = self._guard_input(prompt)

        if self._scan_input and system:
            system = self._guard_input(system)

        response = await backend.generate(
            model=model, prompt=prompt, system=system,
            max_tokens=max_tokens, temperature=temperature,
        )

        if self._scan_output and response:
            response = self._guard_output(response)

        return response

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        backend = self._bound_backend()
        if self._scan_input:
            prompt = self._guard_input(prompt)

        if self._scan_input and system:
            system = self._guard_input(system)

        if self._scan_output and self._mode in {
            RedactionMode.REDACT,
            RedactionMode.BLOCK,
        }:
            response = await backend.generate_stream(
                model=model,
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                on_token=None,
            )
            safe = self._guard_output(response)
            if on_token is not None and safe:
                emitted = on_token(safe)
                if inspect.isawaitable(emitted):
                    await emitted
            return safe

        response = await backend.generate_stream(
            model=model, prompt=prompt, system=system,
            max_tokens=max_tokens, temperature=temperature,
            on_token=on_token,
        )

        if self._scan_output and response:
            response = self._guard_output(response)

        return response
