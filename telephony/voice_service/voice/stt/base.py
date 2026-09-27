"""Контракт STT: Audio (WAV bytes) -> Text."""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


class EngineNotReady(RuntimeError):
    """Модель не загружена (нет файлов, ошибка инициализации)."""


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class STTResult:
    text: str
    language: str | None
    duration_sec: float
    engine: str
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class STTEngine(ABC):
    name: str = "base"

    def load(self) -> None:
        """Тяжёлая инициализация (загрузка модели). Вызывается один раз на старте."""

    @abstractmethod
    def transcribe(self, wav: bytes, language: str | None = None) -> STTResult:
        """WAV PCM16 (любая частота, моно/стерео) -> текст."""
