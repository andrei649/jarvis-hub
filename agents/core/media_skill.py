"""
media_skill.py — H21.B Media summary skill (yt-dlp + Whisper).

"Summarize this video/podcast": yt-dlp pulls the audio → existing Whisper STT →
the agent summarizes. Composes with what exists. The downloader/transcriber/
summarizer are injected (yt-dlp + Whisper binaries are the host seam); the
pipeline orchestration is offline-testable.
"""

from __future__ import annotations

import inspect
import logging

logger = logging.getLogger("jarvis.media_skill")


async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


class MediaSummarizer:
    def __init__(self, downloader=None, transcriber=None, summarizer=None) -> None:
        self._dl = downloader        # (url) -> audio path
        self._tr = transcriber       # (audio) -> transcript
        self._sum = summarizer       # (transcript) -> summary

    async def summarize_url(self, url: str) -> dict:
        if not url:
            return {"ok": False, "reason": "no_url"}
        if self._dl is None or self._tr is None:
            return {"ok": False, "reason": "host_tools_unavailable"}   # yt-dlp/whisper
        try:
            audio = await _maybe_await(self._dl(url))
            transcript = await _maybe_await(self._tr(audio))
        except Exception:
            logger.warning("media pipeline failed", exc_info=True)
            return {"ok": False, "reason": "pipeline_error"}
        summary = ""
        if self._sum is not None:
            try:
                summary = await _maybe_await(self._sum(transcript))
            except Exception:
                summary = ""
        return {"ok": True, "transcript": transcript,
                "summary": summary or (transcript or "")[:200]}
