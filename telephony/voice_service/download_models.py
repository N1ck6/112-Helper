"""Однократная загрузка моделей в MODELS_DIR (нужен интернет только здесь).

    docker compose run --rm -e HF_HUB_OFFLINE=0 voice-service python download_models.py

Результат (том ./models на хосте):
    /models/whisper/<WHISPER_MODEL>/model.bin ...
    /models/piper/<PIPER_VOICE>.onnx, .onnx.json
После этого сервис работает без сети (HF_HUB_OFFLINE=1 в образе).
"""

import logging
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from voice.config import Settings  # noqa: E402

log = logging.getLogger("download_models")
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
    from faster_whisper import download_model
    log.info("Загрузка whisper %s -> %s", settings.whisper_model, target)
    download_model(settings.whisper_model, output_dir=str(target))


def download_piper(settings: Settings) -> None:
    voice = settings.piper_voice
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


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    os.environ["HF_HUB_OFFLINE"] = "0"
    settings = Settings.from_env()
    download_whisper(settings)
    download_piper(settings)
    log.info("Готово. Модели в %s", settings.models_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
