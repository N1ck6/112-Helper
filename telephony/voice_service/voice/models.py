"""Загрузка моделей STT/TTS в MODELS_DIR (интернет нужен только здесь).

Вызывается скриптом download_models.py вручную или автоматически при первом старте
сервиса (MODELS_AUTO_DOWNLOAD=1), если моделей ещё нет. Дальше — работа без сети.
"""

import logging
import os
import urllib.request

from .config import Settings

log = logging.getLogger(__name__)
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def piper_url(voice: str, suffix: str) -> str:
    # ru_RU-irina-medium -> ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx
    locale, name, quality = voice.split("-", 2)
    return f"{PIPER_BASE}/{locale.split('_')[0]}/{locale}/{name}/{quality}/{voice}{suffix}"


def download_whisper(settings: Settings) -> None:
    target = settings.models_dir / "whisper" / settings.whisper_model
    if (target / "model.bin").exists():
        log.info("whisper %s уже есть: %s", settings.whisper_model, target)
        return
    log.info("Загрузка whisper %s -> %s", settings.whisper_model, target)
    # в образе HF_HUB_OFFLINE=1 (рантайм без сети), а huggingface_hub читает флаг при импорте —
    # на время загрузки выключаем и переменную, и уже прочитанную константу
    previous_env = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "0"
    import huggingface_hub.constants as hf_constants
    from faster_whisper import download_model
    previous_const, hf_constants.HF_HUB_OFFLINE = hf_constants.HF_HUB_OFFLINE, False
    try:
        download_model(settings.whisper_model, output_dir=str(target))
    finally:
        hf_constants.HF_HUB_OFFLINE = previous_const
        if previous_env is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous_env


def download_piper(settings: Settings) -> None:
    # голос по умолчанию + голоса категорий собеседника (male/female)
    refs = [settings.piper_voice] + [r for refs in settings.voice_aliases().values() for r in refs]
    for voice in dict.fromkeys(refs):
        download_piper_voice(settings, voice)


SILERO_BASE = "https://models.silero.ai/models/tts/ru"


def download_silero(settings: Settings) -> None:
    target = settings.models_dir / "silero" / f"{settings.silero_model}.pt"
    if target.exists() and target.stat().st_size > 0:
        log.info("silero %s уже есть", target.name)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"{SILERO_BASE}/{settings.silero_model}.pt"
    tmp = target.with_suffix(".part")
    for attempt in range(1, 4):   # сервер моделей иногда рвёт TLS — повторяем
        log.info("Загрузка %s (попытка %d)", url, attempt)
        try:
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(target)
            return
        except OSError as exc:
            log.warning("не скачалось: %s", exc)
            tmp.unlink(missing_ok=True)
    raise OSError(f"модель Silero не скачана: {url}")


def download_piper_voice(settings: Settings, voice: str) -> None:
    target_dir = settings.models_dir / "piper"
    target_dir.mkdir(parents=True, exist_ok=True)
    for suffix in (".onnx", ".onnx.json"):
        target = target_dir / f"{voice}{suffix}"
        if target.exists() and target.stat().st_size > 0:
            log.info("piper %s уже есть", target.name)
            continue
        url = piper_url(voice, suffix)
        log.info("Загрузка %s", url)
        tmp = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(target)


DOWNLOADERS = {"faster_whisper": download_whisper, "piper": download_piper, "silero": download_silero}


def download_for(engine_name: str, settings: Settings) -> bool:
    """Скачать модели движка; False — движку модели не нужны или загрузка не удалась."""
    downloader = DOWNLOADERS.get(engine_name)
    if downloader is None:
        return False
    try:
        downloader(settings)
        return True
    except Exception as exc:  # нет сети / нет места — сервис решит, что делать дальше
        log.error("не удалось скачать модели %s: %s", engine_name, exc)
        return False
