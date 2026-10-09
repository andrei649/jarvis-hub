"""Owner CLI for Bitwarden and 1Password sources.

Command shapes adapted from Hermes hermes_cli/{secrets_cli,
onepassword_secrets_cli}.py at 59b2aeef6c7a (MIT). Nerva stores bootstrap
tokens in SecretStore and never exports resolved values to process environment.
"""

from __future__ import annotations

import argparse
import getpass
import subprocess  # nosec B404 - fixed helper argv, no shell; credentials use a narrow child environment
import sys
from typing import TYPE_CHECKING

from agents.core.secrets import SecretStore, SecretStoreError

if TYPE_CHECKING:
    from agents.core.security.secret_sources import ExternalSecretSources

_REGIONS = {"us": "", "eu": "https://vault.bitwarden.eu"}


def __getattr__(name: str):
    """Keep the existing injectable source class without loading it for CLI help."""
    if name == "ExternalSecretSources":
        from agents.core.security.secret_sources import ExternalSecretSources

        return ExternalSecretSources
    raise AttributeError(name)


def register_parser(subparsers) -> None:
    parent = subparsers.add_parser("secrets", help="manage external password-manager sources")
    providers = parent.add_subparsers(dest="provider", required=True)
    for provider, aliases in (("bitwarden", ("bw",)), ("onepassword", ("op", "1password"))):
        p = providers.add_parser(provider, aliases=list(aliases))
        verbs = p.add_subparsers(dest="action", required=True)
        setup = verbs.add_parser("setup", help="configure and enable this source")
        setup.add_argument("--binary-path", default="", help="existing helper executable")
        if provider == "bitwarden":
            setup.add_argument("--project-id", required=True)
            setup.add_argument("--region", choices=("us", "eu", "self-hosted"), default="us")
            setup.add_argument("--server-url", default="", help="HTTPS URL for self-hosted region")
        else:
            setup.add_argument("--account", default="")
        verbs.add_parser("status", help="local configuration and helper availability")
        token = verbs.add_parser("token", help="store or rotate an encrypted bootstrap token")
        token.add_argument("--token-stdin", action="store_true", help="read one line from stdin")
        token.add_argument("--no-verify", action="store_true", help="store without a live identity probe")
        sync = verbs.add_parser("sync", help="fetch now and show resolved names only")
        sync.add_argument("--fresh", action="store_true", help="skip the in-memory cache")
        verbs.add_parser("disable", help="disable source without removing references or token")
        if provider == "bitwarden":
            verbs.add_parser("install", help="explicitly install pinned bws helper")
        else:
            mapping = verbs.add_parser("set", help="map ENV_VAR to an op:// reference")
            mapping.add_argument("env_var")
            mapping.add_argument("reference")
            remove = verbs.add_parser("remove", help="remove an ENV_VAR reference mapping")
            remove.add_argument("env_var")


def cmd_secrets(ns: argparse.Namespace, ctx, *, store: SecretStore | None = None,
                sources: ExternalSecretSources | None = None) -> int:
    """Offline command handler. Root wires this to the main CLI dispatch table."""
    from agents.core.security.secret_sources import onepassword
    from agents.core.security.secret_sources.base import executable, valid_env_name

    source_type = globals().get("ExternalSecretSources")
    if source_type is None:
        from agents.core.security.secret_sources import ExternalSecretSources as source_type

    out, err = ctx.out, ctx.err
    provider = "bitwarden" if ns.provider in ("bitwarden", "bw") else "onepassword"
    try:
        source = sources or source_type(store or SecretStore())
        cfg = source.configuration(provider)
        action = ns.action
        if action == "status":
            binary = executable(str(cfg.get("binary_path") or ""), "bws" if provider == "bitwarden" else "op")
            out.write(f"{provider}: {'enabled' if cfg.get('enabled') else 'disabled'}\n")
            out.write(f"token: {'stored' if source.token_present(provider) else 'absent'}\n")
            out.write(f"helper: {'available' if binary else 'missing'}\n")
            if provider == "bitwarden":
                out.write(f"project: {cfg.get('project_id') or '(unset)'}\n")
                out.write(f"region: {cfg.get('server_url') or 'US default'}\n")
            else:
                out.write(f"references: {len(cfg.get('env') or {})}\n")
                for name in sorted(cfg.get("env") or {}):
                    out.write(f"  {name}\n")
            return 0
        if action == "setup":
            binary = executable(ns.binary_path.strip(), "bws" if provider == "bitwarden" else "op")
            if binary is None:
                err.write("secret-manager helper is missing; install it before setup\n")
                return 1
            if provider == "bitwarden":
                region = ns.region
                if region == "self-hosted" and not ns.server_url:
                    err.write("self-hosted region requires --server-url\n")
                    return 2
                if region != "self-hosted" and ns.server_url:
                    err.write("--server-url requires --region self-hosted\n")
                    return 2
                cfg.update(enabled=True, project_id=ns.project_id.strip(),
                           server_url=ns.server_url.strip() if region == "self-hosted" else _REGIONS[region],
                           binary_path=ns.binary_path.strip() or binary, cache_ttl_seconds=60)
                if not cfg["project_id"]:
                    err.write("project ID is required\n")
                    return 2
            else:
                cfg.update(enabled=True, account=ns.account.strip(), binary_path=ns.binary_path.strip() or binary,
                           env=cfg.get("env") or {}, cache_ttl_seconds=60)
            source.configure(provider, cfg)
            out.write(f"{provider} enabled; use token to store a bootstrap credential\n")
            return 0
        if action == "token":
            if ns.token_stdin:
                token = ctx.inp.readline().rstrip("\r\n")
            elif sys.stdin.isatty():
                token = getpass.getpass(f"{provider} token: ")
            else:
                err.write("token requires an owner TTY or --token-stdin\n")
                return 2
            if not token:
                err.write("empty token\n")
                return 2
            if not ns.no_verify and not _verify_token(source, provider, cfg, token):
                err.write("token verification failed; previous token preserved\n")
                return 1
            source.set_token(provider, token)
            out.write("encrypted token stored\n")
            return 0
        if action == "disable":
            cfg["enabled"] = False
            source.configure(provider, cfg)
            out.write(f"{provider} disabled\n")
            return 0
        if action == "set" and provider == "onepassword":
            if not valid_env_name(ns.env_var) or not onepassword.valid_reference(ns.reference):
                err.write("expected ENV_VAR and op://vault/item/field reference\n")
                return 2
            refs = dict(cfg.get("env") or {})
            refs[ns.env_var] = ns.reference.strip()
            cfg["env"] = refs
            source.configure(provider, cfg)
            out.write(f"{ns.env_var} mapped\n")
            return 0
        if action == "remove" and provider == "onepassword":
            refs = dict(cfg.get("env") or {})
            if ns.env_var not in refs:
                err.write("reference not found\n")
                return 1
            del refs[ns.env_var]
            cfg["env"] = refs
            source.configure(provider, cfg)
            out.write(f"{ns.env_var} unmapped\n")
            return 0
        if action == "sync":
            if ns.fresh:
                source.clear_cache()
            result = source.fetch_report(provider)
            if result.error:
                err.write(f"{provider} sync failed ({result.error_kind or 'unavailable'})\n")
                return 1
            for name in sorted(result.secrets):
                out.write(f"{name}\n")
            out.write(f"resolved: {len(result.secrets)}\n")
            return 0
        if action == "install" and provider == "bitwarden":
            from agents.core.security.secret_sources.install import install_bws
            binary = install_bws()
            out.write(f"bws installed: {binary}\n")
            return 0
        return 2
    except (ValueError, SecretStoreError) as exc:
        err.write(f"secret source command failed: {type(exc).__name__}\n")
        return 1
    except (OSError, RuntimeError) as exc:
        err.write(f"secret source command unavailable: {type(exc).__name__}\n")
        return 1


def _verify_token(source: ExternalSecretSources, provider: str, cfg: dict, token: str) -> bool:
    """Probe candidate in an isolated child; a failed rotation leaves store intact."""
    from agents.core.security.secret_sources.base import executable, run_helper

    binary = executable(str(cfg.get("binary_path") or ""), "bws" if provider == "bitwarden" else "op")
    if not binary:
        return False
    if provider == "bitwarden":
        argv = [binary, "project", "list", "--output", "json"]
        env_name = "BWS_ACCESS_TOKEN"
    else:
        argv = [binary, "whoami"]
        if cfg.get("account"):
            argv.extend(("--account", str(cfg["account"])))
        env_name = "OP_SERVICE_ACCOUNT_TOKEN"
    try:
        proc = run_helper(source.runner, argv, credential=token, credential_name=env_name,
                          timeout=cfg.get("timeout_seconds", 10),
                          extra_env={"BWS_SERVER_URL": str(cfg["server_url"])}
                          if provider == "bitwarden" and cfg.get("server_url") else None)
        return proc.returncode == 0
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return False
