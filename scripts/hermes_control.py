#!/usr/bin/env python3
"""Operate the managed Hermes runtime through the authenticated local Hub API."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_RESPONSE_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 128 * 1024


class OperatorError(Exception):
    def __init__(self, message: str, status: int | None = None,
                 task_id: int | None = None, disposition: str | None = None):
        super().__init__(message)
        self.status = status
        self.task_id = task_id
        self.disposition = disposition


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise OperatorError("invalid Hub URL") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or port == 0):
        raise OperatorError("Hub URL must be an HTTP(S) origin without credentials or path")
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname == "localhost"
        if not loopback:
            raise OperatorError("plain HTTP requires a loopback Hub address")
    return value.rstrip("/")


def read_params(filename: str | None) -> dict:
    if filename is None:
        return {}
    try:
        if filename == "-":
            raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        else:
            with Path(filename).open("rb") as source:
                raw = source.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise OperatorError("RPC parameters exceed the 128 KiB Hub request limit")
        params = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("RPC parameters must be valid JSON from a readable file or stdin") from exc
    if not isinstance(params, dict):
        raise OperatorError("RPC parameters must be a JSON object")
    return params


def task_id(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("task ID must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("task ID must be a positive integer")
    return parsed


def redact(value: object, token: str) -> object:
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, dict):
        return {redact(key, token): redact(item, token) for key, item in value.items()}
    return value


def api_call(origin: str, token: str, path: str, body: dict | None = None) -> object:
    origin = base_url(origin)
    headers = {"Accept": "application/json", "X-Admin-Token": token}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        try:
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise OperatorError("RPC parameters must be valid JSON") from exc
        if len(payload) > MAX_REQUEST_BYTES:
            raise OperatorError("RPC parameters exceed the 128 KiB Hub request limit")
    request = Request(origin + path, data=payload, headers=headers,
                      method="POST" if body is not None else "GET")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with opener.open(request, timeout=45) as response:  # nosec B310 - validated HTTP loopback or explicit HTTPS origin; redirects and proxies disabled
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise OperatorError("Hub redirect refused") from exc
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        task = None
        disposition = None
        try:
            error = json.loads(raw)
            detail = error.get("detail", error.get("error", "Hub request failed"))
            if isinstance(detail, dict):
                if type(detail.get("task_id")) is int and detail["task_id"] >= 0:
                    task = detail["task_id"]
                if isinstance(detail.get("disposition"), str):
                    disposition = detail["disposition"][:64].replace(token, "[redacted]")
                detail = detail.get("error", detail)
            reason = str(detail)
        except (UnicodeError, ValueError, AttributeError):
            reason = "Hub request failed"
        raise OperatorError(reason.replace(token, "[redacted]"), status=exc.code,
                            task_id=task, disposition=disposition) from exc
    except URLError as exc:
        raise OperatorError("Hub connection failed") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise OperatorError("Hub response exceeds size limit")
    try:
        return json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise OperatorError("Hub response was not JSON") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080",
                        help="Hub origin (default: http://127.0.0.1:8080); HTTPS may be remote")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "start", "stop", "catalog", "approvals"):
        commands.add_parser(name)
    rpc = commands.add_parser("rpc")
    rpc.add_argument("method", help="Hermes catalog method name")
    rpc.add_argument("--params-file", metavar="PATH", help="JSON object file, or - for stdin")
    for name in ("approve", "deny"):
        commands.add_parser(name).add_argument("task_id", type=task_id)
    args = parser.parse_args(argv)
    try:
        origin = base_url(args.base_url)
        token = os.environ.get("JARVIS_ADMIN_TOKEN", "").strip()
        if not token:
            raise OperatorError("set JARVIS_ADMIN_TOKEN in the environment")
        if args.command == "rpc":
            result = api_call(origin, token, "/api/hermes/rpc",
                              {"method": args.method, "params": read_params(args.params_file)})
        elif args.command in {"approve", "deny"}:
            result = api_call(origin, token,
                              f"/api/hermes/approvals/{args.task_id}/decision",
                              {"approved": args.command == "approve"})
        elif args.command in {"start", "stop"}:
            result = api_call(origin, token, f"/api/hermes/{args.command}", {})
        else:
            result = api_call(origin, token, f"/api/hermes/{args.command}")
        print(json.dumps(redact(result, token), ensure_ascii=False, indent=2))
        return 0
    except OperatorError as exc:
        message = {"error": str(exc)}
        if exc.status is not None:
            message["status"] = exc.status
        if exc.task_id is not None:
            message["task_id"] = exc.task_id
        if exc.disposition is not None:
            message["disposition"] = exc.disposition
        print(json.dumps(message, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
