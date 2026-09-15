"""Narrow display preferences shared by browsers of the same owner instance."""
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from agents.core.appearance import RevisionConflict, read_appearance, update_appearance
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=['preferences'], dependencies=[Depends(user_guard)])


class AppearancePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: str | None = Field(None, alias='_revision', max_length=64)
    font: str | None = Field(None, max_length=32)
    accent: str | None = Field(None, max_length=32)
    look: str | None = Field(None, max_length=32)
    density: str | None = Field(None, max_length=32)
    motion: str | None = Field(None, max_length=32)
    scanline: str | None = Field(None, max_length=32)
    dotgrid: str | None = Field(None, max_length=32)


@router.get('/api/preferences/appearance')
def appearance_get():
    try:
        return nocache_json(read_appearance())
    except RevisionConflict:
        return nocache_json({'error': 'appearance revision changed'}, status_code=409)
    except (sqlite3.Error, OSError):
        return nocache_json({'error': 'appearance preferences unavailable'}, status_code=503)


@router.put('/api/preferences/appearance')
def appearance_put(body: AppearancePatch):
    try:
        return nocache_json(update_appearance(body.model_dump(exclude_unset=True, exclude={'expected_revision'}), body.expected_revision))
    except RevisionConflict:
        return nocache_json({'error': 'appearance revision changed'}, status_code=409)
    except (sqlite3.Error, OSError):
        return nocache_json({'error': 'appearance preferences unavailable'}, status_code=503)
