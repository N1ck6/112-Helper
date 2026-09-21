"""
Конвертация WAV -> MP3 для записанных учебных звонков.

Использование:
    python convert_to_mp3.py --once          # конвертировать все .wav один раз
    python convert_to_mp3.py --watch --interval 5   # проверять папку каждые 5с
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

RECORDINGS_DIR = Path("/recordings")


def convert_one(wav_path: Path) -> bool:
    mp3_path = wav_path.with_suffix(".mp3")
    if mp3_path.exists():
        return False  # уже сконвертирован — не делаем работу повторно

    # -y перезаписать, -qscale:a 2 — качество близкое к 192kbps VBR,
    # приемлемо для голоса и не раздувает файл.
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path), "-qscale:a", "2", str(mp3_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[ERROR] {wav_path.name}: {result.stderr.strip()[-300:]}", file=sys.stderr)
        return False
    print(f"[OK] {wav_path.name} -> {mp3_path.name}")
    return True


def run_pass() -> int:
    if not RECORDINGS_DIR.exists():
        print(f"[WARN] {RECORDINGS_DIR} не существует", file=sys.stderr)
        return 0
    converted = 0
    for wav_path in sorted(RECORDINGS_DIR.glob("*.wav")):
        if convert_one(wav_path):
            converted += 1
    return converted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="один проход и выход")
    parser.add_argument("--watch", action="store_true", help="периодически опрашивать папку")
    parser.add_argument("--interval", type=int, default=5, help="секунды между опросами в режиме --watch")
    args = parser.parse_args()

    if args.watch:
        print(f"Слежу за {RECORDINGS_DIR}, интервал {args.interval}с. Ctrl+C для выхода.")
        try:
            while True:
                run_pass()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass
    else:
        # --once по умолчанию тоже сработает, даже если флаг не передан —
        # простой единоразовый запуск самый частый сценарий использования.
        n = run_pass()
        print(f"Готово. Сконвертировано файлов: {n}")


if __name__ == "__main__":
    main()
