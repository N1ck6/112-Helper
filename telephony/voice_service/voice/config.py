"""Конфигурация из переменных окружения. Одно место, без хардкода в движках."""

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    # Выбор реализации: faster_whisper | mock  /  piper | mock
    stt_engine: str
    tts_engine: str
    # Язык распознавания (ISO-код). Пусто/"auto" -> автоопределение whisper.
    stt_language: str | None
    # faster-whisper: имя модели (tiny/base/small/medium) или путь к каталогу
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    whisper_beam_size: int
    # Piper: голос по умолчанию (ru_RU-irina-medium) или путь к .onnx,
    # и голоса по категориям собеседника (мужской / женский).
    piper_voice: str
    piper_voice_male: str
    piper_voice_female: str
    # Частота WAV на выходе TTS. 8000 = формат, который Asterisk
    # проигрывает через STREAM FILE без перекодирования.
    tts_sample_rate: int
    models_dir: Path
    # Разрешённые корни для POST /stt {"path": ...} и POST /tts {"save_as": ...}
    audio_root: Path
    tts_output_dir: Path
    host: str
    port: int
    max_upload_bytes: int
    max_tts_chars: int
    # Сколько распознаваний faster-whisper идёт параллельно (num_workers модели).
    whisper_workers: int

    def voice_aliases(self) -> dict[str, str]:
        return {"male": self.piper_voice_male, "female": self.piper_voice_female}

    @classmethod
    def from_env(cls) -> "Settings":
        lang = _env("STT_LANGUAGE", "ru")
        return cls(
            stt_engine=_env("STT_ENGINE", "mock").lower(),
            tts_engine=_env("TTS_ENGINE", "mock").lower(),
            stt_language=None if lang.lower() == "auto" else lang,
            whisper_model=_env("WHISPER_MODEL", "small"),
            whisper_device=_env("WHISPER_DEVICE", "cpu"),
            whisper_compute_type=_env("WHISPER_COMPUTE_TYPE", "int8"),
            whisper_beam_size=int(_env("WHISPER_BEAM_SIZE", "5")),
            piper_voice=_env("PIPER_VOICE", "ru_RU-irina-medium"),
            piper_voice_male=_env("PIPER_VOICE_MALE", "ru_RU-dmitri-medium"),
            piper_voice_female=_env("PIPER_VOICE_FEMALE", _env("PIPER_VOICE", "ru_RU-irina-medium")),
            tts_sample_rate=int(_env("TTS_SAMPLE_RATE", "8000")),
            models_dir=Path(_env("MODELS_DIR", "/models")),
            audio_root=Path(_env("AUDIO_ROOT", "/recordings")),
            tts_output_dir=Path(_env("TTS_OUTPUT_DIR", "/tts")),
            host=_env("LISTEN_HOST", "0.0.0.0"),
            port=int(_env("LISTEN_PORT", "8091")),
            max_upload_bytes=int(_env("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))),
            max_tts_chars=int(_env("MAX_TTS_CHARS", "1000")),
            whisper_workers=max(1, int(_env("WHISPER_WORKERS", "2"))),
        )
