"""Заглушки ML и Backend для автономной разработки телефонии (stdlib).

Контракты те же, что у настоящих сервисов (telephony/API.md), поэтому при
интеграции меняются только ML_API_URL / BACKEND_URL у virtual-caller.

    GET  /health
    POST /ml/dialogue/turn           следующая реплика собеседника (ml_dialogue.py: правила или LLM)
    GET  /ml/scenarios               список сценариев заглушки
    POST /backend/telephony/events   приём событий звонка (webhook)
    GET  /backend/telephony/events   просмотр принятых: ?call_id=&session_id=&event=&limit=

Логика реплик — в ml_dialogue.py: правила по типу звонка (dispatch, report,
applicant, incident_112) или OpenAI-совместимая LLM (DIALOGUE_ENGINE=llm).
"""

import json
import logging
import os
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ml_dialogue import DialogueError, LLMConfig, dialogue_turn, next_turn  # noqa: F401 (dialogue_turn — для тестов)

log = logging.getLogger("mocks")

SCENARIOS_DIR = Path(os.environ.get("SCENARIOS_DIR", Path(__file__).parent / "scenarios"))
MAX_EVENTS = 5000


class MockError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ------------------------------------------------------------------ ML ---

def load_scenarios(directory: Path = SCENARIOS_DIR) -> dict[str, dict]:
    scenarios = {}
    for path in sorted(Path(directory).glob("*.json")):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        scenarios[data.get("scenario_id", path.stem)] = data
    return scenarios


# ------------------------------------------------------------- Backend ---

class EventStore:
    def __init__(self, maxlen: int = MAX_EVENTS):
        self._events: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, event: dict) -> None:
        with self._lock:
            self._events.append({**event, "received_at": time.time()})

    def query(self, call_id=None, session_id=None, event=None, limit=200) -> list[dict]:
        with self._lock:
            items = list(self._events)
        items = [e for e in items
                 if (not call_id or e.get("call_id") == call_id)
                 and (not session_id or e.get("session_id") == session_id)
                 and (not event or e.get("event") == event)]
        return items[-limit:]


# ---------------------------------------------------------------- HTTP ---

class MockHandler(BaseHTTPRequestHandler):
    scenarios: dict[str, dict] = {}
    store: EventStore
    llm: LLMConfig | None = None
    server_version = "telephony-mocks/1.0"

    def _json(self, status: HTTPStatus, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MockError(HTTPStatus.BAD_REQUEST, f"невалидный JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise MockError(HTTPStatus.BAD_REQUEST, "ожидается JSON-объект")
        return data

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method: str) -> None:
        url = urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        try:
            status, data = self._route(method, path, parse_qs(url.query))
        except MockError as exc:
            status, data = exc.status, {"error": exc.message}
        self._json(status, data)

    def _route(self, method: str, path: str, query: dict):
        q = {k: v[0] for k, v in query.items()}
        if method == "GET" and path in ("/health", "/ml/health", "/backend/health"):
            return HTTPStatus.OK, {"status": "ok", "scenarios": sorted(self.scenarios),
                                   "dialogue_engine": f"llm:{self.llm.model}@{self.llm.api_url}" if self.llm else "rules"}
        if method == "GET" and path == "/ml/scenarios":
            return HTTPStatus.OK, [{"scenario_id": k, "title": v.get("title")} for k, v in self.scenarios.items()]
        if method == "POST" and path == "/ml/dialogue/turn":
            req = self._read_json()
            try:
                reply = next_turn(req, self.scenarios, self.llm)
            except DialogueError as exc:
                raise MockError(HTTPStatus.NOT_FOUND, str(exc)) from exc
            log.info("ML %s call_id=%s turn=%s оператор=%r -> %r end=%s [%s]", req.get("call_type"),
                     req.get("call_id"), req.get("turn"), req.get("operator_text"), reply["reply_text"],
                     reply["end_call"], reply.get("engine"))
            return HTTPStatus.OK, reply
        if path == "/backend/telephony/events":
            if method == "POST":
                event = self._read_json()
                self.store.add(event)
                log.info("Backend <- %s call_id=%s", event.get("event"), event.get("call_id"))
                return HTTPStatus.OK, {"accepted": True}
            limit = int(q.get("limit", "200"))
            return HTTPStatus.OK, self.store.query(q.get("call_id"), q.get("session_id"), q.get("event"), limit)
        raise MockError(HTTPStatus.NOT_FOUND, f"нет маршрута {method} {path}")

    def log_message(self, fmt, *args):
        pass


def make_server(host: str, port: int, scenarios: dict | None = None,
                store: EventStore | None = None, llm: LLMConfig | None = None) -> ThreadingHTTPServer:
    attrs = {"scenarios": scenarios if scenarios is not None else load_scenarios(),
             "store": store or EventStore(), "llm": llm}
    server = ThreadingHTTPServer((host, port), type("BoundMockHandler", (MockHandler,), attrs))
    server.daemon_threads = True
    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    host = os.environ.get("LISTEN_HOST", "0.0.0.0")
    port = int(os.environ.get("LISTEN_PORT", "8093"))
    llm = LLMConfig.from_env()
    server = make_server(host, port, llm=llm)
    log.info("mocks слушают %s:%d: ML /ml (%s), Backend /backend, сценарии: %s", host, port,
             f"LLM {llm.model} @ {llm.api_url}" if llm else "правила",
             ", ".join(sorted(server.RequestHandlerClass.scenarios)))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
