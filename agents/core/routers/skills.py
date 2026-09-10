"""Skills, sandbox, and skill-marketplace endpoints — extracted from web.py (CLN-3).

Covers the skills surface: `/skills` listing, `/skills/import` + `/skills/imported`,
the `/sandbox/*` execution endpoints, and the `/api/skills/marketplace/*`
agent-marketplace endpoints (H5.8 / H12.12).

`skills_import` and `sandbox_execute` gate on web.py's `DEV_MODE` flag. They read
it via `app_state.dev_mode()` (CLN-3 unblock B), which resolves `web.DEV_MODE` at
request time through `sys.modules` — so the skills test suite's
`monkeypatch.setattr(web, "DEV_MODE", ...)` is still observed and no test changes.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard, admin_guard
from agents.core.routers._component import component_unavailable

from agents.core.web_helpers import error_json, logger
from agents.core import app_state
from agents.core.app_state import get_orch
from agents.core.skills.marketplace import BrokerOnlyInstall


router = APIRouter(tags=["skills"])


@router.get("/skills")
async def list_skills():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    result = {}
    for name, skill in orch.skills.skills.items():
        result[name] = {
            "name": skill.name,
            "version": skill.version,
            "description": skill.description,
            "agents": skill.agents,
            "commands": skill.commands_meta,
        }
    return {"skills": result}


@router.get("/sandbox/status")
async def sandbox_status():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    # DRA-08 — disclose whether the governed Tool-RPC pipeline mode is usable and
    # exactly which tools a script may reach. Honest and additive: `available`
    # false + an empty list means `tools: true` will be refused, not downgraded.
    server = getattr(orch, "tool_rpc", None)
    return {
        "available": orch.sandbox._has_docker,
        "docker_image": orch.sandbox.docker_image,
        "timeout": orch.sandbox.timeout,
        # HF-6 — expose isolation posture so an active host-exec fallback is visible.
        **orch.sandbox.security_status(),
        "tool_rpc": {
            "available": server is not None,
            "tools": server.tools() if server is not None else [],
        },
    }


# ── K3: the owner's window onto their own session kernels ────────────────────
#
# Two additive routes over what K2 already owns. Both derive the kernel key from the
# *request's* own authority — the same K0 binding `execute_code` uses — so neither
# takes a session id, a principal or a kernel token as input. That is the whole
# access-control story: there is no argument with which to name someone else's
# interpreter, so "another session cannot inspect or reset this one" is a property of
# the shape rather than a check that could be forgotten.
#
# What they publish is deliberately thin: the mode and why, and for the caller's own
# kernel its age, its cell count and whether it is alive. Never a cell's source, never
# a variable, never the reply token that frames a kernel's replies.

SESSIONS_OFF = "sessions_disabled"
CODE_OFF = "code_execution_disabled"
NOT_COMPOSED = "kernels_not_composed"
NOT_ISOLATED = "sandbox_not_isolated"
SESSION_MODE = "session"
ONE_SHOT_MODE = "one_shot"


def _kernel_mode(orch, get_setting) -> tuple[object, str, str]:
    """The manager, the mode a cell would run in, and the reason it is not `session`.

    Read in the order an owner would ask: is code execution on at all, are sessions
    on, is a manager composed, and is the backend really isolated. The first honest
    "no" wins, so the reason names the switch to change rather than the symptom.
    """
    from agents.core.code_tools import SESSION_SETTING, SETTING

    if get_setting is None:
        return None, ONE_SHOT_MODE, CODE_OFF
    if get_setting(SETTING, False) is not True:
        return None, ONE_SHOT_MODE, CODE_OFF
    if get_setting(SESSION_SETTING, False) is not True:
        return None, ONE_SHOT_MODE, SESSIONS_OFF
    kernels = getattr(orch, "session_kernels", None)
    if kernels is None:
        # Composed to None: the image is missing or unpinned. The coordinator logged
        # which; the route says the honest short version.
        return None, ONE_SHOT_MODE, NOT_COMPOSED
    sandbox = getattr(orch, "sandbox", None)
    try:
        isolated = bool(sandbox.is_isolated())
    except Exception:
        isolated = False
    if not isolated:
        return kernels, ONE_SHOT_MODE, NOT_ISOLATED
    return kernels, SESSION_MODE, ""


def _caller_key(orch, request):
    """This request's kernel key, or None when no authority can be bound.

    Built from the same invocation `execute_code` binds, so the key a route resolves
    and the key a cell runs under cannot drift apart.
    """
    from agents.core.session_kernels import KernelKey

    server = getattr(orch, "tool_rpc", None)
    if server is None:
        return None
    invocation = _sandbox_invocation(orch, server, getattr(orch, "get_setting", None), request)
    if invocation is None:
        return None
    return KernelKey.from_invocation(invocation)


@router.get("/sandbox/kernels", dependencies=[Depends(user_guard)])
async def sandbox_kernels(request: Request):
    """Report the mode, and the caller's own kernel if they have one."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    get_setting = getattr(orch, "get_setting", None)
    kernels, mode, reason = _kernel_mode(orch, get_setting)
    body = {"mode": mode, "reason": reason, "kernel": None}
    if kernels is None:
        return body
    key = _caller_key(orch, request)
    if key is None:
        # No authority resolved: report the mode, claim no kernel. Returning someone
        # else's row here would be the exact leak these routes exist to avoid.
        return body
    body["kernel"] = next(
        (row for row in kernels.status() if row.get("token") == key.token), None)
    return body


@router.post("/sandbox/kernels/reset", dependencies=[Depends(user_guard)])
async def sandbox_kernel_reset(request: Request):
    """Destroy the caller's own kernel. Says whether there was one to destroy."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    kernels, mode, reason = _kernel_mode(orch, getattr(orch, "get_setting", None))
    if kernels is None:
        return {"reset": False, "mode": mode, "reason": reason}
    server = getattr(orch, "tool_rpc", None)
    invocation = _sandbox_invocation(
        orch, server, getattr(orch, "get_setting", None), request) if server else None
    if invocation is None:
        return {"reset": False, "mode": mode, "reason": "authority_unavailable"}
    # `reset` answers "was there state to lose", not "did the call succeed". False
    # here is a successful call over an empty seat, and the panel says so — a reset
    # that reads as success when nothing existed teaches an owner to distrust it.
    from agents.core.session_kernels import KernelKey

    destroyed = await kernels.reset(invocation)
    return {"reset": bool(destroyed), "mode": mode, "reason": reason,
            "kernel_token": KernelKey.from_invocation(invocation).token}


def _sandbox_invocation(orch, server, get_setting, request):
    """Resolve one sandbox run's authority. Never raises: a failure binds nothing,
    and a runtime without an invocation refuses every tool call it is asked for.

    The principal comes from *this request*, resolved the same way `/chat` resolves
    it. That matters more than it looks: nothing binds a turn principal on this
    route, so reading the ambient one would make every sandbox run resolve as the
    `internal`/`system` posture — and the profile would then withhold every gated
    tool, quietly withdrawing the documented "a gated call enqueues an approval"
    behaviour from the owner as well as from a guest. Binding what the door already
    authenticated keeps the owner's reach and narrows a guest's, which is the point.
    """
    from agents.core import sandbox_invocation
    from agents.core.action_origin import current_action_origin

    try:
        config = getattr(orch, "config", None)
        agents = getattr(config, "agents", None) or {}
        agent = getattr(server, "agent", "jarvis")
        invocation, _decision = sandbox_invocation.bind(
            tools=server.tools(),
            agent=agent,
            principal=_request_principal(request),
            origin=current_action_origin(),
            session_id=str(getattr(orch, "session_id", "") or ""),
            settings=(get_setting or (lambda key, default: default)),
            agent_patterns=getattr(agents.get(agent), "tools", None),
        )
        return invocation
    except Exception:
        logger.warning("sandbox invocation binding failed; tool calls will be refused",
                       exc_info=True)
        return None


def _request_principal(request):
    """Who is at this door, by the same rule the chat route uses."""
    from agents import web

    resolver = getattr(web, "_web_principal", None)
    if resolver is None or request is None:
        return None
    try:
        return resolver(request)
    except Exception:
        # An unreadable request is nobody in particular: the guest posture, never
        # the owner's.
        from agents.core.commands import Principal

        return Principal(channel="web", sender=None, admin=False)


class SandboxExecuteBody(BaseModel):
    code: str = Field("", max_length=32768)
    language: str = "python"
    # DRA-08 — opt in to the governed Tool-RPC pipeline (Python only). Default
    # False keeps the existing plain-sandbox path byte-identical for every caller.
    tools: bool = False


@router.post("/sandbox/execute", dependencies=[Depends(user_guard)])
async def sandbox_execute(body: SandboxExecuteBody, request: Request):
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not app_state.dev_mode():
        return JSONResponse({"error": "sandbox disabled — set DEV_MODE=1 to enable"}, status_code=403)
    code = body.code
    language = body.language
    if body.tools:
        # DRA-08 phase 3 — run the script through ToolRPCSandboxRuntime so
        # `jarvis_tool_call(...)` inside it is serviced on the host by
        # ToolRPCServer.handle(): allowlist, risk gating (gated tools return
        # `approval_required` and enqueue an ask-tier task), Action-Kernel
        # mediation and secret scrubbing all still apply.
        if language != "python":
            # The file-RPC shim is a Python shim; never silently downgrade a
            # tools=true request into an ungoverned shell run.
            return JSONResponse(
                {"error": "tool_rpc_pipeline_python_only"}, status_code=422)
        server = getattr(orch, "tool_rpc", None)
        if server is None:
            # No governed server → refuse. Falling back to execute_python would
            # run the very same code ungoverned, which is what this wiring exists
            # to prevent.
            return component_unavailable("tool-rpc unavailable")
        from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime
        get_setting = getattr(orch, "get_setting", None)
        try:
            max_tool_calls = int(
                get_setting("security.sandbox_max_tool_calls", 50) if get_setting else 50)
        except (TypeError, ValueError):
            max_tool_calls = 50
        # K0 — bind this run's authority from what the host already knows about the
        # caller, before a line of the script runs. The body cannot name an identity
        # or a tool set: both are resolved here, and the same profile that narrows a
        # model turn narrows the script's reach.
        invocation = _sandbox_invocation(orch, server, get_setting, request)
        run = await ToolRPCSandboxRuntime(
            server, orch.sandbox, invocation=invocation, max_tool_calls=max_tool_calls,
        ).run_python(code)
        return {
            "stdout": run.result.stdout,
            "stderr": run.result.stderr,
            "exit_code": run.result.exit_code,
            "duration": run.result.duration,
            "success": run.result.success,
            "tool_calls": run.tool_calls,
            "timed_out": run.timed_out,
        }
    if language == "python":
        result = await orch.sandbox.execute_python(code)
    else:
        result = await orch.sandbox.execute_shell(code)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration": result.duration,
        "success": result.success,
    }


@router.post("/skills/import", dependencies=[Depends(user_guard)])
async def skills_import(req: Request):
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not app_state.dev_mode():
        return JSONResponse({"error": "skill import disabled — set DEV_MODE=1 to enable"}, status_code=403)
    body = await req.json()
    source = body.get("source", "hermes")
    skill_name = body.get("skill", "")
    if not skill_name:
        return JSONResponse({"error": "skill name required"}, status_code=400)
    if source == "hermes":
        ok = await orch.skill_importer.import_from_hermes(skill_name)
    elif source == "openclaw":
        ok = await orch.skill_importer.import_from_openclaw(skill_name)
    else:
        ok = await orch.skill_importer.import_from_github(source, skill_name)
    if ok:
        orch.skills.discover()
        return {"ok": True, "source": source, "skill": skill_name}
    return JSONResponse({"ok": False, "error": f"Skill '{skill_name}' not found in {source}"}, status_code=404)


@router.get("/skills/imported")
async def skills_imported():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {"imported": orch.skill_importer.list_imported()}


# ── Agent Marketplace Endpoints (H5.8) ───────────────────────────

class PublishSkillBody(BaseModel):
    name: str


class InstallSkillBody(BaseModel):
    name: str


class InstallZipBody(BaseModel):
    zip_base64: str


@router.get("/api/skills/marketplace", dependencies=[Depends(admin_guard)])
async def marketplace_list():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        skills = orch.marketplace.list_skills()
        return {"skills": skills}
    except Exception:
        logger.exception("Failed to list marketplace skills")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


@router.get("/api/skills/marketplace/history", dependencies=[Depends(admin_guard)])
async def marketplace_history(name: str | None = None):
    """0.58 read surface: the version-history ledger (publish/install/uninstall
    events + stats, and current/rollback-target for a given ``name``). Reports
    ``enabled: False`` when no ledger is attached (JARVIS_SKILL_HISTORY unset)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        return orch.marketplace.history_view(name)
    except Exception:
        logger.exception("Failed to read marketplace history")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


@router.post("/api/skills/marketplace/{name}/rollback", dependencies=[Depends(admin_guard)])
async def marketplace_rollback(name: str):
    """0.58 — roll a marketplace skill's package back to its most recent prior version
    (reversible; the current package is archived first). The restored package replaces
    the registry row but is not installed — ``install_skill`` re-deploys it through the
    moderation gate. 422 when there's nothing to restore."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        result = orch.marketplace.restore_prior_package(name)
        return JSONResponse(result, status_code=200 if result.get("ok") else 422)
    except Exception:
        logger.exception("Failed to roll back marketplace skill")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


@router.post("/api/skills/marketplace/publish", dependencies=[Depends(admin_guard)])
async def marketplace_publish(body: PublishSkillBody):
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        res = orch.marketplace.publish_skill(body.name)
        return {"ok": True, "published": res}
    except PermissionError:
        logger.warning("Skill publish blocked by supply-chain contract")
        return JSONResponse({"error": f"skill '{body.name}' blocked by supply-chain contract"},
                            status_code=403)
    except FileNotFoundError as e:
        return error_json(e, 404, "skill not found")
    except Exception:
        logger.exception("Failed to publish skill")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


@router.post("/api/skills/marketplace/install", dependencies=[Depends(admin_guard)])
async def marketplace_install(body: InstallSkillBody):
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        ok = orch.marketplace.install_skill(body.name)
        if ok:
            orch.skills.discover()
            return {"ok": True, "installed": body.name}
        return JSONResponse({"error": f"Failed to install skill '{body.name}'"}, status_code=500)
    except BrokerOnlyInstall:
        # Not a moderation verdict: an acquired package's code never lands in
        # skills/, so this endpoint is simply the wrong path for it. Reported
        # separately because "blocked by moderation/signature policy" sent
        # operators to moderate a package that moderation could never unblock.
        logger.warning("Skill install refused: acquired packages deploy via the sandbox broker")
        return JSONResponse(
            {
                "error": (
                    f"skill '{body.name}' is an acquired package — it deploys through "
                    "the sandbox broker, not this endpoint"
                ),
                "install_path": "sandbox-broker",
            },
            status_code=403,
        )
    except PermissionError:
        # Blocked by the moderation/signature gate (H12.12). Don't log the
        # caller-supplied name (log-injection); the response echoes it instead.
        logger.warning("Skill install blocked by moderation/signature policy")
        return JSONResponse(
            {"error": f"skill '{body.name}' blocked by moderation/signature policy"},
            status_code=403,
        )
    except ValueError:
        # Observed in a real session as three POSTs → 404 in two seconds: the
        # name reached the endpoint but is in neither registry table.
        logger.warning("Skill install failed: no such skill in the marketplace registry")
        return JSONResponse({"error": f"skill '{body.name}' not found in registry"}, status_code=404)
    except Exception:
        logger.exception("Failed to install skill")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


@router.post("/api/skills/marketplace/install-zip", dependencies=[Depends(admin_guard)])
async def marketplace_install_zip(body: InstallZipBody):
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        import base64
        zip_bytes = base64.b64decode(body.zip_base64)
        ok = orch.marketplace.install_from_zip(zip_bytes)
        if ok:
            orch.skills.discover()
            return {"ok": True}
        return JSONResponse({"error": "Failed to install skill from zip"}, status_code=500)
    except (PermissionError, ValueError):
        # Rejected by the zip-slip guard or the signature gate (H12.12).
        logger.warning("Skill zip install rejected (unsafe path or signature policy)")
        return JSONResponse(
            {"error": "skill package rejected (unsafe path or signature policy)"},
            status_code=400,
        )
    except Exception:
        logger.exception("Failed to install skill from zip")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


class ReviewSkillBody(BaseModel):
    name: str
    status: str = Field(..., pattern="^(pending|approved|rejected)$")


@router.post("/api/skills/marketplace/review", dependencies=[Depends(admin_guard)])
async def marketplace_review(body: ReviewSkillBody):
    """Moderate a marketplace skill (H12.12): set review status to approved/rejected/pending."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        orch.marketplace.set_review_status(body.name, body.status)
        return {"ok": True, "name": body.name, "review_status": body.status}
    except ValueError:
        return JSONResponse({"error": f"skill '{body.name}' not found in registry"}, status_code=404)
    except Exception:
        logger.exception("Failed to set skill review status")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


class UninstallSkillBody(BaseModel):
    name: str
    purge: bool = False


@router.post("/api/skills/marketplace/uninstall", dependencies=[Depends(admin_guard)])
async def marketplace_uninstall(body: UninstallSkillBody):
    """0.58 — uninstall an installed skill (remove its directory). With `purge`,
    also drop the marketplace registry row. The package is retained by default so
    `install` can restore it."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        # Resolve the on-disk dir up front so we can drop it from the live loader
        # by path (the loader keys by manifest title, which may differ from the dir).
        removed_dir = (orch.marketplace.skills_dir / body.name).resolve()
        # The registry row is filed under the SKILL.md title, not the folder name, and
        # that title is only readable while the directory still exists — so resolve it
        # (and whether a row is actually there) BEFORE the uninstall.
        registry_key = orch.marketplace.registry_key(body.name)
        was_registered = bool(body.purge) and orch.marketplace.is_registered(registry_key)
        removed = orch.marketplace.uninstall_skill(body.name, purge=body.purge)
        # OBSERVE the outcome. This used to return `body.purge` — the caller's own
        # request flag echoed back — so the HUD reported "registry row purged" even when
        # the delete matched nothing and the published package survived, blob and all.
        purged = was_registered and not orch.marketplace.is_registered(registry_key)
    except PermissionError:
        logger.warning("Skill uninstall blocked by supply-chain contract")
        return JSONResponse({"error": f"skill '{body.name}' blocked by supply-chain contract"},
                            status_code=403)
    except ValueError:
        return JSONResponse({"error": f"invalid skill name '{body.name}'"}, status_code=400)
    except Exception:
        logger.exception("Failed to uninstall skill")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)
    if not removed and not body.purge:
        return JSONResponse({"error": f"skill '{body.name}' is not installed"}, status_code=404)
    if removed:
        # Forget the skill in the live loader (match by on-disk path, not name).
        import contextlib
        from pathlib import Path
        for key in [k for k, s in list(orch.skills.skills.items())
                    if Path(getattr(s, "path", "")).resolve() == removed_dir]:
            with contextlib.suppress(Exception):
                del orch.skills.skills[key]
        # DRA-54 — drop the owner approval bound to that path immediately, so a
        # re-created (byte-identical) tree at the same path cannot inherit it.
        with contextlib.suppress(Exception):
            orch.skills.revoke_approval(removed_dir)
    return {"ok": True, "uninstalled": body.name, "removed": removed, "purged": purged}


_PENDING_REASON = "pending review (CDX-8 quarantine)"


@router.get("/api/skills/pending", dependencies=[Depends(admin_guard)])
async def list_pending_skills():
    """CDX-8: auto-generated skills awaiting owner review — quarantined, NOT yet executable."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    pending = [
        {"name": name, "description": getattr(s, "description", ""), "agents": getattr(s, "agents", [])}
        for name, s in orch.skills.skills.items()
        if getattr(s, "signature_reason", "") == _PENDING_REASON
    ]
    return JSONResponse({"pending": pending, "count": len(pending)})


@router.post("/api/skills/{name}/approve", dependencies=[Depends(admin_guard)])
async def approve_generated_skill(name: str):
    """CDX-8: owner-approve a quarantined auto-generated skill — sign + activate it. Only an
    admin can promote LLM-authored code from pending to executable."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if orch.skills.approve_generated_skill(name):
        return {"approved": True, "skill": name}
    return JSONResponse({"error": f"no pending skill '{name}'"}, status_code=404)
