"""audio_container.py — what an audio clip really is, and making it a voice note (H528, G16).

A chat platform plays a clip as a native voice note only in some containers: Telegram's
``sendVoice`` wants Ogg/Opus (it also takes MP3 and M4A, without a waveform). The TTS
engines Nerva drives produce WAV, MP3 or Ogg, and the file's suffix or the engine's MIME
is not proof of what the bytes are. So:

* :func:`sniff` reads the magic bytes: ``ogg_opus``, ``ogg_vorbis``, ``ogg`` (other),
  ``mp3``, ``wav``, ``flac``, ``m4a``, or ``unknown``.
* :func:`prepare_voice` returns what to send. Ogg/Opus goes as it is, and so do MP3 and
  M4A, the two other containers Telegram documents for ``sendVoice``. Anything else (WAV,
  FLAC, Ogg/Vorbis, an unrecognised body) is converted to Ogg/Opus with ``ffmpeg`` (stdin to stdout, no shell, no temporary file,
  bounded time and output) when ffmpeg is installed. When it is not, or the conversion
  fails, the clip is sent as a plain audio file (``mode="audio"``) with a one-line note
  saying why it is not a voice note — never dropped, never mislabelled.

Adapted from the shape of Hermes ``tools/audio_container.py`` (MIT, reference only);
Nerva keeps one conversion path (to Opus) and no concatenation matrix.
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404 — fixed argv, no shell, see _convert
from dataclasses import dataclass

logger = logging.getLogger("jarvis.channels.audio_container")

#: The longest a conversion may take, and the largest output it may produce.
CONVERT_TIMEOUT_S = 30.0
MAX_OUTPUT_BYTES = 20 * 1024 * 1024

MIME = {"ogg_opus": "audio/ogg", "ogg_vorbis": "audio/ogg", "ogg": "audio/ogg",
        "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "m4a": "audio/mp4"}
SUFFIX = {"ogg_opus": "ogg", "ogg_vorbis": "ogg", "ogg": "ogg", "mp3": "mp3", "wav": "wav",
          "flac": "flac", "m4a": "m4a"}

#: Containers a voice message takes as they are (Telegram Bot API, ``sendVoice``).
VOICE_READY = frozenset({"ogg_opus", "mp3", "m4a"})

NOTE_NO_FFMPEG = ("Sent as an audio file, not a voice note: this hub has no ffmpeg to "
                  "convert it.")
NOTE_CONVERT_FAILED = "Sent as an audio file, not a voice note: it could not be converted."


def sniff(data: bytes) -> str:
    """The container (and, for Ogg, the codec) the bytes really are."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 4:
        return "unknown"
    head = bytes(data[:4096])
    if head.startswith(b"OggS"):
        if b"OpusHead" in head[:256]:
            return "ogg_opus"
        if b"\x01vorbis" in head[:256]:
            return "ogg_vorbis"
        return "ogg"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"fLaC"):
        return "flac"
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in (b"M4A ", b"M4B ", b"mp42", b"isom", b"mp41", b"dash"):
        return "m4a"
    if head.startswith(b"ID3") or (head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    return "unknown"


@dataclass(frozen=True)
class VoiceClip:
    data: bytes
    mime: str
    filename: str
    #: ``voice`` — send as a native voice note; ``audio`` — as an audio file.
    mode: str
    note: str = ""
    converted: bool = False


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _convert(data: bytes, ffmpeg: str) -> bytes | None:
    """Re-encode to Ogg/Opus mono 48 kHz. Fixed argv, stdin/stdout only, bounded."""
    argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", "pipe:0", "-vn", "-ac", "1", "-ar", "48000", "-c:a", "libopus",
            "-b:a", "32k", "-f", "ogg", "pipe:1"]
    try:
        proc = subprocess.run(  # nosec B603 — argv list, no shell; ffmpeg from PATH lookup
            argv, input=data, capture_output=True, timeout=CONVERT_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("Voice conversion did not run (%s)", type(exc).__name__)
        return None
    out = proc.stdout or b""
    if proc.returncode != 0 or not out or len(out) > MAX_OUTPUT_BYTES or sniff(out) != "ogg_opus":
        logger.info("Voice conversion failed (exit %s)", proc.returncode)
        return None
    return out


def prepare_voice(data: bytes, *, declared_mime: str = "", stem: str = "reply",
                  convert=None, ffmpeg: str | None | bool = None) -> VoiceClip:
    """What to post for *data* as a voice message.

    ``ffmpeg``: ``None`` looks it up on PATH; ``False`` behaves as if it were missing
    (tests); a string is used as the binary. ``convert`` replaces the converter (tests).
    """
    container = sniff(data)
    if container in VOICE_READY:
        return VoiceClip(bytes(data), MIME[container], f"{stem}.{SUFFIX[container]}", "voice")
    binary = ffmpeg_path() if ffmpeg is None else (ffmpeg or None)
    mime = MIME.get(container) or (declared_mime if declared_mime.startswith("audio/") else
                                   "application/octet-stream")
    suffix = SUFFIX.get(container, "bin")
    if binary is None:
        return VoiceClip(bytes(data), mime, f"{stem}.{suffix}", "audio", NOTE_NO_FFMPEG)
    converted = (convert or _convert)(bytes(data), binary)
    if converted is None:
        return VoiceClip(bytes(data), mime, f"{stem}.{suffix}", "audio", NOTE_CONVERT_FAILED)
    return VoiceClip(converted, "audio/ogg", f"{stem}.ogg", "voice", converted=True)


__all__ = ["NOTE_CONVERT_FAILED", "NOTE_NO_FFMPEG", "VoiceClip", "ffmpeg_path",
           "prepare_voice", "sniff"]
