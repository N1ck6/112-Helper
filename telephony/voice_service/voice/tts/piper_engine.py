"""TTS на Piper (ONNX), полностью локально.

Голоса: MODELS_DIR/piper/<голос>.onnx + .onnx.json (скачиваются download_models.py).
Голос по умолчанию обязателен; голоса категорий (male/female) — если скачаны,
иначе используется голос по умолчанию.
"""

import io
import logging
import threading
import wave
from pathlib import Path

from ..audio import to_wav_mono16, wav_info
from .base import EngineNotReady, TTSEngine, TTSResult
from .silero_engine import pick_voice

log = logging.getLogger(__name__)


class PiperTTS(TTSEngine):
    name = "piper"

    def __init__(self, voice: str, models_dir: Path, aliases: dict[str, list[str]] | None = None):
        self.default_ref = voice
        self.models_dir = Path(models_dir)
        self.aliases = dict(aliases or {})
        self._voices: dict[str, object] = {}   # имя голоса -> PiperVoice
        self._locks: dict[str, threading.Lock] = {}

    def voice_path(self, ref: str) -> Path:
        p = Path(ref)
        if p.suffix == ".onnx":
            return p if p.is_absolute() else self.models_dir / "piper" / p
        return self.models_dir / "piper" / f"{ref}.onnx"

    def _load_one(self, ref: str) -> None:
        path = self.voice_path(ref)
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
        self._voices[ref] = PiperVoice.load(str(path), config_path=str(config))
        self._locks[ref] = threading.Lock()

    def load(self) -> None:
        self._load_one(self.default_ref)  # без голоса по умолчанию сервис не готов
        for alias, refs in self.aliases.items():
            for ref in refs:
                if ref in self._voices:
                    continue
                try:
                    self._load_one(ref)
                except EngineNotReady as exc:
                    log.warning("голос %s (%s) недоступен, будет голос по умолчанию: %s", alias, ref, exc)

    def voices(self) -> list[str]:
        return sorted(self._voices) + [a for a, refs in self.aliases.items() if any(r in self._voices for r in refs)]

    def _resolve(self, voice: str | None) -> str:
        groups = {k: [r for r in refs if r in self._voices] for k, refs in self.aliases.items()}
        return pick_voice(voice, groups, set(self._voices), self.default_ref)

    def _synthesize_native(self, ref: str, text: str) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            # piper-tts >= 1.3: synthesize_wav(); 1.2.x: synthesize(text, wav_file).
            v = self._voices[ref]
            if hasattr(v, "synthesize_wav"):
                v.synthesize_wav(text, w)
            else:
                v.synthesize(text, w)
        return buf.getvalue()

    def synthesize(self, text: str, sample_rate: int, voice: str | None = None) -> TTSResult:
        if not self._voices:
            raise EngineNotReady("Piper не загружен")
        ref = self._resolve(voice)
        with self._locks[ref]:  # один голос — один поток; разные голоса параллельно
            native = self._synthesize_native(ref, text)
        # Piper отдаёт 22050 Гц; для Asterisk (STREAM FILE) нужно 8000 Гц.
        wav = to_wav_mono16(native, sample_rate)
        return TTSResult(wav, sample_rate, round(wav_info(wav).duration_sec, 3), f"{self.name}:{ref}")
