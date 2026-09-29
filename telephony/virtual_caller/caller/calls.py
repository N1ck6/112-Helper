"""Реестр звонков в памяти: общее состояние для AGI-обработчика и HTTP API.

Хранит последние MAX_CALLS звонков. Долговременная история — в sessions.log
и у Backend (события), здесь только оперативное состояние.
"""

import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field

MAX_CALLS = 500

# Статусы: dialing -> in_progress -> ended  |  dialing -> failed
ACTIVE = ("dialing", "in_progress")
FINAL = ("ended", "failed")


@dataclass
class Call:
    call_id: str
    session_id: str
    scenario_id: str
    direction: str                 # outbound (API звонит обучающемуся) | inbound (обучающийся набрал номер)
    trainee: str | None = None     # SIP-аккаунт рабочего места обучающегося
    call_type: str = "incident_112"  # dispatch | report | applicant | incident_112 (см. directory.py)
    persona: dict | None = None    # собеседник: служба, имя, должность, пол
    card: dict | None = None       # карточка происшествия, по которой звонок
    report: dict | None = None     # для report: {"status": ..., "text": ...}
    dialed: str | None = None      # номер, набранный с панели телефона (POST /calls {"dial"})
    channel: str | None = None     # имя канала Asterisk (для отбоя)
    status: str = "dialing"
    reason: str | None = None
    created_at: float = field(default_factory=time.time)
    answered_at: float | None = None
    ended_at: float | None = None
    recording_url: str | None = None
    transcript: list[dict] = field(default_factory=list)
    backend: dict | None = None      # id занятия / попытки / обучающегося, если звонок поднял Backend

    def to_dict(self) -> dict:
        data = asdict(self)
        end = self.ended_at or time.time()
        data["duration_sec"] = round(end - self.answered_at, 1) if self.answered_at else 0.0
        return data


class CallRegistry:
    def __init__(self):
        self._calls: OrderedDict[str, Call] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, call: Call) -> Call:
        with self._lock:
            self._calls[call.call_id] = call
            while len(self._calls) > MAX_CALLS:
                self._calls.popitem(last=False)
        return call

    def get(self, call_id: str) -> Call | None:
        with self._lock:
            return self._calls.get(call_id)

    def list(self) -> list[Call]:
        with self._lock:
            return list(reversed(self._calls.values()))

    def update(self, call_id: str, **fields) -> Call | None:
        """Меняет поля; финальный статус не откатывается (гонка AMI-события и AGI)."""
        with self._lock:
            call = self._calls.get(call_id)
            if call is None:
                return None
            if call.status in FINAL and fields.get("status") not in (None, call.status):
                fields.pop("status")
                fields.pop("reason", None)
            for k, v in fields.items():
                setattr(call, k, v)
            return call

    def append_turn(self, call_id: str, turn: dict) -> None:
        with self._lock:
            call = self._calls.get(call_id)
            if call is not None:
                call.transcript.append(turn)


class TraineeContexts:
    """Что сейчас открыто на рабочем месте: сессия и карточка.

    Frontend/Backend сообщают это через PUT /trainees/{trainee}/context; звонок,
    который обучающийся набрал сам (2XXX, 3000), получает карточку отсюда.
    """

    def __init__(self):
        self._items: dict[str, dict] = {}
        self._available: dict[str, bool] = {}
        self._lock = threading.Lock()

    # Статус оператора в АРМ («доступен» / «недоступен»): недоступному не идут
    # входящие вызовы от системы/преподавателя (доклады, вызовы 112).
    def set_available(self, trainee: str, available: bool) -> dict:
        with self._lock:
            self._available[trainee] = bool(available)
        return {"trainee": trainee, "available": bool(available)}

    def available(self, trainee: str | None) -> bool:
        with self._lock:
            return self._available.get(trainee, True) if trainee else True

    def set(self, trainee: str, context: dict) -> dict:
        item = {**context, "trainee": trainee, "updated_at": time.time()}
        with self._lock:
            self._items[trainee] = item
        return item

    def get(self, trainee: str | None) -> dict | None:
        if not trainee:
            return None
        with self._lock:
            return self._items.get(trainee)

    def delete(self, trainee: str) -> bool:
        with self._lock:
            return self._items.pop(trainee, None) is not None
