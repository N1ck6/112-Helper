"""TTS: фабрика по имени движка. Новый движок = новый класс + строка здесь."""

from ..config import Settings
from .base import EngineNotReady, TTSEngine, TTSResult

__all__ = ["EngineNotReady", "TTSEngine", "TTSResult", "create_tts", "TTS_ENGINES"]

TTS_ENGINES = ("silero", "piper", "mock")


def create_tts(settings: Settings) -> TTSEngine:
    name = settings.tts_engine
    if name == "mock":
        from .mock import MockTTS
        return MockTTS()
    if name == "silero":
        from .silero_engine import SileroTTS
        groups = settings.silero_groups()
        return SileroTTS(model=settings.silero_model, models_dir=settings.models_dir,
                         female=groups["female"], male=groups["male"], threads=settings.silero_threads)
    if name == "piper":
        from .piper_engine import PiperTTS
        return PiperTTS(voice=settings.piper_voice, models_dir=settings.models_dir,
                        aliases=settings.voice_aliases())
    raise ValueError(f"неизвестный TTS_ENGINE={name!r}, доступны: {', '.join(TTS_ENGINES)}")
