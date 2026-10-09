"""Server-owned classification and live Kernel authority for Hermes effects."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from agents.core.kernel import Action, Capability, Verdict, kernel_enabled
from agents.core.kernel.binding import make_action_kernel
from agents.core.kernel.capabilities import issue_operator_capability

KIND = "hermes.runtime"
CATALOG_FILE = Path(__file__).resolve().parents[3] / "runtime/hermes/gateway-catalog.json"
POLICY_FILE = CATALOG_FILE.with_name("rpc-policy.json")
READ_TOOLS = frozenset({"web_search", "web_extract", "read_file", "search_files", "list_directory", "session_search"})



class RuntimeDenied(RuntimeError):
    def __init__(self, reason: str, *, verdict: str = "deny", card=None, task_id=None):
        self.reason, self.verdict, self.card, self.task_id = reason, verdict, card, task_id
        super().__init__(reason)


def catalog() -> dict:
    value = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    if policy["source_sha"] != value["source_sha"] or set(policy["tiers"]) != {method["name"] for method in value["methods"]}:
        raise RuntimeDenied("Hermes catalog classification is incomplete")
    for method in value["methods"]:
        name = method["name"]
        method["risk_tier"] = policy["tiers"][name]
        if type(method["risk_tier"]) is not int or method["risk_tier"] not in {0, 1, 2, 3}:
            raise RuntimeDenied("Hermes catalog classification is invalid")
        method["availability"] = "approval_floor" if method["risk_tier"] == 3 else "kernel_required"
    return value


def classify(kind: str, target: str) -> int:
    if kind == "rpc":
        methods = {method["name"]: method for method in catalog()["methods"]}
        if target not in methods:
            raise RuntimeDenied("Hermes method is outside the pinned catalog")
        return methods[target]["risk_tier"]
    if kind == "tool" and isinstance(target, str) and 0 < len(target) < 256:
        # Unknown/plugin tools retain an approval floor. Built-ins receive no
        # implicit permission merely because their name resembles a read.
        return 0 if target in READ_TOOLS else 1 if target == "todo" else 3
    if kind == "control" and target == "start":
        return 2
    raise RuntimeDenied("Hermes operation is unclassified")


class HermesGate:
    def __init__(self, *, kernel=None, orchestrator=None):
        self._kernel, self._orchestrator = kernel, orchestrator

    def authorize(self, kind: str, target: str, args: dict, generation: str, *,
                  request_nonce: str | None = None, approved_task_id: int | None = None,
                  approval_check=None) -> dict:
        tier = classify(kind, target)
        if not kernel_enabled():
            raise RuntimeDenied("Hermes requires the Action Kernel")
        kernel, capability = self._kernel, Capability(name=KIND)
        if kernel is None:
            if not kernel_enabled() or self._orchestrator is None:
                raise RuntimeDenied("Hermes requires the Action Kernel")
            orch = self._orchestrator()
            kernel = make_action_kernel(orch)
            broker = getattr(orch, "capabilities", None)
            token = issue_operator_capability(broker, KIND)
            if not callable(kernel) or not token:
                raise RuntimeDenied("Hermes authority is unavailable")
            capability = Capability(token_id=token, name=KIND)
        payload = {"operation": kind, "target": target, "arguments": deepcopy(args),
                   "generation": generation, "owner": "hub-owner",
                   "session_id": args.get("session_id"), "risk_tier": tier}
        if request_nonce is not None:
            payload["request_nonce"] = request_nonce
            payload["submission_id"] = request_nonce
        if approved_task_id is not None:
            payload["approved_task_id"] = approved_task_id
        action = Action(
            kind=KIND, agent="hermes", title=f"Hermes {kind}: {target}",
            payload=payload,
            origin="generated",
        )
        try:
            if approved_task_id is None:
                decision = kernel(action, capability)
            else:
                check = getattr(kernel, "revalidate", None)
                if not callable(check) or not callable(approval_check):
                    raise RuntimeDenied("Hermes live revalidation is unavailable")
                decision = check(action, capability, approval_check=approval_check)
        except Exception as exc:
            raise RuntimeDenied("Hermes authority is unavailable") from exc
        if decision.verdict is not Verdict.GRANT or (approved_task_id is not None and decision.task_id != approved_task_id):
            raise RuntimeDenied(decision.reason or "Hermes operation refused",
                                verdict=decision.verdict.value, card=decision.card)
        return {"verdict": "grant", "tier": decision.tier}
