"""
guardrails.py — Security-aware LLM call wrapper with scan/redact/block.
"""

import logging
from typing import Callable, Optional

from .scanner import PIIScanner, SecretScanner
from .types import RedactionMode, ScanResult
from ..llm.base import LLMBackend

logger = logging.getLogger("jarvis.security")


class SecurityBlockError(Exception):
    pass


class GuardrailsEngine:
    def __init__(
        self,
        backend: LLMBackend,
        mode: RedactionMode = RedactionMode.WARN,
        scan_input: bool = True,
        scan_output: bool = True,
    ):
        self._backend = backend
        self._scanners = [SecretScanner(), PIIScanner()]
        self._mode = mode
        self._scan_input = scan_input
        self._scan_output = scan_output

    def _scan_text(self, text: str) -> ScanResult:
        merged = ScanResult()
        for scanner in self._scanners:
            result = scanner.scan(text)
            merged.findings.extend(result.findings)
        return merged

    def _redact_text(self, text: str) -> str:
        result = text
        for scanner in self._scanners:
            result = scanner.redact(result)
        return result

    def _handle_findings(self, text: str, result: ScanResult, direction: str) -> str:
        finding_info = [
            {"pattern": f.pattern_name, "threat": f.threat_level.value}
            for f in result.findings
        ]

        if self._mode == RedactionMode.WARN:
            if result.critical_count > 0:
                logger.warning(f"Security WARN [{direction}]: {finding_info}")
            return text

        if self._mode == RedactionMode.REDACT:
            if result.findings:
                logger.info(f"Security REDACT [{direction}]: {finding_info}")
            return self._redact_text(text)

        if self._mode == RedactionMode.BLOCK:
            logger.warning(f"Security BLOCK [{direction}]: {finding_info}")
            raise SecurityBlockError(
                f"Security scan blocked {direction}: {len(result.findings)} finding(s)"
            )

        return text

    async def generate(self, model: str, prompt: str, system: str = "") -> str:
        if self._scan_input:
            result = self._scan_text(prompt)
            if not result.clean:
                prompt = self._handle_findings(prompt, result, "input")

        if self._scan_input and system:
            result = self._scan_text(system)
            if not result.clean:
                system = self._handle_findings(system, result, "input")

        response = await self._backend.generate(model=model, prompt=prompt, system=system)

        if self._scan_output and response:
            result = self._scan_text(response)
            if not result.clean:
                response = self._handle_findings(response, result, "output")

        return response

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        if self._scan_input:
            result = self._scan_text(prompt)
            if not result.clean:
                prompt = self._handle_findings(prompt, result, "input")

        if self._scan_input and system:
            result = self._scan_text(system)
            if not result.clean:
                system = self._handle_findings(system, result, "input")

        response = await self._backend.generate_stream(
            model=model, prompt=prompt, system=system,
            max_tokens=max_tokens, temperature=temperature,
            on_token=on_token,
        )

        if self._scan_output and response:
            result = self._scan_text(response)
            if not result.clean:
                response = self._handle_findings(response, result, "output")

        return response
