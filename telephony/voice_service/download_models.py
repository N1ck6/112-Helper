"""Однократная загрузка моделей в MODELS_DIR (нужен интернет только здесь).

    docker compose run --rm voice-service python download_models.py

Обычно не нужен: сервис сам скачивает недостающие модели при первом старте
(MODELS_AUTO_DOWNLOAD=1). Результат (том ./models на хосте):
    /models/whisper/<WHISPER_MODEL>/model.bin ...
    /models/piper/<PIPER_VOICE>.onnx, .onnx.json
После этого сервис работает без сети (HF_HUB_OFFLINE=1 в образе).
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from voice.config import Settings  # noqa: E402
from voice.models import download_piper, download_whisper, piper_url  # noqa: E402,F401

log = logging.getLogger("download_models")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    settings = Settings.from_env()
    download_whisper(settings)
    download_piper(settings)
    log.info("Готово. Модели в %s", settings.models_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
