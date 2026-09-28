"""События звонка: JSON Lines в sessions.log + доставка в Backend (webhook).

sessions.log пишется всегда и первым — это журнал и буфер: если Backend
недоступен, события не теряются и их можно дозалить из файла.
Доставка в Backend — в фоновом потоке с повторами, чтобы медленный или
упавший Backend не тормозил голосовой цикл.

Формат доставки (BACKEND_EVENTS_FORMAT):
  raw     — событие как в SSE (call.started, call.utterance…), для заглушки mocks;
  backend — контракт backend/docs/INTEGRATION.md §2.2: только смена статуса вызова
            (ringing / answered / missed / ended / failed), id занятия и попытки,
            длительность, запись; остальное — в meta. Заголовок X-Telephony-Token.
"""

import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .clients import ServiceError, post_json

log = logging.getLogger("virtual_caller.events")

RETRY_DELAYS_SEC = (0.5, 1.0, 2.0, 5.0)
# Событие телефонии -> статус вызова в Backend; остальные события Backend не нужны
BACKEND_EVENTS = {"call.dialing": "ringing", "call.started": "answered", "call.ended": "ended",
                  "call.failed": "failed"}
MISSED_REASONS = ("no_answer", "busy", "timeout")
BACKEND_ID_FIELDS = ("lesson_id", "attempt_id", "student_id")
META_FIELDS = ("session_id", "scenario_id", "call_type", "trainee", "direction", "dialed", "reason",
               "persona", "card_id", "transcript")


def to_backend_event(record: dict, backend_ids: dict | None) -> dict | None:
    """Событие телефонии -> тело POST /api/v1/telephony/events (None — Backend не интересно)."""
    status = BACKEND_EVENTS.get(record.get("event"))
    if status is None:
        return None
    if status == "failed" and record.get("reason") in MISSED_REASONS:
        status = "missed"
    persona_number = (record.get("persona") or {}).get("number")
    trainee = record.get("trainee")
    inbound = record.get("direction") == "inbound" or record.get("dialed")
    body = {
        "sip_call_id": record.get("call_id"),
        "event": status,
        **{k: v for k, v in (backend_ids or {}).items() if k in BACKEND_ID_FIELDS and v},
        # inbound — обучающийся набрал номер сам; outbound — звонит собеседник
        "caller_number": trainee if inbound else persona_number,
        "callee_number": (record.get("dialed") or persona_number) if inbound else trainee,
        "meta": {"telephony_event": record.get("event"),
                 **{k: record[k] for k in META_FIELDS if record.get(k) not in (None, "", [])}},
    }
    if record.get("duration_sec") is not None:
        body["duration_ms"] = int(float(record["duration_sec"]) * 1000)
    if record.get("recording_url"):
        body["audio_path"] = record["recording_url"]
        body["audio_format"] = record["recording_url"].rsplit(".", 1)[-1].lower()
    return body


class EventSink:
    def __init__(self, log_path: Path, backend_url: str = "", timeout: float = 5.0,
                 fmt: str = "raw", token: str = "", backend_ids=None):
        """backend_ids(call_id) -> {"lesson_id", "attempt_id", "student_id"} для формата backend."""
        self.log_path = Path(log_path)
        self.webhook_url = f"{backend_url}/telephony/events" if backend_url else ""
        self.timeout = timeout
        self.fmt = fmt
        self.headers = {"X-Telephony-Token": token} if token else {}
        self.backend_ids = backend_ids or (lambda call_id: None)
        self._file_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=10000)
        # подписчики GET /events (SSE): (фильтр, очередь). Медленный клиент теряет
        # события сверх 1000, но не тормозит звонки.
        self._subscribers: list[tuple[dict, queue.Queue]] = []
        self._sub_lock = threading.Lock()
        if self.webhook_url:
            threading.Thread(target=self._deliver_loop, name="event-webhook", daemon=True).start()

    def emit(self, event: str, **fields) -> dict:
        record = {"event": event, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}
        line = json.dumps(record, ensure_ascii=False)
        with self._file_lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        log.info("event=%s call_id=%s", event, fields.get("call_id", "-"))
        self._publish(record)
        body = record
        if self.fmt == "backend":
            body = to_backend_event(record, self.backend_ids(record.get("call_id")))
        if self.webhook_url and body is not None:
            try:
                self._queue.put_nowait(body)
            except queue.Full:
                log.error("очередь webhook переполнена, событие только в %s", self.log_path)
        return record

    def subscribe(self, filters: dict) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._sub_lock:
            self._subscribers.append((filters, q))
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._sub_lock:
            self._subscribers = [(f, sq) for f, sq in self._subscribers if sq is not q]

    def _publish(self, record: dict) -> None:
        with self._sub_lock:
            subs = list(self._subscribers)
        for filters, q in subs:
            if all(record.get(k) == v for k, v in filters.items() if v):
                try:
                    q.put_nowait(record)
                except queue.Full:
                    pass

    def _deliver_loop(self) -> None:
        while True:
            record = self._queue.get()
            for attempt, delay in enumerate((0.0, *RETRY_DELAYS_SEC)):
                if delay:
                    time.sleep(delay)
                try:
                    post_json(self.webhook_url, record, self.timeout, self.headers)
                    break
                except ServiceError as exc:
                    if attempt == len(RETRY_DELAYS_SEC):
                        log.error("событие %s не доставлено в Backend (%s), есть в %s",
                                  record.get("event"), exc, self.log_path)
            self._queue.task_done()

    def wait_delivered(self, timeout: float = 5.0) -> bool:
        """Для тестов: дождаться доставки всех событий из очереди."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return False
