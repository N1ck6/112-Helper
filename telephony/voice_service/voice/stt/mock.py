"""Mock STT: не распознаёт речь, возвращает фиксированный текст.

Нужен, чтобы Backend/ML и голосовой цикл (этап 6) разрабатывались и
тестировались без моделей. Текст задаётся MOCK_STT_TEXT.
"""

import os

from ..audio import wav_info
from .base import Segment, STTEngine, STTResult


class MockSTT(STTEngine):
    name = "mock"

    def __init__(self, text: str | None = None):
        self.text = text if text is not None else os.environ.get(
            "MOCK_STT_TEXT", "Пожар на улице Ленина, дом пять.")

    def transcribe(self, wav: bytes, language: str | None = None) -> STTResult:
        duration = wav_info(wav).duration_sec
        return STTResult(
            text=self.text,
            language=language,
            duration_sec=round(duration, 3),
            engine=self.name,
            segments=[Segment(0.0, round(duration, 3), self.text)],
        )
