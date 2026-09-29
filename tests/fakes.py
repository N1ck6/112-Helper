"""Тестовые двойники для unit-тестов телефонии (в полном стенде их нет — там настоящие ML и Backend).

  * ml_dialogue — логика реплик ML-сервиса (ml/integration/dialogue.py) без FastAPI;
  * SCENARIOS  — сценарии голосовых вызовов 112 из ML (ml/data/dialogue_scenarios);
  * make_ml_server — HTTP POST /dialogue/turn поверх этой логики;
  * EventStore / make_backend_server — приёмник событий звонка POST .../telephony/events.
"""

import importlib.util
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("ml_integration_dialogue",
                                               REPO_ROOT / "ml" / "integration" / "dialogue.py")
ml_dialogue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ml_dialogue)

SCENARIOS = ml_dialogue.load_scenarios()


class EventStore:
    def __init__(self):
        self.events: list[dict] = []
        self.headers: list[dict] = []
        self._lock = threading.Lock()

    def add(self, event: dict, headers: dict) -> None:
        with self._lock:
            self.events.append(event)
            self.headers.append(headers)

    def query(self, call_id: str | None = None) -> list[dict]:
        with self._lock:
            return [e for e in self.events if not call_id or e.get("call_id", e.get("sip_call_id")) == call_id]


class _Handler(BaseHTTPRequestHandler):
    store: EventStore | None = None
    scenarios: dict = {}
    llm = None

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.endswith("/telephony/events") and self.store is not None:
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            return self._json(HTTPStatus.OK, self.store.query(q.get("call_id")))
        self._json(HTTPStatus.OK, {"status": "ok"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        path = urlparse(self.path).path
        if path.endswith("/telephony/events") and self.store is not None:
            self.store.add(data, dict(self.headers))
            return self._json(HTTPStatus.OK, {"accepted": True})
        if path.endswith("/dialogue/turn"):
            try:
                return self._json(HTTPStatus.OK, ml_dialogue.next_turn(data, self.scenarios, self.llm))
            except ml_dialogue.DialogueError as exc:
                return self._json(HTTPStatus.NOT_FOUND, {"detail": str(exc)})
        self._json(HTTPStatus.NOT_FOUND, {"detail": path})

    def log_message(self, *args):
        pass


def _server(**attrs) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), type("H", (_Handler,), attrs))
    server.daemon_threads = True
    return server


def make_ml_server(scenarios: dict | None = None, llm=None) -> ThreadingHTTPServer:
    return _server(scenarios=SCENARIOS if scenarios is None else scenarios, llm=llm)


def make_backend_server(store: EventStore) -> ThreadingHTTPServer:
    return _server(store=store)
