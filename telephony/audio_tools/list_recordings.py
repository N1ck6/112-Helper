"""
Показывает список записанных звонков и, если получится, обогащает
каждую запись данными из sessions.log этапа 3 (scenario_id, session_id) —
связка идёт по call_id, который совпадает с именем файла (UNIQUEID
Asterisk без расширения).

Использование:
    python list_recordings.py
"""

import json
from pathlib import Path

RECORDINGS_DIR = Path("/recordings")
SESSIONS_LOG_PATH = Path("/data/sessions.log")


def load_call_index() -> dict:
    """call_id -> {scenario_id, session_id} из call_started событий."""
    index = {}
    if not SESSIONS_LOG_PATH.exists():
        return index
    with SESSIONS_LOG_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") == "call_started":
                index[record["call_id"]] = {
                    "scenario_id": record.get("scenario_id"),
                    "session_id": record.get("session_id"),
                }
    return index


def human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.0f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}TB"


def main():
    if not RECORDINGS_DIR.exists():
        print(f"{RECORDINGS_DIR} не существует — записей ещё нет.")
        return

    call_index = load_call_index()
    wav_files = sorted(RECORDINGS_DIR.glob("*.wav"))

    if not wav_files:
        print("Записей пока нет. Совершите тестовый звонок (см. README этапа 4).")
        return

    print(f"{'call_id':<38} {'wav':<6} {'mp3':<6} {'size':<8} scenario_id / session_id")
    print("-" * 100)
    for wav in wav_files:
        call_id = wav.stem
        mp3_exists = wav.with_suffix(".mp3").exists()
        meta = call_index.get(call_id, {})
        scenario = meta.get("scenario_id", "—")
        session = meta.get("session_id", "—")
        print(
            f"{call_id:<38} {'yes':<6} {'yes' if mp3_exists else 'no':<6} "
            f"{human_size(wav.stat().st_size):<8} {scenario} / {session}"
        )


if __name__ == "__main__":
    main()
