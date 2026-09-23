"""Контракт TTS: Text -> Audio (WAV bytes, PCM16 mono)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..stt.base import EngineNotReady  # единое исключение для обоих модулей

__all__ = ["EngineNotReady", "TTSEngine", "TTSResult"]


@dataclass
class TTSResult:
    wav: bytes
    sample_rate: int
    duration_sec: float
    engine: str


class TTSEngine(ABC):
    name: str = "base"

    def load(self) -> None:
        """Тяжёлая инициализация (загрузка голоса). Вызывается один раз на старте."""

    @abstractmethod
    def synthesize(self, text: str, sample_rate: int) -> TTSResult:
        """Текст -> WAV PCM16 mono с частотой sample_rate."""
