"""
autonomy — Proactive Cortex (ORIZONT 6).

MVP "Continuous Jarvis": self-tasking queue (H6.1) + risk gate / autonomy dial
(H6.3) + decision inbox (H6.2). Ambient-agent model: trigger → queue → gating →
inbox → execute. NOT an open-ended auto-prompt loop (anti-AutoGPT).
"""

from .policy import AutonomyPolicy, Decision, RiskTier, Outcome
from .queue import Task, TaskQueue, TaskStatus, TaskQueueError
from .worker import AutonomyWorker, InterruptBudget, is_night_window
from .inbox import build_decision_card, parse_callback_data, DECISION_ACTIONS
from .executor import TaskExecutor
from .digest import build_morning_brief, build_evening_retro
from .preferences import PreferenceStore
from .remediation import RemediationRunner, ServiceCommand, ExecResult
from .watchers import EventWatcher, EmailProbe, CalendarProbe, FinanceProbe, HealthProbe
from .error_logger import persist_problem, sync_problems_to_backlog
from .observer import (
    ProactiveObserver, Signal, Severity, Remediation, Finding,
    ResourceProbe, ServiceProbe, ServiceSpec, default_probes,
)

__all__ = [
    "AutonomyPolicy", "Decision", "RiskTier", "Outcome",
    "Task", "TaskQueue", "TaskStatus", "TaskQueueError",
    "AutonomyWorker", "InterruptBudget", "is_night_window",
    "build_decision_card", "parse_callback_data", "DECISION_ACTIONS",
    "TaskExecutor",
    "build_morning_brief", "build_evening_retro",
    "PreferenceStore",
    "RemediationRunner", "ServiceCommand", "ExecResult",
    "EventWatcher", "EmailProbe", "CalendarProbe", "FinanceProbe", "HealthProbe",
    "persist_problem", "sync_problems_to_backlog",
    "ProactiveObserver", "Signal", "Severity", "Remediation", "Finding",
    "ResourceProbe", "ServiceProbe", "ServiceSpec", "default_probes",
]
