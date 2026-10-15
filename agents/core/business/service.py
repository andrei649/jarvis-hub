"""Business operations over durable snapshots and approved read-only adapters."""

from __future__ import annotations

import asyncio
import json

from agents.core.business.catalog import catalog
from agents.core.business.store import BusinessStore


class BusinessError(Exception):
    def __init__(self, code: str, message: str, status: int):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def _missing():
    raise BusinessError("not_found", "Connection not found", 404)


class BusinessService:
    def __init__(self, store: BusinessStore):
        self.store = store

    def workspace(self) -> dict:
        return {"workspace": self.store.profile(), "connections": self.store.list_connections(), "reports": self.store.list_reports(), "activity": self.store.list_activity()}

    def update_workspace(self, profile: dict) -> dict:
        return {"workspace": self.store.update_profile(profile)}

    def add_connection(self, provider: str, name: str, base_url: str, credentials: dict) -> dict:
        from agents.core.business.connectors import validate_connection

        if provider not in {"woocommerce", "hubspot"}:
            raise BusinessError("invalid_provider", "Choose a supported remote connector", 422)
        try:
            normalized = validate_connection(provider, base_url, credentials)
        except ValueError:
            raise BusinessError("invalid_connection", "Check the connector URL and credentials", 422) from None
        try:
            return self.store.add_connection(provider, name, normalized, credentials)
        except ValueError:
            raise BusinessError("limit_reached", "Connection limit reached", 409) from None

    async def sync(self, connection_id: str) -> dict:
        from agents.core.business.connectors import ConnectorError, fetch_snapshot

        connection = await asyncio.to_thread(self.store.get_connection, connection_id)
        if connection is None:
            _missing()
        if connection["provider"] == "csv":
            raise BusinessError("unsupported", "CSV imports are updated by importing a file", 422)
        try:
            credentials = await asyncio.to_thread(self.store.credentials, connection_id)
        except Exception:
            raise BusinessError("credentials_unavailable", "Saved credentials are unavailable", 503) from None
        try:
            snapshot = await fetch_snapshot(connection["provider"], connection["base_url"], credentials)
            return await asyncio.to_thread(self.store.replace_snapshot, connection_id, snapshot)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ConnectorError) else "Sincronizarea nu a reușit. Verifică serviciul și configurarea."
            await asyncio.to_thread(self.store.mark_sync_error, connection_id, message)
            raise BusinessError("sync_failed", f"{message} Datele sincronizate anterior, dacă există, au fost păstrate.", 502) from None

    def remove_connection(self, connection_id: str) -> dict:
        if not self.store.remove_connection(connection_id):
            _missing()
        return {"ok": True}

    def import_csv(self, name: str, kind: str, csv_text: str) -> dict:
        from agents.core.business.connectors import CsvImportError, parse_csv

        try:
            snapshot = parse_csv(csv_text, kind)
        except CsvImportError as exc:
            raise BusinessError("invalid_csv", str(exc), 422) from None
        except Exception:
            raise BusinessError("invalid_csv", "Fișierul CSV nu a putut fi validat. Verifică formatul și coloanele.", 422) from None
        existing = next((c for c in self.store.list_connections() if c["provider"] == "csv" and c["name"] == name), None)
        if existing and self.store.snapshot_kind(existing["id"]) != kind:
            raise BusinessError("source_kind_mismatch", "This CSV source name is already used for another record kind", 409)
        try:
            cid = existing["id"] if existing else self.store.add_connection("csv", name, "", {})["id"]
        except ValueError:
            raise BusinessError("limit_reached", "Connection limit reached", 409) from None
        try:
            return self.store.replace_snapshot(cid, {**snapshot, "kind": kind})
        except (ValueError, TypeError, KeyError):
            raise BusinessError("invalid_csv", "CSV format or values are invalid", 422) from None

    def _current_snapshots(self) -> list[dict]:
        snapshots = self.store.snapshots()
        connections = {item["id"]: item for item in self.store.list_connections()}
        for snapshot in snapshots:
            connection = connections.get(snapshot["connection_id"], {})
            snapshot["provider"] = connection.get("provider")
            if connection.get("status") == "stale":
                snapshot["complete"] = False
                snapshot["stale"] = True
        return snapshots

    def run_report(self, workflow_id: str, *, connection_id: str | None = None,
                   start_date: str | None = None, end_date: str | None = None) -> dict:
        from agents.core.business.reports import ReportFilterError, build_report

        if workflow_id not in {w["id"] for w in catalog()["workflows"]}:
            raise BusinessError("unknown_workflow", "Workflow not found", 404)
        snapshots = self._current_snapshots()
        if connection_id is not None:
            if self.store.get_connection(connection_id) is None:
                raise BusinessError("source_not_found", "Sursa selectată nu mai există. Actualizează lista surselor.", 404)
            snapshots = [item for item in snapshots if item["connection_id"] == connection_id]
        try:
            report = build_report(workflow_id, snapshots, start_date=start_date, end_date=end_date)
            report["source_selection"] = {"connection_id": connection_id}
            return self.store.save_report(report)
        except ReportFilterError as exc:
            raise BusinessError("invalid_report_filter", str(exc), 422) from None
        except Exception:
            raise BusinessError("report_failed", "Report could not be built from saved data", 502) from None

    def _question_context(self, report_id: str | None = None) -> tuple[dict, bool]:
        from agents.core.business.reports import build_report

        if report_id is not None:
            saved = next((report for report in self.store.list_reports() if report["id"] == report_id), None)
            if saved is None:
                raise BusinessError("report_not_found", "Raportul selectat nu mai este disponibil. Rulează sau selectează alt raport.", 404)
            inputs = [saved]
        else:
            snapshots = self._current_snapshots()
            inputs = [build_report(workflow["id"], snapshots) for workflow in catalog()["workflows"]]
        reports = []
        for report in inputs:
            coverage = report["coverage"][:20]
            warnings = report["warnings"][:20]
            if len(report["coverage"]) > 20:
                warnings.append(f"Coverage lists 20 of {len(report['coverage'])} sources; metrics include every source.")
            reports.append({"workflow_id": report["workflow_id"], "summary": report["summary"][:1000],
                            "metrics": report["metrics"], "coverage": coverage, "warnings": warnings,
                            "created_at": report.get("created_at"), "filters": report.get("filters", {}),
                            "source_selection": report.get("source_selection", {})})
        context = {"scope": "saved_report" if report_id else "current_snapshots", "reports": reports}
        if report_id:
            context["scope_note"] = "Raport istoric salvat. Indicatorii sunt cei de la generare și nu sunt recalculați din datele curente."
        if len(json.dumps(context, ensure_ascii=False)) > 45_000:
            raise BusinessError("context_too_large", "Business aggregates exceed the assistant context limit", 413)
        return context, self.store.profile()["local_only"]

    async def ask(self, question: str, report_id: str | None = None) -> dict:
        from agents.core.business.assistant import BusinessAIError, answer_question

        try:
            context, local_only = await asyncio.to_thread(self._question_context, report_id)
        except BusinessError:
            raise
        except Exception:
            raise BusinessError("report_failed", "Current business reports are unavailable", 502) from None
        try:
            return await answer_question(question, context, local_only)
        except BusinessAIError as exc:
            raise BusinessError("assistant_unavailable", str(exc), 503) from None
        except Exception:
            raise BusinessError("assistant_unavailable", "Business assistant is unavailable", 503) from None
