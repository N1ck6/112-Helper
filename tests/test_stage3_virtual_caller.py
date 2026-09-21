"""
Тест этапа 3 — виртуальный абонент реально обрабатывает звонок и
пишет запись в sessions.log с правильным scenario_id.

Запуск:
    docker compose -f telephony/docker-compose.yml up --build -d
    pytest tests/test_stage3_virtual_caller.py -v

Ограничение теста (честно, по-русски): Local-канал держим на связи
Application=Wait,2 — этого достаточно, чтобы AGI успел прочитать
окружение и залогировать call_started, но НЕ гарантирует, что весь
сценарий доиграется до конца (для этого нужен реальный/более длинный
звонок — см. ручную проверку в README этапа 3). Тест проверяет именно
факт связки звонка со сценарием, а не полное воспроизведение.
"""

import json
import time
from pathlib import Path

from conftest import REPO_ROOT

SESSIONS_LOG = REPO_ROOT / "data" / "stage3" / "sessions" / "sessions.log"


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def test_scenario_call_is_logged(ami_stage3):
    lines_before = _read_lines(SESSIONS_LOG)

    ami_stage3.originate_and_wait_hangup(
        channel="Local/700@internal",
        Application="Wait",
        Data="2",
        timeout_s=20.0,
    )

    # Файл пишется процессом virtual_caller асинхронно относительно
    # нашего Originate — даём ему до 5 секунд догнать запись на диск.
    new_records = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        lines_after = _read_lines(SESSIONS_LOG)
        new_lines = lines_after[len(lines_before):]
        new_records = [json.loads(line) for line in new_lines if line.strip()]
        if any(r.get("event") == "call_started" for r in new_records):
            break
        time.sleep(0.5)

    assert SESSIONS_LOG.exists(), (
        f"{SESSIONS_LOG} не найден — проверьте, что volume в "
        f"docker-compose.yml этапа 3 смонтирован (../../data/stage3/sessions)"
    )
    started = [r for r in new_records if r.get("event") == "call_started"]
    assert started, f"Не нашли событие call_started после звонка. Новые записи: {new_records}"
    assert started[-1]["scenario_id"] == "scenario_001", (
        f"Ожидали scenario_id=scenario_001, получили: {started[-1]}"
    )
    assert "session_id" in started[-1], "call_started без session_id — связка сломана"
