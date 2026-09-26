"""STT на faster-whisper (CTranslate2), полностью локально.

Модель берётся из MODELS_DIR/whisper/<WHISPER_MODEL> (скачивается один раз
скриптом download_models.py). В рантайме сеть не нужна: local_files_only.
"""

import io
import logging
import threading
from pathlib import Path

from ..audio import read_pcm16_mono, pcm16_to_wav
from .base import EngineNotReady, Segment, STTEngine, STTResult

log = logging.getLogger(__name__)


class FasterWhisperSTT(STTEngine):
    name = "faster_whisper"

    def __init__(self, model: str, models_dir: Path, device: str = "cpu",
                 compute_type: str = "int8", beam_size: int = 5, language: str | None = "ru",
                 workers: int = 1):
        self.model_ref = model
        self.models_dir = Path(models_dir)
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.default_language = language
        self._model = None
        self.workers = max(1, workers)
        # num_workers=N у WhisperModel даёт N параллельных распознаваний из разных
        # потоков; семафор не пускает больше — остальные звонки ждут очереди,
        # а не делят CPU до неразборчивости.
        self._slots = threading.BoundedSemaphore(self.workers)

    def model_path(self) -> Path:
        p = Path(self.model_ref)
        return p if p.is_absolute() else self.models_dir / "whisper" / self.model_ref

    def load(self) -> None:
        path = self.model_path()
        if not (path / "model.bin").exists():
            raise EngineNotReady(
                f"модель whisper не найдена: {path}. Скачайте: "
                f"docker compose run --rm voice-service python download_models.py")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise EngineNotReady(f"пакет faster-whisper не установлен: {exc}") from exc
        log.info("Загрузка faster-whisper: %s device=%s compute=%s", path, self.device, self.compute_type)
        self._model = WhisperModel(str(path), device=self.device, compute_type=self.compute_type,
                                   num_workers=self.workers, local_files_only=True)

    def transcribe(self, wav: bytes, language: str | None = None) -> STTResult:
        if self._model is None:
            raise EngineNotReady("faster-whisper не загружен")
        # Нормализуем вход в PCM16 mono: записи Asterisk бывают 8 кГц,
        # whisper сам ресемплирует до 16 кГц при декодировании.
        pcm, rate = read_pcm16_mono(wav)
        audio = io.BytesIO(pcm16_to_wav(pcm, rate))
        lang = language or self.default_language
        with self._slots:
            segments_iter, info = self._model.transcribe(
                audio, language=lang, beam_size=self.beam_size, vad_filter=True)
            segments = [Segment(round(s.start, 3), round(s.end, 3), s.text.strip()) for s in segments_iter]
        return STTResult(
            text=" ".join(s.text for s in segments if s.text).strip(),
            language=info.language,
            duration_sec=round(info.duration, 3),
            engine=self.name,
            segments=segments,
        )
