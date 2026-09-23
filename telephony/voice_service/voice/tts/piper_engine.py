"""TTS на Piper (ONNX), полностью локально.

Голос: MODELS_DIR/piper/<PIPER_VOICE>.onnx + .onnx.json
(скачивается один раз скриптом download_models.py).
"""

import io
import logging
import threading
import wave
from pathlib import Path

from ..audio import to_wav_mono16, wav_info
from .base import EngineNotReady, TTSEngine, TTSResult

log = logging.getLogger(__name__)


class PiperTTS(TTSEngine):
    name = "piper"

    def __init__(self, voice: str, models_dir: Path):
        self.voice_ref = voice
        self.models_dir = Path(models_dir)
        self._voice = None
        self._lock = threading.Lock()

    def voice_path(self) -> Path:
        p = Path(self.voice_ref)
        if p.suffix == ".onnx":
            return p if p.is_absolute() else self.models_dir / "piper" / p
        return self.models_dir / "piper" / f"{self.voice_ref}.onnx"

    def load(self) -> None:
        path = self.voice_path()
        config = Path(str(path) + ".json")
        if not path.exists() or not config.exists():
            raise EngineNotReady(
                f"голос Piper не найден: {path} (+ .json). Скачайте: "
                f"docker compose run --rm voice-service python download_models.py")
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise EngineNotReady(f"пакет piper-tts не установлен: {exc}") from exc
        log.info("Загрузка Piper: %s", path)
        self._voice = PiperVoice.load(str(path), config_path=str(config))

    def _synthesize_native(self, text: str) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            # piper-tts >= 1.3: synthesize_wav(); 1.2.x: synthesize(text, wav_file).
            if hasattr(self._voice, "synthesize_wav"):
                self._voice.synthesize_wav(text, w)
            else:
                self._voice.synthesize(text, w)
        return buf.getvalue()

    def synthesize(self, text: str, sample_rate: int) -> TTSResult:
        if self._voice is None:
            raise EngineNotReady("Piper не загружен")
        with self._lock:
            native = self._synthesize_native(text)
        # Piper отдаёт 22050 Гц; для Asterisk (STREAM FILE) нужно 8000 Гц.
        wav = to_wav_mono16(native, sample_rate)
        return TTSResult(wav, sample_rate, round(wav_info(wav).duration_sec, 3), self.name)
