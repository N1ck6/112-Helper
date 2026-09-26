"""Mock TTS: вместо речи — тон, длительность пропорциональна тексту.

Позволяет проверить весь аудиотракт (файл -> Asterisk -> софтфон) и
контракт API без модели Piper. Мужской голос — тон ниже.
"""

from ..audio import tone_wav, wav_info
from .base import TTSEngine, TTSResult

SEC_PER_CHAR = 0.06
MIN_SEC, MAX_SEC = 0.3, 10.0
FREQ = {"male": 220.0, "female": 440.0}


class MockTTS(TTSEngine):
    name = "mock"

    def voices(self) -> list[str]:
        return sorted(FREQ)

    def synthesize(self, text: str, sample_rate: int, voice: str | None = None) -> TTSResult:
        duration = min(MAX_SEC, max(MIN_SEC, len(text) * SEC_PER_CHAR))
        wav = tone_wav(duration, sample_rate, freq=FREQ.get(voice or "", 440.0))
        return TTSResult(wav, sample_rate, round(wav_info(wav).duration_sec, 3), self.name)
