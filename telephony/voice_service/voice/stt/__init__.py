"""STT: фабрика по имени движка. Новый движок = новый класс + строка здесь."""

from ..config import Settings
from .base import EngineNotReady, Segment, STTEngine, STTResult

__all__ = ["EngineNotReady", "Segment", "STTEngine", "STTResult", "create_stt", "STT_ENGINES"]

STT_ENGINES = ("faster_whisper", "mock")


def create_stt(settings: Settings) -> STTEngine:
    name = settings.stt_engine
    if name == "mock":
        from .mock import MockSTT
        return MockSTT()
    if name == "faster_whisper":
        from .faster_whisper_engine import FasterWhisperSTT
        return FasterWhisperSTT(
            model=settings.whisper_model,
            models_dir=settings.models_dir,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            beam_size=settings.whisper_beam_size,
            language=settings.stt_language,
        )
    raise ValueError(f"неизвестный STT_ENGINE={name!r}, доступны: {', '.join(STT_ENGINES)}")
