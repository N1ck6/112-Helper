"""CLI для проверки движков напрямую, без HTTP.

    python -m voice.cli stt /recordings/response_<call_id>.wav
    python -m voice.cli tts "Помогите, пожар!" -o /tts/test.wav [--voice male]
Движки — из STT_ENGINE / TTS_ENGINE (как у сервиса).
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from .config import Settings
from .stt import create_stt
from .tts import create_tts


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(prog="voice.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_stt = sub.add_parser("stt", help="WAV -> текст")
    p_stt.add_argument("wav", type=Path)
    p_stt.add_argument("--language", default=None)
    p_tts = sub.add_parser("tts", help="текст -> WAV")
    p_tts.add_argument("text")
    p_tts.add_argument("-o", "--output", type=Path, required=True)
    p_tts.add_argument("--rate", type=int, default=None, help="частота WAV (по умолчанию TTS_SAMPLE_RATE)")
    p_tts.add_argument("--voice", default=None, help="male | female | имя голоса")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    started = time.monotonic()
    if args.cmd == "stt":
        engine = create_stt(settings)
        engine.load()
        result = engine.transcribe(args.wav.read_bytes(), language=args.language)
        data = result.to_dict()
        data["processing_sec"] = round(time.monotonic() - started, 3)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        engine = create_tts(settings)
        engine.load()
        result = engine.synthesize(args.text, args.rate or settings.tts_sample_rate, args.voice)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(result.wav)
        print(json.dumps({"output": str(args.output), "engine": result.engine,
                          "sample_rate": result.sample_rate, "duration_sec": result.duration_sec,
                          "processing_sec": round(time.monotonic() - started, 3)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
