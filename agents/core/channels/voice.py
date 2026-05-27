"""
voice.py — Voice channel adapter.

Wraps the VoicePipeline (wake word -> STT -> TTS cycle)
into a ChannelAdapter that the orchestrator can route through.
"""

import asyncio
import logging
from typing import Callable, Optional

from .base import ChannelAdapter
from ..voice.pipeline import VoicePipeline

logger = logging.getLogger("jarvis.channels.voice")


class VoiceChannel(ChannelAdapter):
    def __init__(self, handler: Optional[Callable] = None,
                 wake_words: Optional[list[str]] = None):
        super().__init__("voice", handler)
        self.wake_words = wake_words or ["jarvis", "hub"]
        self.pipeline: Optional[VoicePipeline] = None

    async def start(self):
        self._running = True
        self.pipeline = VoicePipeline(on_transcription=self.handle_transcription)
        await self.pipeline.start()
        logger.info("Voice channel started")

    async def stop(self):
        self._running = False
        if self.pipeline:
            self.pipeline.stop()
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
        logger.info(f"Voice transcription: {text[:60]}")
        return await self.receive(text)

    async def set_wake_words(self, words: list[str]):
        self.wake_words = words
        if self.pipeline and self.pipeline.detector:
            self.pipeline.detector.WAKE_WORDS = words
            logger.info(f"Wake words updated: {words}")
