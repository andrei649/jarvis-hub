"""
voice.py — Voice channel adapter.

Wraps the VoicePipeline (wake word -> STT -> TTS cycle)
into a ChannelAdapter that the orchestrator can route through.
"""

import asyncio
import logging
from typing import Callable, Optional

from .base import ChannelAdapter
from ..voice import mic
from ..voice.pipeline import VoicePipeline

logger = logging.getLogger("jarvis.channels.voice")


class VoiceChannel(ChannelAdapter):
    def __init__(self, handler: Optional[Callable] = None,
                 wake_words: Optional[list[str]] = None):
        super().__init__("voice", handler)
        self.wake_words = wake_words or ["jarvis", "hub"]
        self.pipeline: Optional[VoicePipeline] = None

    #: The hub's own pipeline, as a microphone lease (H247).
    SURFACE = "host:hub"

    async def start(self):
        # H247: the hub's always-on listener opens the microphone only with a lease — the
        # owner's consent (voice.mic_surfaces) and no other surface on this machine
        # holding it. A take-over pauses the pipeline; giving the mic back starts it again.
        self._running = True
        self._loop = asyncio.get_running_loop()
        try:
            mic.ARBITER.arm("host", "hub", device=mic.HOST_DEVICE)
        except mic.MicRefused as refused:
            logger.info("Voice channel: the host microphone stays closed (%s)", refused.message)
            return
        mic.ARBITER.on_change(self.SURFACE, self._on_lease)
        await self._run_pipeline()
        logger.info("Voice channel started")

    async def _run_pipeline(self):
        self.pipeline = VoicePipeline(on_transcription=self.handle_transcription)
        await self.pipeline.start()

    def _on_lease(self, state: str) -> None:
        if state == "paused":
            if self.pipeline:
                self.pipeline.stop()
                self.pipeline = None
        elif state == "armed" and self._running and self.pipeline is None:
            loop = getattr(self, "_loop", None)
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(lambda: loop.create_task(self._run_pipeline()))

    async def stop(self):
        self._running = False
        if self.pipeline:
            self.pipeline.stop()
            self.pipeline = None
        mic.ARBITER.stop(self.SURFACE)
        logger.info("Voice channel stopped")

    async def send(self, message: str, **kwargs) -> bool:
        if not self.pipeline or not self.pipeline.tts:
            logger.warning("TTS not available")
            return False
        try:
            audio_path = await self.pipeline.tts.speak(
                message, lang=kwargs.get("lang", "ro")
            )
            if audio_path:
                await self.pipeline._play_audio(audio_path)
                return True
            return False
        except Exception as e:
            logger.error(f"Voice send error: {e}")
            return False

    async def handle_transcription(self, text: str) -> Optional[str]:
        # DEBUG, not INFO: the transcript is spoken user content. Keeping it below
        # the default level keeps it out of the default-INFO sink (stderr and the
        # opt-in rotating file log, H23.11) unless an operator explicitly enables DEBUG.
        logger.debug(f"Voice transcription: {text[:60]}")
        return await self.receive(text)

    async def set_wake_words(self, words: list[str]):
        self.wake_words = words
        if self.pipeline and self.pipeline.detector:
            self.pipeline.detector.WAKE_WORDS = words
            logger.info(f"Wake words updated: {words}")
