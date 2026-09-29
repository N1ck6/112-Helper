"""TTS на Silero (PyTorch, CPU), полностью локально: мягкие естественные русские голоса.

Модель: MODELS_DIR/silero/<SILERO_MODEL>.pt (v5_ru, скачивается при первом старте).
Голоса собеседников: женские SILERO_VOICES_FEMALE, мужские SILERO_VOICES_MALE.
voice в запросе: "female" / "male" — первый голос категории; "female-7" / "male-3" — голос
категории по номеру (virtual-caller даёт номер по имени собеседника: у каждого свой тембр);
имя голоса ("baya") — он сам.

Лицензия моделей silero v5_ru — CC BY-NC 4.0 (некоммерческое использование, © Silero Team,
github.com/snakers4/silero-models). Для коммерческого использования — TTS_ENGINE=piper (MIT).
"""

import io
import logging
import threading
import wave
from pathlib import Path

from ..audio import to_wav_mono16, wav_info
from .base import EngineNotReady, TTSEngine, TTSResult

log = logging.getLogger(__name__)

NATIVE_RATES = (8000, 24000, 48000)


def pick_voice(voice: str | None, groups: dict[str, list[str]], known: set[str], default: str) -> str:
    """male / female / female-<n> / имя голоса -> имя голоса движка."""
    if not voice:
        return default
    if voice in known:
        return voice
    kind, _, number = voice.partition("-")
    pool = groups.get(kind) or []
    if not pool:
        return default
    return pool[int(number) % len(pool)] if number.isdigit() else pool[0]


class SileroTTS(TTSEngine):
    name = "silero"

    def __init__(self, model: str, models_dir: Path, female: list[str], male: list[str], threads: int = 2):
        self.model_name = model
        self.models_dir = Path(models_dir)
        self.groups = {"female": list(female), "male": list(male)}
        self.threads = threads
        self._model = None
        self._speakers: set[str] = set()
        self._lock = threading.Lock()

    @property
    def model_path(self) -> Path:
        return self.models_dir / "silero" / f"{self.model_name}.pt"

    def load(self) -> None:
        if not self.model_path.exists():
            raise EngineNotReady(f"модель Silero не найдена: {self.model_path} (MODELS_AUTO_DOWNLOAD=1 скачает)")
        try:
            import torch
        except ImportError as exc:
            raise EngineNotReady(f"пакет torch не установлен: {exc}") from exc
        torch.set_num_threads(self.threads)
        log.info("Загрузка Silero: %s", self.model_path)
        importer = torch.package.PackageImporter(str(self.model_path))
        model = importer.load_pickle("tts_models", "model")
        model.to(torch.device("cpu"))
        self._model = model
        self._speakers = set(getattr(model, "speakers", []) or [])
        for kind, pool in self.groups.items():
            missing = [v for v in pool if self._speakers and v not in self._speakers]
            if missing:
                log.warning("голоса %s нет в модели %s: %s", kind, self.model_name, ", ".join(missing))
            self.groups[kind] = [v for v in pool if not self._speakers or v in self._speakers]
        if not (self.groups["female"] or self.groups["male"]):
            raise EngineNotReady(f"в модели {self.model_name} нет ни одного голоса из настроек")
        # прогрев: первая фраза иначе синтезируется заметно дольше
        self._synthesize_native("Слушаю вас.", self.default_voice, 8000)

    @property
    def default_voice(self) -> str:
        return (self.groups["female"] or self.groups["male"])[0]

    def voices(self) -> list[str]:
        return sorted(set(self.groups["female"] + self.groups["male"])) + ["female", "male"]

    def _synthesize_native(self, text: str, speaker: str, rate: int) -> bytes:
        with self._lock:   # модель одна — синтез по очереди (короткие реплики, ~0.3–1 с)
            audio = self._model.apply_tts(text=text, speaker=speaker, sample_rate=rate,
                                          put_accent=True, put_yo=True)
        pcm = (audio.clamp(-1, 1) * 32767).short().numpy().tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        return buf.getvalue()

    def synthesize(self, text: str, sample_rate: int, voice: str | None = None) -> TTSResult:
        if self._model is None:
            raise EngineNotReady("Silero не загружен")
        speaker = pick_voice(voice, self.groups, self._speakers, self.default_voice)
        native_rate = sample_rate if sample_rate in NATIVE_RATES else 24000
        native = self._synthesize_native(text, speaker, native_rate)
        wav = native if native_rate == sample_rate else to_wav_mono16(native, sample_rate)
        return TTSResult(wav, sample_rate, round(wav_info(wav).duration_sec, 3), f"{self.name}:{speaker}")
