"""
Тест этапа 4 — звонок реально порождает WAV-файл с валидным заголовком.

Запуск:
    docker compose -f telephony/docker-compose.yml up --build -d
    pytest tests/test_stage4_audio.py -v
"""

import time
from pathlib import Path

from conftest import REPO_ROOT

RECORDINGS_DIR = REPO_ROOT / "data" / "stage4" / "recordings"


def test_call_produces_valid_wav_recording(ami_stage4):
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    files_before = {p.name for p in RECORDINGS_DIR.glob("*.wav")}

    ami_stage4.originate_and_wait_hangup(
        channel="Local/700@internal",
        Application="Wait",
        Data="2",
        timeout_s=20.0,
    )

    # MixMonitor дописывает/закрывает файл при хануге — даём небольшой запас.
    new_wav = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        files_after = {p.name for p in RECORDINGS_DIR.glob("*.wav")}
        new_files = files_after - files_before
        if new_files:
            new_wav = RECORDINGS_DIR / sorted(new_files)[0]
            break
        time.sleep(0.5)

    assert new_wav is not None, (
        f"После звонка не появилось новых .wav в {RECORDINGS_DIR}. "
        f"Было: {sorted(files_before)}"
    )

    data = new_wav.read_bytes()
    assert len(data) > 44, f"{new_wav.name} меньше минимального WAV-заголовка (44 байта)"
    assert data[0:4] == b"RIFF", f"{new_wav.name} не начинается с 'RIFF' — не похоже на валидный WAV"
    assert data[8:12] == b"WAVE", f"{new_wav.name}: нет маркера 'WAVE' в заголовке"
