"""
watchers.py — Proactive Personal Event Watchers (Antigravity additions).

Similar to the Proactive OS Observer (`observer.py`), this module monitors personal
data streams (Gmail, Google Calendar, balance readers, Apple Health companion)
and turns state changes or important events into autonomy tasks.

It uses the same state-change debouncing system to prevent alert spam:
- If a low balance is detected, a single alert is submitted. Once the balance
  rises above the threshold, a recovery is fired, clearing the active state.
- Urgent emails and upcoming meetings are tracked by their unique IDs.
- Health sleep and stress (HRV) anomalies are flagged and debounced.

Offline testability is guaranteed: if plugins are missing, not configured,
or throw HTTP exceptions, the probes degrade gracefully to return empty lists
or mock data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from .observer import Signal, Severity, Finding, RiskTier

logger = logging.getLogger("jarvis.autonomy.watchers")


class EmailProbe:
    """Monitors Gmail for new unread priority/urgent messages.

    Flags an alert for any email matching urgent keywords (e.g. 'urgent', 'critical')
    or important senders, debounced by message ID.
    """

    def __init__(self, gmail_plugin=None, priority_senders: list[str] = None, get_setting=None):
        self.plugin = gmail_plugin
        self._default_priority_senders = priority_senders or []
        self.get_setting = get_setting

    @property
    def priority_senders(self) -> list[str]:
        if self.get_setting:
            try:
                val = self.get_setting("autonomy.priority_senders", self._default_priority_senders)
                if isinstance(val, list):
                    return val
            except Exception:
                logger.warning("Failed to read autonomy.priority_senders setting", exc_info=True)
        return self._default_priority_senders

    async def __call__(self) -> list[Signal]:
        if self.plugin is None or not hasattr(self.plugin, "list_messages"):
            return []

        try:
            # Check last 5 messages
            messages = await self.plugin.list_messages(max_results=5)
            if not messages or "error" in messages[0]:
                return []

            signals: list[Signal] = []
            for msg in messages:
                msg_id = msg.get("id")
                if not msg_id:
                    continue

                subject = (msg.get("subject") or "").lower()
                sender = (msg.get("from") or "").lower()
                snippet = (msg.get("snippet") or "").lower()

                # Determine if priority/urgent
                is_urgent = any(kw in subject or kw in snippet for kw in ["urgent", "critical", "alerta", "atentie"])
                is_priority_sender = any(s in sender for s in self.priority_senders)

                if is_urgent or is_priority_sender:
                    severity = Severity.CRITICAL if "critical" in subject else Severity.WARN
                    signals.append(Signal(
                        key=f"email.urgent.{msg_id}",
                        healthy=False,
                        severity=severity,
                        detail=f"Urgent email from {msg.get('from')}: '{msg.get('subject')}'",
                        agent="stark"
                    ))
                else:
                    # Healthy state for this message ID (resolves alert if it was previously flagged)
                    signals.append(Signal(
                        key=f"email.urgent.{msg_id}",
                        healthy=True,
                        agent="stark"
                    ))
            return signals
        except Exception as e:
            logger.warning(f"EmailProbe failed: {e}")
            return []


class CalendarProbe:
    """Monitors Google Calendar for upcoming meetings starting in less than 30 minutes."""

    def __init__(self, calendar_plugin=None, lead_time_min: int = 30, get_setting=None):
        self.plugin = calendar_plugin
        self._default_lead_time_min = lead_time_min
        self.get_setting = get_setting

    @property
    def lead_time_min(self) -> int:
        if self.get_setting:
            try:
                return int(self.get_setting("autonomy.calendar_lead_time", self._default_lead_time_min))
            except Exception:
                logger.warning("Failed to read autonomy.calendar_lead_time setting", exc_info=True)
        return self._default_lead_time_min

    async def __call__(self) -> list[Signal]:
        if self.plugin is None or not hasattr(self.plugin, "get_today_events"):
            return []

        try:
            events = await self.plugin.get_today_events()
            if not events or (isinstance(events, list) and len(events) > 0 and "error" in events[0]):
                return []

            now_ts = datetime.now(timezone.utc).timestamp()
            signals: list[Signal] = []

            for ev in events:
                title = ev.get("title", "(no title)")
                state = ev.get("state")
                ts_str = ev.get("ts")
                
                # Parse timestamp
                event_ts = self._parse_ts(ts_str)
                if event_ts is None:
                    continue

                time_diff_sec = event_ts - now_ts
                event_id = ev.get("id") or f"{title}_{event_ts}"
                key = f"calendar.meeting.{event_id}"

                # Trigger when starting in less than lead_time_min, but not in the past
                if 0 < time_diff_sec < (self.lead_time_min * 60):
                    min_left = int(time_diff_sec / 60)
                    signals.append(Signal(
                        key=key,
                        healthy=False,
                        severity=Severity.WARN,
                        detail=f"Meeting '{title}' starting in {min_left} mins!",
                        agent="pepper"
                    ))
                else:
                    # Healthy state (clears past alerts)
                    signals.append(Signal(
                        key=key,
                        healthy=True,
                        agent="pepper"
                    ))
            return signals
        except Exception as e:
            logger.warning(f"CalendarProbe failed: {e}")
            return []

    def _parse_ts(self, ts_str: str) -> Optional[float]:
        if not ts_str:
            return None
        try:
            if "T" in ts_str:
                dt = datetime.fromisoformat(ts_str)
            else:
                dt = datetime.fromisoformat(ts_str).replace(hour=0, minute=0, tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            return None


class FinanceProbe:
    """Monitors financial accounts for low balances or runway issues."""

    def __init__(self, balance_plugin=None, min_ron: float = 2000.0, min_eur: float = 400.0, get_setting=None):
        self.plugin = balance_plugin
        self._default_min_ron = min_ron
        self._default_min_eur = min_eur
        self.get_setting = get_setting

    @property
    def min_ron(self) -> float:
        if self.get_setting:
            try:
                return float(self.get_setting("autonomy.finance_min_ron", self._default_min_ron))
            except Exception:
                logger.warning("Failed to read autonomy.finance_min_ron setting", exc_info=True)
        return self._default_min_ron

    @property
    def min_eur(self) -> float:
        if self.get_setting:
            try:
                return float(self.get_setting("autonomy.finance_min_eur", self._default_min_eur))
            except Exception:
                logger.warning("Failed to read autonomy.finance_min_eur setting", exc_info=True)
        return self._default_min_eur

    async def __call__(self) -> list[Signal]:
        if self.plugin is None or not hasattr(self.plugin, "get_balances"):
            return []

        try:
            balances = await self.plugin.get_balances()
            signals: list[Signal] = []

            # Check individual accounts
            for source, accounts in balances.items():
                if source == "mock" or not isinstance(accounts, list):
                    continue
                for acct in accounts:
                    acct_id = acct.get("account", "unknown")
                    balance = float(acct.get("balance", 0.0))
                    currency = acct.get("currency", "RON").upper()
                    
                    threshold = self.min_ron if currency == "RON" else self.min_eur
                    key = f"finance.balance.{acct_id}"

                    if balance < threshold:
                        signals.append(Signal(
                            key=key,
                            healthy=False,
                            severity=Severity.WARN,
                            detail=f"Low balance on {source.upper()} ({acct_id}): {balance:.2f} {currency} (threshold {threshold:.2f})",
                            agent="gecko"
                        ))
                    else:
                        signals.append(Signal(
                            key=key,
                            healthy=True,
                            detail=f"Balance on {source.upper()} ({acct_id}) is healthy: {balance:.2f} {currency}",
                            agent="gecko"
                        ))

            # Check monthly runway
            if hasattr(self.plugin, "get_burn_rate"):
                burn = await self.plugin.get_burn_rate()
                runway = float(burn.get("runway_months", 99.0))
                if runway < 3.0:
                    signals.append(Signal(
                        key="finance.runway",
                        healthy=False,
                        severity=Severity.CRITICAL,
                        detail=f"Low runway alert: only {runway:.1f} months remaining!",
                        agent="gecko"
                    ))
                else:
                    signals.append(Signal(
                        key="finance.runway",
                        healthy=True,
                        detail=f"Financial runway is safe: {runway:.1f} months.",
                        agent="gecko"
                    ))

            return signals
        except Exception as e:
            logger.warning(f"FinanceProbe failed: {e}")
            return []


class HealthProbe:
    """Monitors Apple Health summary data for sleep duration or HRV strain."""

    def __init__(self, health_plugin=None, min_sleep_hrs: float = 5.0, min_hrv_ms: float = 30.0, get_setting=None):
        self.plugin = health_plugin
        self._default_min_sleep_hrs = min_sleep_hrs
        self._default_min_hrv_ms = min_hrv_ms
        self.get_setting = get_setting

    @property
    def min_sleep_hrs(self) -> float:
        if self.get_setting:
            try:
                return float(self.get_setting("autonomy.health_min_sleep", self._default_min_sleep_hrs))
            except Exception:
                logger.warning("Failed to read autonomy.health_min_sleep setting", exc_info=True)
        return self._default_min_sleep_hrs

    @property
    def min_hrv_ms(self) -> float:
        if self.get_setting:
            try:
                return float(self.get_setting("autonomy.health_min_hrv", self._default_min_hrv_ms))
            except Exception:
                logger.warning("Failed to read autonomy.health_min_hrv setting", exc_info=True)
        return self._default_min_hrv_ms

    async def __call__(self) -> list[Signal]:
        if self.plugin is None or not hasattr(self.plugin, "get_summary"):
            return []

        try:
            summary = await self.plugin.get_summary(days=1)
            signals: list[Signal] = []

            # Parse Sleep
            sleep_data = summary.get("sleep", [])
            if sleep_data and isinstance(sleep_data, list):
                # Calculate total sleep hours
                # Sleep records are typically list of dicts with hours/duration
                total_sleep = 0.0
                for record in sleep_data:
                    total_sleep += float(record.get("hours", record.get("duration", 0.0)))
                
                if total_sleep > 0:
                    if total_sleep < self.min_sleep_hrs:
                        signals.append(Signal(
                            key="health.sleep",
                            healthy=False,
                            severity=Severity.WARN,
                            detail=f"Short sleep duration: only {total_sleep:.1f} hours logged last night.",
                            agent="hercules"
                        ))
                    else:
                        signals.append(Signal(
                            key="health.sleep",
                            healthy=True,
                            detail=f"Sleep duration is healthy: {total_sleep:.1f} hours.",
                            agent="hercules"
                        ))

            # Parse HRV
            hrv_data = summary.get("hrv", [])
            if hrv_data and isinstance(hrv_data, list):
                # Check average HRV last night
                avg_hrv = 0.0
                hrv_vals = [float(r.get("value", r.get("hrv", 0.0))) for r in hrv_data if r.get("value", r.get("hrv"))]
                if hrv_vals:
                    avg_hrv = sum(hrv_vals) / len(hrv_vals)
                
                if avg_hrv > 0:
                    if avg_hrv < self.min_hrv_ms:
                        signals.append(Signal(
                            key="health.hrv",
                            healthy=False,
                            severity=Severity.WARN,
                            detail=f"Low HRV strain: average HRV is {avg_hrv:.1f} ms last night.",
                            agent="hercules"
                        ))
                    else:
                        signals.append(Signal(
                            key="health.hrv",
                            healthy=True,
                            detail=f"HRV is healthy: {avg_hrv:.1f} ms.",
                            agent="hercules"
                        ))

            return signals
        except Exception as e:
            logger.warning(f"HealthProbe failed: {e}")
            return []


def _eta_text(t_ingress) -> str:
    """Render ' in ~Nm' from a unix-seconds ingress time, or '' if unknown/past."""
    try:
        delta = float(t_ingress) - datetime.now(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return ""
    if delta <= 0:
        return ""
    mins = int(delta // 60)
    return f" in ~{mins}m" if mins else " imminently"


class WorldViewProbe:
    """Monitors the local WorldView 4D OSINT platform for *due* satellite recon
    passes and dark-vessel detections, turning each into an autonomy signal so it
    surfaces in the JARVIS digest (within the daily urgent budget) with a
    provenance link back to WorldView.

    Debounced by a stable per-event key (one alert per pass / per dark vessel).
    Degrades gracefully: if the WorldView plugin is absent or its backend is
    unreachable, the probe returns no signals — it never raises and never invents
    intel (an OSINT surface). Reuses the read-only ``WorldViewPlugin`` (H19.3.3),
    so it inherits that plugin's retry + circuit-breaker and permission scope.
    """

    def __init__(self, worldview_plugin=None, lead_min: int = 30, get_setting=None):
        self.plugin = worldview_plugin
        self._default_lead_min = lead_min
        self.get_setting = get_setting

    @property
    def lead_min(self) -> int:
        if self.get_setting:
            try:
                return int(self.get_setting("autonomy.worldview_lead_min", self._default_lead_min))
            except Exception:
                logger.warning("Failed to read autonomy.worldview_lead_min setting", exc_info=True)
        return self._default_lead_min

    async def __call__(self) -> list[Signal]:
        if self.plugin is None:
            return []
        signals: list[Signal] = []
        signals.extend(await self._recon_signals())
        signals.extend(await self._dark_vessel_signals())
        return signals

    async def _recon_signals(self) -> list[Signal]:
        """Satellite recon passes due within the lead window → WARN signals."""
        if not hasattr(self.plugin, "recon_alerts"):
            return []
        try:
            res = await self.plugin.recon_alerts(lead=float(self.lead_min) * 60.0)
        except Exception as e:
            logger.warning(f"WorldViewProbe recon probe failed: {e}")
            return []
        if not isinstance(res, dict) or res.get("status") != "ok":
            return []  # backend unavailable → no signals
        out: list[Signal] = []
        for alert in res.get("alerts", []) or []:
            norad = alert.get("norad_id")
            aoi = alert.get("aoi_id")
            if norad is None or aoi is None:
                continue
            sensor = alert.get("sensor_type") or "sensor"
            eta = _eta_text(alert.get("t_ingress"))
            # Provenance link: the pass traces to the WorldView 'tle' layer entity.
            prov = f"provenance WorldView /provenance/tle/{norad}"
            out.append(Signal(
                key=f"worldview.recon.{norad}.{aoi}",
                healthy=False,
                severity=Severity.WARN,
                detail=f"Recon pass: {sensor} sat {norad} over AOI '{aoi}'{eta} — {prov}",
                agent="athena",
            ))
        return out

    async def _dark_vessel_signals(self) -> list[Signal]:
        """Dark-vessel detections (AIS gap in a watched geofence) → CRITICAL signals."""
        if not hasattr(self.plugin, "state_at"):
            return []
        now = datetime.now(timezone.utc).timestamp()
        try:
            res = await self.plugin.state_at("context", now)
        except Exception as e:
            logger.warning(f"WorldViewProbe dark-vessel probe failed: {e}")
            return []
        if not isinstance(res, dict) or res.get("status") != "ok":
            return []
        out: list[Signal] = []
        for feat in res.get("features", []) or []:
            props = (feat or {}).get("properties", {}) or {}
            if props.get("kind") != "dark_vessel":
                continue
            mmsi = props.get("mmsi") or props.get("entity_id")
            if mmsi is None:
                continue
            prov = f"provenance WorldView /provenance/ais/{mmsi}"
            out.append(Signal(
                key=f"worldview.dark_vessel.{mmsi}",
                healthy=False,
                severity=Severity.CRITICAL,
                detail=f"Dark vessel: MMSI {mmsi} went silent in a watched geofence — {prov}",
                agent="athena",
            ))
        return out


# ── the event watcher ────────────────────────────────────────────────
class EventWatcher:
    """Aggregates probes, debounces events, and feeds the autonomy worker.

    Identical state-change debouncing logic as ProactiveObserver.
    """

    def __init__(self, worker, probes: list[Callable[[], list[Signal]]] = None):
        self.worker = worker
        self.probes = probes or []
        self._state: dict[str, bool] = {}  # key -> last-known healthy

    def evaluate(self, signals: list[Signal]) -> list[Finding]:
        findings: list[Finding] = []
        for sig in signals:
            was_healthy = self._state.get(sig.key, True)
            if was_healthy and not sig.healthy:
                findings.append(Finding(sig, "alert"))
            elif not was_healthy and sig.healthy:
                findings.append(Finding(sig, "recovery"))
            self._state[sig.key] = sig.healthy
        return findings

    async def _gather(self) -> list[Signal]:
        signals: list[Signal] = []
        for probe in self.probes:
            try:
                res = await probe()
                signals.extend(res or [])
            except Exception as e:
                logger.warning(f"EventWatcher probe failed: {e}")
        return signals

    async def observe(self) -> dict:
        signals = await self._gather()
        findings = self.evaluate(signals)
        submitted = 0
        for finding in findings:
            try:
                await self._submit(finding)
                submitted += 1
            except Exception as e:
                logger.warning(f"EventWatcher submit failed for {finding.signal.key}: {e}")
        return {
            "sampled": len(signals),
            "findings": len(findings),
            "submitted": submitted,
            "unhealthy": [k for k, ok in self._state.items() if not ok],
        }

    async def _submit(self, finding: Finding):
        sig = finding.signal
        if finding.transition == "recovery":
            return await self.worker.submit(
                agent=sig.agent,
                kind="monitor.recovery",
                title=f"✓ Resolved: {sig.detail if sig.detail else sig.key}",
                payload={"key": sig.key, "risk_tier": int(RiskTier.READ_ONLY)},
                origin="generated",
            )

        # Alerts are submitted as READ_ONLY -> auto-approved and surfaced in HUD / brief
        prefix = "⚠️ " if sig.severity >= Severity.CRITICAL else "🔔 "
        return await self.worker.submit(
            agent=sig.agent,
            kind="monitor.alert",
            title=f"{prefix}{sig.detail}",
            payload={"key": sig.key, "severity": sig.severity.name, "risk_tier": int(RiskTier.READ_ONLY)},
            origin="generated",
        )
