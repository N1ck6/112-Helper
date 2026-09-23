"""События звонка: JSON Lines в sessions.log + доставка в Backend (webhook).

sessions.log пишется всегда и первым — это журнал и буфер: если Backend
недоступен, события не теряются и их можно дозалить из файла.
Доставка в Backend — в фоновом потоке с повторами, чтобы медленный или
упавший Backend не тормозил голосовой цикл.
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


class EventSink:
    def __init__(self, log_path: Path, backend_url: str = "", timeout: float = 5.0):
        self.log_path = Path(log_path)
        self.webhook_url = f"{backend_url}/telephony/events" if backend_url else ""
        self.timeout = timeout
        self._file_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=10000)
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
        if self.webhook_url:
            try:
                self._queue.put_nowait(record)
            except queue.Full:
                log.error("очередь webhook переполнена, событие только в %s", self.log_path)
        return record

    def _deliver_loop(self) -> None:
        while True:
            record = self._queue.get()
            for attempt, delay in enumerate((0.0, *RETRY_DELAYS_SEC)):
                if delay:
                    time.sleep(delay)
                try:
                    post_json(self.webhook_url, record, self.timeout)
                    break
                except ServiceError as exc:
                    if attempt == len(RETRY_DELAYS_SEC):
                        log.error("событие %s не доставлено в Backend (%s), есть в %s",
                                  record["event"], exc, self.log_path)
            self._queue.task_done()

    def wait_delivered(self, timeout: float = 5.0) -> bool:
        """Для тестов: дождаться доставки всех событий из очереди."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return False
