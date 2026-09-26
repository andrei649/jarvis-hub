"""
heartbeat.py — Heartbeat scheduler for agents that need periodic self-triggers.

Two sources feed one schedule, and this is their precedence:

1. The agent's ``HEARTBEAT.md`` — or its ``HEARTBEAT.local.md`` overlay, the user data
   home first, then the repo-local copy — read by ``load_all``: a YAML front-matter
   carrying the ``cadence`` (``cron:<5 fields>`` or ``interval:<seconds>``) and the
   ``checklist`` that ``Agent.run_heartbeat`` executes.
2. The ``heartbeat: "<interval>"`` field of ``agents/_system/agents.yaml``, read by
   ``load_from_config``: a cadence-only fallback for an active agent that ships no
   heartbeat file. It never replaces an entry ``load_all`` loaded — the file carries
   the checklist and a time-of-day cadence an interval cannot express, and before this
   rule every shipped heartbeat lost both at boot and ran as an empty interval job.

An entry the injection scan refused (``_blocked``) is scheduled from neither source:
the verdict on the file is not undone by the registry re-adding the same agent as an
interval job. The orchestrator calls ``load_all`` then ``load_from_config``; the
result is the same in either order.

Schedules agent routines using APScheduler with jitter and MIN_HEARTBEAT_INTERVAL
guardrails.
"""

import datetime
import hashlib
import logging
import random
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Optional

from .security.quarantine import detect_injection_normalized, strip_invisible

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    # APScheduler 3.x defines this under `.base`; importing it from the package
    # root fails there, which used to leave SchedulerNotRunningError = None and turn
    # `except SchedulerNotRunningError` into `except None` → TypeError (CodeQL #26).
    from apscheduler.schedulers.base import SchedulerNotRunningError
except ImportError:
    AsyncIOScheduler = None

    # Keep the name bound to a real exception type so the `except` clause in stop()
    # is always valid (never None) even when APScheduler isn't installed.
    class SchedulerNotRunningError(Exception):  # type: ignore[no-redef]
        pass

logger = logging.getLogger("jarvis.heartbeat")

MIN_HEARTBEAT_INTERVAL = 3600
JITTER_MIN = 15
JITTER_MAX = 30

# H506 (read side) — HEARTBEAT.md is the file in this repo that *literally* steers
# future runs: what `_parse_heartbeat` returns becomes a cron job and, through
# `Agent.run_heartbeat`, a checklist whose every item is keyword-routed to a skill and
# echoed verbatim into the run summary. The write side already treats the name as an
# always-ask class (file_tools.py); this is the same class on the way in, with the
# block-and-mark semantics `agent.py::_scan_soul_body` uses for SOUL.md.
#
# What is scanned, precisely. ONLY the YAML front-matter is loaded — the prose body
# after the second `---` is discarded by `_parse_heartbeat` and reaches no model, log
# or scheduler, so it is outside this scan by construction (a loader that starts
# reading it must route it through `scan_heartbeat_config`; the tripwire is
# tests/test_instruction_files_read_side_scan.py). Within the front-matter every
# string is scanned — keys and values, nested to `_SCAN_MAX_DEPTH` — because the whole
# mapping is handed to the agent and no field is reserved for prose. The walker fails
# CLOSED: a container at the bound, a `!!binary` value or a type `yaml.safe_load` never
# produces is a flag that refuses the entry, not a leaf the walker had nothing to say
# about. (The first cut returned silently at the bound and skipped `set` and `bytes`,
# and "nothing found" read as clean — the review loaded, scheduled and echoed a payload
# through each.) One hit refuses the whole entry: a heartbeat is one scheduled job with
# no "rest of the persona" to preserve, so unlike the per-line SOUL quarantine the
# fail-closed answer is simply not to schedule it — and `load_from_config`, which runs
# right after `load_all` at startup, does not schedule the agents.yaml interval for a
# refused agent either. The reason is logged with the file's digest, never the payload,
# and `get_status()["blocked"]` carries the verdict to the HUD and the runtime run-log,
# naming the file relative to its root (the route is public; the log keeps the path).
#
# Each string is scanned as the union of itself and its normalised copies
# (`detect_injection_normalized`): the patterns are literal, so an invisible character
# inside a phrase, a blank character in place of a space, a respacing between words or
# a fullwidth spelling defeats a raw scan, and a scan of a stripped copy alone destroys
# the `you are now\b` match when the invisible character was what supplied the
# boundary. A TAG-plane payload (U+E0000–U+E007F, rendered as nothing) is decoded and
# scanned too, so it is named rather than merely deleted — with one shape excused from
# the bare-invisible-run flag: a subdivision flag emoji (🏴, a few TAG letters, CANCEL
# TAG — England, Scotland, Wales) is ordinary text, and what such runs spell is still
# scanned. All of it is a no-op for every shipped HEARTBEAT.md, pinned by the same test.
_INVISIBLE_TAG_FLAG = "invisible-unicode-tag"
_NESTING_FLAG = "nesting-too-deep"
_UNSCANNABLE_FLAG = "unscannable-value-type"
# Deep enough for any front-matter a person writes (the shipped ones reach three),
# shallow enough that a `&x [*x]` alias cycle — which PyYAML really does build — stops
# here, as a refusal, rather than in the interpreter's recursion limit.
_SCAN_MAX_DEPTH = 16
# YAML's own non-text scalars: nothing in them reads as words. `bool` is an `int`,
# `datetime` is a `date`.
_INERT_SCALAR_TYPES = (bool, int, float, datetime.date)
# 🏴 (U+1F3F4), one to eight TAG letters or digits, CANCEL TAG (U+E007F).
_FLAG_EMOJI_RE = re.compile("\U0001F3F4[\U000E0030-\U000E0039\U000E0061-\U000E007A]{1,8}\U000E007F")


def _add(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def _string_leaves(value: Any, flags: list[str], depth: int = 0) -> Iterator[str]:
    """Every string a parsed front-matter carries; a shape it will not vouch for is a flag.

    Refusing is the only safe answer to a shape the walker does not read: the caller
    treats "nothing yielded" as clean, so a silent return here would admit whatever
    the shape hid.
    """
    if isinstance(value, str):
        yield value
    elif value is None or isinstance(value, _INERT_SCALAR_TYPES):
        return
    elif isinstance(value, (bytes, bytearray)):
        # `!!binary`: decoded so the verdict names what it hid, refused regardless —
        # the encoding is a guess, and the agent could not use the value anyway.
        _add(flags, f"{_UNSCANNABLE_FLAG}:bytes")
        yield bytes(value).decode("utf-8", "replace")
    elif depth >= _SCAN_MAX_DEPTH:
        _add(flags, _NESTING_FLAG)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _string_leaves(key, flags, depth + 1)
            yield from _string_leaves(item, flags, depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _string_leaves(item, flags, depth + 1)
    else:
        _add(flags, f"{_UNSCANNABLE_FLAG}:{type(value).__name__}")


def _decode_invisible_tags(text: str) -> str:
    """Map U+E0000–U+E007F back to the ASCII they encode (twin of agent.py's)."""
    return "".join(chr(ord(ch) - 0xE0000) for ch in text if 0xE0000 <= ord(ch) <= 0xE007F)


def _join_surrogates(text: str) -> str:
    """UTF-16 surrogate pairs as the one character they spell — for SCANNING.

    PyYAML decodes a ``"\\uDB40\\uDC70"`` escape into two lone surrogates rather than
    U+E0070: code units no code-point range in `quarantine.py` matches, which a JSON
    serialiser on the way to a model joins back into the invisible TAG character. A
    surrogate that pairs with nothing becomes U+FFFD; ordinary text is unchanged.
    """
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def scan_heartbeat_config(config: Any) -> list[str]:
    """Injection patterns found anywhere in a parsed HEARTBEAT front-matter (empty = clean).

    Structural refusals (`nesting-too-deep`, `unscannable-value-type:<type>`) are flags
    like any other: the entry is refused, and the verdict says why.
    """
    flags: list[str] = []
    for leaf in _string_leaves(config, flags):
        joined = _join_surrogates(leaf)
        for text in ((leaf, joined) if joined != leaf else (leaf,)):
            visible = _FLAG_EMOJI_RE.sub("", text)
            if strip_invisible(visible) != visible:
                _add(flags, _INVISIBLE_TAG_FLAG)
            decoded = _decode_invisible_tags(text)
            if decoded:
                # CANCEL TAG decodes to DEL, which the normaliser reads as the blank it
                # is — so flag-shaped runs that together spell a phrase are named too.
                for pattern in detect_injection_normalized(decoded):
                    _add(flags, pattern)
            for pattern in detect_injection_normalized(text):
                _add(flags, pattern)
    return flags


class HeartbeatScheduler:
    def __init__(self, agents_dir: Optional[str] = None):
        if agents_dir is None:
            # Anchored on the app root (repo checkout / frozen bundle), not the
            # CWD — identical to the old "agents" default when run from the repo.
            from .paths import app_root
            agents_dir = app_root() / "agents"
        self.agents_dir = Path(agents_dir)
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._heartbeat_configs: dict[str, dict] = {}
        # H506: the entries the injection scan refused, keyed by the agent directory
        # that carried the file — never in `_heartbeat_configs`, so never scheduled.
        self._blocked: dict[str, dict] = {}

    def load_all(self):
        """Scan all agent directories for HEARTBEAT.md files."""
        if not self.agents_dir.exists():
            logger.warning(f"Agents directory not found: {self.agents_dir}")
            return
        for agent_dir in self.agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            # A reload starts this directory from a clean slate: the verdict an earlier
            # load recorded belongs to the file as it was then, and so does the config
            # it admitted (dropped below if the file is refused now).
            self._blocked.pop(agent_dir.name, None)
            # Personalization overlay: HEARTBEAT.local.md (gitignored) wins over
            # the shipped template — same convention as SOUL.local.md. A user
            # data home (Documents/Jarvis/souls/<id>/) wins over both.
            from . import safe_mode
            from .paths import user_souls_dir
            souls_home = user_souls_dir()
            hb_path = None
            if souls_home is not None:
                candidate = souls_home / agent_dir.name / "HEARTBEAT.local.md"
                if candidate.exists():
                    hb_path = candidate
            if hb_path is None:
                hb_path = agent_dir / "HEARTBEAT.local.md"
            if safe_mode.enabled() and hb_path.exists():
                # H275: the shipped schedule only; an overlay's runs are not scheduled.
                safe_mode.note("heartbeat_overlays")
                hb_path = agent_dir / "HEARTBEAT.md"
            if not hb_path.exists():
                hb_path = agent_dir / "HEARTBEAT.md"
            if hb_path.exists():
                config = self._parse_heartbeat(hb_path)
                if config:
                    self._heartbeat_configs[config["agent"]] = config
                    logger.info(f"Loaded heartbeat: {config['agent']} — {config.get('cadence', 'unknown')}")
                elif agent_dir.name in self._blocked:
                    # Refused now: a config an earlier load admitted for this directory
                    # must not outlive the file that earned it. A refused file evicts
                    # whatever another source put here first, so the verdict holds even
                    # when load_from_config ran before load_all.
                    self._heartbeat_configs.pop(agent_dir.name, None)

    def _parse_heartbeat(self, path: Path) -> Optional[dict]:
        """Parse the YAML frontmatter from a HEARTBEAT.md file.

        Never returns a config the injection scan flagged: the parser is the one place
        file bytes become a heartbeat config, so the scan sits here rather than in a
        caller that could be bypassed. A refused file is recorded in ``_blocked`` under
        the directory that carried it and reported by ``get_status()``.
        """
        # One read: the digest below is over the buffer that was parsed and scanned,
        # so a file rewritten in between cannot earn a verdict naming other bytes.
        raw = path.read_bytes()
        content = raw.decode("utf-8")
        if not content.startswith("---"):
            return None

        _, frontmatter, _ = content.split("---", 2)
        import yaml
        try:
            config = yaml.safe_load(frontmatter)
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse {path}: {e}")
            return None
        flags = scan_heartbeat_config(config)
        if flags:
            # The bytes on disk, so the owner can match the log line with `sha256sum`.
            digest = hashlib.sha256(raw).hexdigest()
            self._blocked[path.parent.name] = {
                "agent_id": path.parent.name, "path": self._public_path(path),
                "flags": flags, "digest": digest,
            }
            logger.error(
                "HEARTBEAT injection scan refused %s for agent %s — not scheduled; "
                "sha256 %s; matched: %s",
                path, path.parent.name, digest, ", ".join(flags),
            )
            return None
        return config

    def _public_path(self, path: Path) -> str:
        """The file as the verdict names it: relative to the root it was found under.

        ``GET /heartbeat/status`` is a deliberately public route (aggregate
        observability, no token), and a data-home overlay's absolute path spells the
        OS user name and the data-home layout. The owner needs to know WHICH file —
        ``agents/<id>/HEARTBEAT.local.md`` or ``souls/<id>/HEARTBEAT.local.md`` — and
        the log line, owner-only, keeps the absolute path beside the digest.
        """
        from .paths import user_souls_dir
        for root in (self.agents_dir, user_souls_dir()):
            if root is None:
                continue
            try:
                relative = path.resolve().relative_to(Path(root).resolve())
            except ValueError:
                continue
            return str(Path(Path(root).name) / relative)
        return path.name

    def _cron_fires_per_day(self, parts: list[str]) -> float:
        """Estimate how many times a cron expression fires in a 24h period."""
        minute, hour, day, month, dow = parts
        hour_count = self._field_count(hour, 24)
        minute_count = self._field_count(minute, 60)
        if hour_count == 0 or minute_count == 0:
            return 0
        base = float(hour_count * minute_count)
        if dow != "*":
            base *= max(0.01, self._field_count(dow, 7) / 7)
        if day != "*":
            base *= max(0.01, self._field_count(day, 31) / 31)
        if month != "*":
            base *= max(0.01, self._field_count(month, 12) / 12)
        return base

    def _field_count(self, field: str, max_val: int) -> int:
        """Count distinct values a cron field can match (approximate)."""
        field = field.strip()
        if field == "*":
            return max_val
        if "/" in field:
            if field.startswith("*/"):
                step = int(field[2:])
                return max(1, max_val // step)
            base, step = field.split("/")
            base_count = self._field_count(base, max_val)
            step_val = int(step)
            return max(1, base_count // step_val)
        parts = [p.strip() for p in field.split(",")]
        total = 0
        for p in parts:
            if "-" in p:
                lo, hi = p.split("-")
                if not (lo.isdigit() and hi.isdigit()):
                    return max_val
                total += int(hi) - int(lo) + 1
            else:
                try:
                    int(p)
                    total += 1
                except ValueError:
                    return max_val
        return total

    def load_from_config(self, config):
        """Fill in agents.yaml interval heartbeats for agents that have no heartbeat file.

        The module docstring states the precedence: an agent already in
        ``_heartbeat_configs`` keeps its file — cadence and checklist — and an agent in
        ``_blocked`` gets nothing, so the scan's verdict is not undone by a second source
        re-adding the same agent as an interval job.
        """
        for agent_id, agent_cfg in config.agents.items():
            if agent_cfg.status != "active":
                continue
            if not agent_cfg.has_heartbeat:
                continue
            if agent_id in self._blocked:
                # The orchestrator calls this right after `load_all`, and an interval
                # entry written here unconditionally would put a refused agent back
                # into `_heartbeat_configs` before `start()` — scheduled after all.
                logger.warning(
                    "Heartbeat %s: agents.yaml interval not scheduled — its HEARTBEAT file "
                    "was refused by the injection scan (sha256 %s)",
                    agent_id, self._blocked[agent_id]["digest"],
                )
                continue
            interval_str = agent_cfg.heartbeat if hasattr(agent_cfg, 'heartbeat') else None
            if not isinstance(interval_str, str) or interval_str == "no":
                continue
            if agent_id in self._blocked:
                logger.warning(
                    "Heartbeat %s: agents.yaml interval %s withheld — its HEARTBEAT file was refused",
                    agent_id, interval_str,
                )
                continue
            existing = self._heartbeat_configs.get(agent_id)
            if existing is not None:
                logger.info(
                    "Heartbeat %s: keeping %s from its HEARTBEAT file over the agents.yaml interval %s",
                    agent_id, existing.get("cadence", "unknown"), interval_str,
                )
                continue
            seconds = self._parse_interval(interval_str)
            seconds = self._coerce_interval(seconds)
            self._heartbeat_configs[agent_id] = {
                "agent": agent_id,
                "cadence": f"interval:{seconds}",
                "interval_seconds": seconds,
            }
            logger.info(f"Loaded heartbeat from config: {agent_id} — {interval_str} ({seconds}s)")

    def _parse_interval(self, interval_str: str) -> int:
        """Convert a human-readable interval string to seconds."""
        interval_str = interval_str.strip().lower()
        if interval_str.endswith("h"):
            return int(interval_str[:-1]) * 3600
        elif interval_str.endswith("m"):
            return int(interval_str[:-1]) * 60
        elif interval_str.endswith("s"):
            return int(interval_str[:-1])
        else:
            try:
                return int(interval_str)
            except ValueError:
                logger.warning(f"Unrecognized heartbeat interval: {interval_str}, defaulting to {MIN_HEARTBEAT_INTERVAL}s")
                return MIN_HEARTBEAT_INTERVAL

    def _coerce_interval(self, seconds: int) -> int:
        """Apply MIN_HEARTBEAT_INTERVAL guardrail."""
        if seconds < MIN_HEARTBEAT_INTERVAL:
            logger.warning(
                f"Heartbeat interval {seconds}s is below minimum {MIN_HEARTBEAT_INTERVAL}s, coercing upward"
            )
            return MIN_HEARTBEAT_INTERVAL
        return seconds

    def start(self, orchestrator):
        """Start the APScheduler with all loaded heartbeats (cron + interval)."""
        if AsyncIOScheduler is None:
            logger.warning("APScheduler not installed, heartbeats disabled")
            return

        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler()

        jobs = getattr(orchestrator, "jobs", None)
        if jobs is not None:
            from .scheduler_health import install_scheduler_health

            install_scheduler_health(self.scheduler, jobs.store)

        for agent_id, config in self._heartbeat_configs.items():
            if agent_id in self._blocked:
                # Both loaders keep a refused agent out of _heartbeat_configs; this is
                # the gate at the point where APScheduler is actually fed.
                logger.warning("Heartbeat %s: not scheduled — its HEARTBEAT file was refused", agent_id)
                continue
            cadence = config.get("cadence", "")
            if cadence.startswith("interval:"):
                seconds = int(cadence.split(":")[1])
                jitter = random.randint(JITTER_MIN, JITTER_MAX)
                self.scheduler.add_job(
                    self._run_heartbeat,
                    "interval",
                    seconds=seconds,
                    args=[agent_id, orchestrator],
                    id=f"heartbeat-{agent_id}",
                    replace_existing=True,
                    jitter=jitter,
                )
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                logger.info(f"Scheduled heartbeat: {agent_id} @ {hours}h{minutes}m interval (jitter={jitter}s)")
            elif cadence.startswith("cron:"):
                cron_expr = cadence[5:]
                parts = cron_expr.strip().split()
                if len(parts) == 5:
                    fires_per_day = self._cron_fires_per_day(parts)
                    if fires_per_day > 24:
                        avg_interval = 86400 / fires_per_day
                        logger.warning(
                            f"Heartbeat {agent_id} fires ~{fires_per_day:.0f}x/day "
                            f"(avg interval ~{avg_interval:.0f}s, min is {MIN_HEARTBEAT_INTERVAL}s). "
                            f"Cron: {cron_expr}"
                        )
                    jitter = random.randint(JITTER_MIN, JITTER_MAX)
                    # cron counts Sunday as 0; APScheduler counts Monday as 0. Passing the
                    # field straight through fired every weekday heartbeat a day late
                    # (found while building the owner's jobs — BACKLOG HA-2c). The jobs
                    # engine owns the one translation.
                    from .autonomy.jobs import cron_kwargs

                    try:
                        cron_fields = cron_kwargs(" ".join(parts))
                    except ValueError as exc:
                        logger.warning(f"Heartbeat {agent_id}: unusable cron '{cron_expr}': {exc}")
                        continue
                    self.scheduler.add_job(
                        self._run_heartbeat,
                        "cron",
                        **cron_fields,
                        args=[agent_id, orchestrator],
                        id=f"heartbeat-{agent_id}",
                        replace_existing=True,
                        jitter=jitter,
                    )
                    logger.info(f"Scheduled heartbeat: {agent_id} @ {cron_expr} (jitter={jitter}s)")

        self.scheduler.start()
        logger.info("Heartbeat scheduler started")

    async def _run_heartbeat(self, agent_id: str, orchestrator):
        """Execute a single agent's heartbeat."""
        from agents.core import estop
        if estop.check_paused(f"heartbeat:{agent_id}", logger):
            return {"_scheduler_status": "skipped"}
        try:
            result = await orchestrator.run_heartbeat(agent_id)
            if result:
                logger.info(f"Heartbeat {agent_id}: {result[:100]}")
        except Exception as e:
            logger.error(f"Heartbeat failed for {agent_id}: {e}")
            return {"_scheduler_status": "failed"}

    def stop(self):
        if self.scheduler:
            try:
                self.scheduler.shutdown()
            except SchedulerNotRunningError:
                pass

    def get_status(self):
        """Return status of all scheduled heartbeats.

        ``blocked`` lists the HEARTBEAT files the injection scan refused at load — the
        HUD must not show an agent as merely "stopped" when its schedule was in fact
        quarantined. Same three-field shape in both branches, so a HUD or the runtime
        run-log reading it sees the verdict whether or not the scheduler is up.
        """
        blocked = [dict(verdict) for verdict in self._blocked.values()]
        if not self.scheduler:
            return {"scheduler_running": False, "heartbeats": [], "blocked": blocked}

        heartbeats = []
        for job in self.scheduler.get_jobs():
            if job.id.startswith("heartbeat-"):
                agent_id = job.id.replace("heartbeat-", "")
                heartbeats.append({
                    "agent_id": agent_id,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                })

        return {
            "scheduler_running": self.scheduler.running,
            "heartbeats": heartbeats,
            "blocked": blocked,
        }

    def start_heartbeat(self, agent_id: str, orchestrator):
        """Start a single heartbeat job."""
        if not self.scheduler or not self.scheduler.running:
            return False

        if agent_id in self._blocked:
            logger.warning("Cannot resume heartbeat %s: its HEARTBEAT file was refused", agent_id)
            return False
        config = self._heartbeat_configs.get(agent_id)
        if not config:
            return False
        
        cadence = config.get("cadence", "")
        if cadence.startswith("interval:"):
            seconds = int(cadence.split(":")[1])
            jitter = random.randint(JITTER_MIN, JITTER_MAX)
            self.scheduler.add_job(
                self._run_heartbeat,
                "interval",
                seconds=seconds,
                args=[agent_id, orchestrator],
                id=f"heartbeat-{agent_id}",
                replace_existing=True,
                jitter=jitter,
            )
            return True
        elif cadence.startswith("cron:"):
            cron_expr = cadence[5:]
            parts = cron_expr.strip().split()
            if len(parts) == 5:
                from .autonomy.jobs import cron_kwargs

                try:
                    cron_fields = cron_kwargs(cron_expr)
                except ValueError as exc:
                    logger.warning("Cannot resume heartbeat %s: %s", agent_id, exc)
                    return False
                jitter = random.randint(JITTER_MIN, JITTER_MAX)
                self.scheduler.add_job(
                    self._run_heartbeat,
                    "cron",
                    **cron_fields,
                    args=[agent_id, orchestrator],
                    id=f"heartbeat-{agent_id}",
                    replace_existing=True,
                    jitter=jitter,
                )
                return True
        return False

    def stop_heartbeat(self, agent_id: str):
        """Stop a single heartbeat job."""
        if not self.scheduler:
            return False
        try:
            self.scheduler.remove_job(f"heartbeat-{agent_id}")
            return True
        except Exception:
            return False

    async def run_now(self, agent_id: str, orchestrator):
        """Run a heartbeat immediately."""
        await self._run_heartbeat(agent_id, orchestrator)
        return True
