"""
autonomy — Proactive Cortex (ORIZONT 6).

MVP "Continuous Jarvis": self-tasking queue (H6.1) + risk gate / autonomy dial
(H6.3) + decision inbox (H6.2). Ambient-agent model: trigger → queue → gating →
inbox → execute. NOT an open-ended auto-prompt loop (anti-AutoGPT).
"""

if __name__ == "agents.core.autonomy":
    from .digest import build_evening_retro, build_morning_brief
    from .error_logger import (
        persist_problem,
        sync_problems_to_backlog,
        sync_problems_to_diagnostics,
    )
    from .executor import TaskExecutor
    from .inbox import DECISION_ACTIONS, build_decision_card, parse_callback_data
    from .log_scanner import LogBugScanner, ScanResult
    from .missions import (
        BudgetExceeded,
        Mission,
        MissionError,
        MissionEvent,
        MissionStatus,
        MissionStore,
        StepStatus,
    )
    from .observer import (
        Finding,
        ProactiveObserver,
        Remediation,
        ResourceProbe,
        ServiceProbe,
        ServiceSpec,
        Severity,
        Signal,
        default_probes,
    )
    from .policy import AutonomyPolicy, Decision, Outcome, RiskTier
    from .preferences import PreferenceStore
    from .queue import Task, TaskQueue, TaskQueueError, TaskStatus
    from .reflection import DailyReflector
    from .remediation import ExecResult, RemediationRunner, ServiceCommand
    from .tech_scout import (
        DEFAULT_QUERIES as TECH_SCOUT_DEFAULT_QUERIES,
        TechScout,
        TechScoutStore,
    )
    from .watchers import CalendarProbe, EmailProbe, EventWatcher, FinanceProbe, HealthProbe
    from .worker import AutonomyWorker, InterruptBudget, is_night_window

    __all__ = [
        "AutonomyPolicy",
        "Decision",
        "RiskTier",
        "Outcome",
        "Task",
        "TaskQueue",
        "TaskStatus",
        "TaskQueueError",
        "AutonomyWorker",
        "InterruptBudget",
        "is_night_window",
        "build_decision_card",
        "parse_callback_data",
        "DECISION_ACTIONS",
        "TaskExecutor",
        "MissionStore",
        "Mission",
        "MissionEvent",
        "MissionStatus",
        "StepStatus",
        "MissionError",
        "BudgetExceeded",
        "build_morning_brief",
        "build_evening_retro",
        "PreferenceStore",
        "RemediationRunner",
        "ServiceCommand",
        "ExecResult",
        "DailyReflector",
        "EventWatcher",
        "EmailProbe",
        "CalendarProbe",
        "FinanceProbe",
        "HealthProbe",
        "persist_problem",
        "sync_problems_to_diagnostics",
        "sync_problems_to_backlog",
        "LogBugScanner",
        "ScanResult",
        "ProactiveObserver",
        "Signal",
        "Severity",
        "Remediation",
        "Finding",
        "ResourceProbe",
        "ServiceProbe",
        "ServiceSpec",
        "default_probes",
        "TechScout",
        "TechScoutStore",
        "TECH_SCOUT_DEFAULT_QUERIES",
    ]
else:
    # Legacy ``core.autonomy.<non-authority>`` modules remain importable while
    # queue/worker/executor/evidence modules reject their own legacy identities.
    __all__ = []
