"""G20 skills distribution, H342: the values a skill's declared environment variables need.

``/api/skills/setup/{name}`` says which variables a skill declares, which are set (and
where: stored for this skill, or the hub's environment) and which are missing. A value
goes in through ``PUT`` and is never sent back, not even in part
(``skills/skill_secrets.py``); it is stored encrypted and handed only to that skill's own
code. Validation errors answer without FastAPI's detail, which would repeat the input.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from agents.core.app_state import get_orch
from agents.core.web_helpers import nocache_json

from ._deps import admin_guard

logger = logging.getLogger("jarvis.routers.skill_setup")

SKILL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
VAR_PATTERN = r"^[A-Z_][A-Z0-9_]{0,127}$"


class _QuietRoute(APIRoute):
    """A validation error is answered without FastAPI's detail, which repeats the input."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return nocache_json({"error": "invalid_request"}, status_code=422)

        return guarded


router = APIRouter(route_class=_QuietRoute, tags=["skills"])


async def same_origin_write(request: Request) -> None:
    """A write must come from this origin and, for a POST/PUT, be JSON (forces CORS's check)."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="a skills change must come from this origin")
    if request.method in ("POST", "PUT"):
        kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if kind != "application/json":
            raise HTTPException(status_code=415, detail="expected application/json")


WRITE_GUARDS = [Depends(admin_guard), Depends(same_origin_write)]


def _unavailable() -> JSONResponse:
    return nocache_json({"error": "not initialized"}, status_code=503)


def _skill(orch, name: str):
    loader = getattr(orch, "skills", None)
    skills = getattr(loader, "skills", None)
    return skills.get(name) if isinstance(skills, dict) else None


def _audit(orch, action: str, why: str, metadata: dict) -> None:
    audit = getattr(orch, "intent_log", None)
    if callable(getattr(audit, "record", None)):
        try:
            audit.record(actor="owner", action=action, why=why, cause="skills.setup", metadata=metadata)
        except Exception:  # noqa: BLE001 — a projection
            logger.warning("skill setup intent projection failed", exc_info=True)


def _setup_view(skill) -> dict:
    from agents.core.skills import skill_secrets

    rows = skill_secrets.requirements(skill)
    missing = [r["name"] for r in rows if not r["optional"] and not r["set"]]
    return {"skill": skill.name, "requirements": rows, "missing": missing, "ready": not missing}


# ── H342: a skill's setup values ────────────────────────────────────────────────

@router.get("/api/skills/setup/{name}", dependencies=[Depends(admin_guard)])
async def skill_setup(name: str = Path(pattern=SKILL_PATTERN)):
    orch = get_orch()
    if not orch:
        return _unavailable()
    skill = _skill(orch, name)
    if skill is None:
        return nocache_json({"error": "unknown_skill"}, status_code=404)
    return nocache_json(await asyncio.to_thread(_setup_view, skill))


class SetupValueBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: SecretStr = Field(min_length=1, max_length=4096)


@router.put("/api/skills/setup/{name}/{var}", dependencies=WRITE_GUARDS)
async def skill_setup_put(body: SetupValueBody, name: str = Path(pattern=SKILL_PATTERN),
                          var: str = Path(pattern=VAR_PATTERN)):
    from agents.core.skills import skill_secrets

    orch = get_orch()
    if not orch:
        return _unavailable()
    skill = _skill(orch, name)
    if skill is None:
        return nocache_json({"error": "unknown_skill"}, status_code=404)
    try:
        await asyncio.to_thread(skill_secrets.set_value, skill, var, body.value.get_secret_value())
    except skill_secrets.SetupRefused as exc:
        status = 422 if exc.reason == "invalid_value" else 403 if exc.reason == "reserved_name" else 404
        return nocache_json({"error": exc.reason}, status_code=status)
    except Exception:  # noqa: BLE001 — the store: never a value in a log line
        logger.warning("a skill setup value could not be stored (skill=%s, name=%s)", name, var)
        return nocache_json({"error": "store_unavailable"}, status_code=503)
    _audit(orch, "skill.setup.set", f"{var} set for skill {name} (stored encrypted; value not logged)",
           {"skill": name, "name": var})
    return nocache_json({"ok": True, **await asyncio.to_thread(_setup_view, skill)})


@router.delete("/api/skills/setup/{name}/{var}", dependencies=WRITE_GUARDS)
async def skill_setup_delete(name: str = Path(pattern=SKILL_PATTERN), var: str = Path(pattern=VAR_PATTERN)):
    from agents.core.skills import skill_secrets

    orch = get_orch()
    if not orch:
        return _unavailable()
    skill = _skill(orch, name)
    if skill is None:
        return nocache_json({"error": "unknown_skill"}, status_code=404)
    try:
        result = await asyncio.to_thread(skill_secrets.clear_value, skill, var)
    except skill_secrets.SetupRefused as exc:
        return nocache_json({"error": exc.reason}, status_code=422)
    except Exception:  # noqa: BLE001
        logger.warning("a skill setup value could not be removed (skill=%s, name=%s)", name, var)
        return nocache_json({"error": "store_unavailable"}, status_code=503)
    _audit(orch, "skill.setup.clear", f"{var} cleared for skill {name}", {"skill": name, "name": var})
    return nocache_json({"ok": True, "removed": result["removed"], **await asyncio.to_thread(_setup_view, skill)})
