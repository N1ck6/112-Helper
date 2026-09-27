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

    def voices(self) -> list[str]:
        """Доступные голоса (псевдонимы male/female и полные имена)."""
        return []

    @abstractmethod
    def synthesize(self, text: str, sample_rate: int, voice: str | None = None) -> TTSResult:
        """Текст -> WAV PCM16 mono с частотой sample_rate.

        voice — псевдоним ("male"/"female") или имя голоса движка; None — голос по умолчанию.
        Неизвестный голос -> голос по умолчанию (звонок важнее точного тембра).
        """
