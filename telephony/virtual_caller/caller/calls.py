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
    direction: str                 # outbound (API звонит обучающемуся) | inbound (обучающийся набрал 7xx)
    trainee: str | None = None     # SIP-аккаунт обучающегося
    channel: str | None = None     # имя канала Asterisk (для отбоя)
    status: str = "dialing"
    reason: str | None = None
    created_at: float = field(default_factory=time.time)
    answered_at: float | None = None
    ended_at: float | None = None
    recording_url: str | None = None
    transcript: list[dict] = field(default_factory=list)

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
