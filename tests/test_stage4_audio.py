"""
Тест этапа 4 — звонок реально порождает WAV-файл с валидным заголовком.

Запуск:
    cd telephony && docker compose up --build -d
    pytest tests/test_stage4_audio.py -v
"""

import time
from pathlib import Path

from conftest import RECORDINGS_DIR


def _full_recordings() -> set[str]:
    """Полные записи MixMonitor (<call_id>.wav), без реплик оператора (<call_id>_opNN.wav)."""
    return {p.name for p in RECORDINGS_DIR.glob("*.wav")
            if "_op" not in p.stem and not p.stem.startswith("response_")}


def test_call_produces_valid_wav_recording(ami):
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    files_before = _full_recordings()

    ami.originate_and_wait_hangup(
        channel="Local/700@internal",
        Application="Wait",
        Data="2",
        timeout_s=20.0,
    )

    # MixMonitor дописывает/закрывает файл при хануге — даём небольшой запас.
    new_wav = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        files_after = _full_recordings()
        new_files = files_after - files_before
        if new_files:
            new_wav = RECORDINGS_DIR / sorted(new_files)[0]
            break
        time.sleep(0.5)

    assert new_wav is not None, (
        f"После звонка не появилось новых .wav в {RECORDINGS_DIR}. "
        f"Было: {sorted(files_before)}"
    )

    # MixMonitor создаёт файл в начале звонка и закрывает (дописывает
    # заголовок и данные) только при отбое — ждём, пока размер перестанет быть 44.
    deadline = time.monotonic() + 10.0
    while new_wav.stat().st_size <= 44 and time.monotonic() < deadline:
        time.sleep(0.5)
    data = new_wav.read_bytes()
    # 44 байта = только заголовок, звука нет (так было с MixMonitor(...,b) у AGI-звонка).
    # Звонок держится ~2 с, 0.1 с PCM16 8 кГц = 1600 байт — с большим запасом.
    assert len(data) > 44 + 1600, f"{new_wav.name}: {len(data)} байт — запись пустая"
    assert data[0:4] == b"RIFF", f"{new_wav.name} не начинается с 'RIFF' — не похоже на валидный WAV"
    assert data[8:12] == b"WAVE", f"{new_wav.name}: нет маркера 'WAVE' в заголовке"
