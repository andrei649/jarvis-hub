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
    def __init__(
        self,
        downloader=None,
        transcriber=None,
        summarizer=None,
        *,
        url_guard=None,
    ) -> None:
        self._dl = downloader  # (url) -> audio path
        self._tr = transcriber  # (audio) -> transcript
        self._sum = summarizer  # (transcript) -> summary
        self._url_guard = url_guard  # governed URL policy, e.g. BrowserPolicy.domain_allowed

    async def summarize_url(self, url: str) -> dict:
        if not url:
            return {"ok": False, "reason": "no_url"}
        if self._dl is None or self._tr is None:
            return {"ok": False, "reason": "host_tools_unavailable"}  # yt-dlp/whisper
        if self._url_guard is None:
            return {"ok": False, "reason": "url_guard_unavailable"}
        try:
            guard_result = await _maybe_await(self._url_guard(url))
        except Exception:
            return {"ok": False, "reason": "url_refused"}
        allowed = (
            isinstance(guard_result, (tuple, list))
            and len(guard_result) == 2
            and guard_result[0] is True
            and isinstance(guard_result[1], str)
            and not guard_result[1]
        )
        if not allowed:
            return {"ok": False, "reason": "url_refused"}
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
        return {
            "ok": True,
            "transcript": transcript,
            "summary": summary or (transcript or "")[:200],
        }
