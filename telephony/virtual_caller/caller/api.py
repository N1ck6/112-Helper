"""HTTP API управления учебными звонками (для Backend). Контракт — telephony/API.md.

    GET  /health                   состояние AMI и voice-service
    POST /calls                    позвонить обучающемуся по сценарию -> 202 + call_id
    GET  /calls                    последние звонки
    GET  /calls/{call_id}          статус, расшифровка, запись
    POST /calls/{call_id}/hangup   завершить звонок
    GET  /endpoints                SIP-аккаунты и их регистрация
"""

import json
import logging
import re
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .ami import AMIClient, AMIError
from .calls import ACTIVE, Call, CallRegistry
from .clients import VoiceClient
from .config import Settings
from .events import EventSink

log = logging.getLogger("virtual_caller.api")

ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# Канал задаётся явно только для тестов/особых случаев: PJSIP/<аккаунт> или Local/<exten>@<context>
CHANNEL_RE = re.compile(r"^(PJSIP/[A-Za-z0-9_.-]{1,64}|Local/[A-Za-z0-9_.-]{1,64}@[A-Za-z0-9_-]{1,64})$")
CALL_PATH_RE = re.compile(r"^/calls/([A-Za-z0-9_.-]{1,64})(/hangup)?$")
RUN_CONTEXT = "training-run"  # см. extensions.conf


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class CallControl:
    """Логика API без HTTP — отдельно, чтобы тестировать без сокетов."""

    def __init__(self, settings: Settings, registry: CallRegistry, events: EventSink,
                 ami: AMIClient, voice: VoiceClient):
        self.s = settings
        self.registry = registry
        self.events = events
        self.ami = ami
        self.voice = voice

    def health(self) -> tuple[HTTPStatus, dict]:
        ami_ok = self.ami.ping()
        voice_ok = self.voice.health()
        body = {
            "status": "ok" if ami_ok and voice_ok else "degraded",
            "ami": ami_ok,
            "voice_service": voice_ok,
            "ml_api_url": self.s.ml_api_url,
            "backend_url": self.s.backend_url or None,
            "active_calls": sum(1 for c in self.registry.list() if c.status in ACTIVE),
        }
        return (HTTPStatus.OK if ami_ok else HTTPStatus.SERVICE_UNAVAILABLE), body

    def start_call(self, payload: dict) -> Call:
        scenario_id = str(payload.get("scenario_id") or "")
        if not ID_RE.match(scenario_id):
            raise ApiError(HTTPStatus.BAD_REQUEST, "scenario_id обязателен: [A-Za-z0-9_.-], до 64 символов")
        session_id = str(payload.get("session_id") or uuid.uuid4())
        if not ID_RE.match(session_id):
            raise ApiError(HTTPStatus.BAD_REQUEST, "session_id: [A-Za-z0-9_.-], до 64 символов")
        trainee = payload.get("trainee")
        channel = payload.get("channel")
        if channel:
            if not CHANNEL_RE.match(str(channel)):
                raise ApiError(HTTPStatus.BAD_REQUEST, "channel: PJSIP/<аккаунт> или Local/<exten>@<context>")
        elif trainee and ID_RE.match(str(trainee)):
            channel = f"PJSIP/{trainee}"
        else:
            raise ApiError(HTTPStatus.BAD_REQUEST, "нужен trainee (SIP-аккаунт обучающегося)")

        call = self.registry.add(Call(call_id=uuid.uuid4().hex, session_id=session_id,
                                      scenario_id=scenario_id, direction="outbound",
                                      trainee=str(trainee) if trainee else None))
        self.events.emit("call.dialing", call_id=call.call_id, session_id=session_id,
                         scenario_id=scenario_id, trainee=call.trainee, channel=channel)
        threading.Thread(target=self._originate, args=(call, channel), daemon=True,
                         name=f"originate-{call.call_id[:8]}").start()
        return call

    def _originate(self, call: Call, channel: str) -> None:
        try:
            outcome = self.ami.originate(
                call_id=call.call_id, channel=channel, context=RUN_CONTEXT,
                variables={"SCENARIO_ID": call.scenario_id, "SESSION_ID": call.session_id},
                caller_id=self.s.outbound_caller_id, ring_timeout_sec=self.s.ring_timeout_sec,
                on_channel=lambda name: self.registry.update(call.call_id, channel=name))
        except (OSError, AMIError) as exc:
            log.error("originate call_id=%s: %s", call.call_id, exc)
            outcome = "ami_error"
        if outcome == "answered":
            return  # дальше звонок ведёт AGI (DialogueRunner), он же пришлёт call.started/call.ended
        current = self.registry.get(call.call_id)
        if current and current.status == "dialing":
            self.registry.update(call.call_id, status="failed", reason=outcome, ended_at=time.time())
            self.events.emit("call.failed", call_id=call.call_id, session_id=call.session_id,
                             scenario_id=call.scenario_id, trainee=call.trainee, reason=outcome)

    def get_call(self, call_id: str) -> Call:
        call = self.registry.get(call_id)
        if call is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"звонок {call_id} не найден")
        return call

    def hangup(self, call_id: str) -> Call:
        call = self.get_call(call_id)
        if call.status not in ACTIVE:
            raise ApiError(HTTPStatus.CONFLICT, f"звонок уже завершён: {call.status}")
        if not call.channel:
            raise ApiError(HTTPStatus.CONFLICT, "канал ещё не создан, повторите через секунду")
        try:
            self.ami.hangup(call.channel)
        except (OSError, AMIError) as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, f"AMI: {exc}") from exc
        return call

    def endpoints(self) -> list[dict]:
        try:
            return self.ami.endpoints()
        except (OSError, AMIError) as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, f"AMI: {exc}") from exc


class ApiHandler(BaseHTTPRequestHandler):
    control: CallControl  # проставляется в make_api_server()
    server_version = "virtual-caller/1.0"

    def _json(self, status: HTTPStatus, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 64 * 1024:
            raise ApiError(HTTPStatus.BAD_REQUEST, "нужно JSON-тело до 64 КБ")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"невалидный JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "ожидается JSON-объект")
        return data

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method: str) -> None:
        started = time.monotonic()
        path = urlparse(self.path).path.rstrip("/") or "/"
        status = HTTPStatus.OK
        try:
            status, data = self._route(method, path)
            self._json(status, data)
        except ApiError as exc:
            status = exc.status
            self._json(status, {"error": exc.message})
        except Exception as exc:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            log.exception("%s %s", method, path)
            self._json(status, {"error": f"{type(exc).__name__}: {exc}"})
        finally:
            log.info("%s %s -> %d за %.3f с", method, path, int(status), time.monotonic() - started)

    def _route(self, method: str, path: str):
        c = self.control
        if method == "GET" and path == "/health":
            return c.health()
        if path == "/calls":
            if method == "POST":
                return HTTPStatus.ACCEPTED, c.start_call(self._read_json()).to_dict()
            return HTTPStatus.OK, [call.to_dict() for call in c.registry.list()]
        m = CALL_PATH_RE.match(path)
        if m and method == "GET" and not m.group(2):
            return HTTPStatus.OK, c.get_call(m.group(1)).to_dict()
        if m and method == "POST" and m.group(2):
            return HTTPStatus.ACCEPTED, c.hangup(m.group(1)).to_dict()
        if method == "GET" and path == "/endpoints":
            return HTTPStatus.OK, c.endpoints()
        raise ApiError(HTTPStatus.NOT_FOUND, f"нет маршрута {method} {path}")

    def log_message(self, fmt, *args):  # access-лог пишется в _handle
        pass


def make_api_server(control: CallControl, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundApiHandler", (ApiHandler,), {"control": control})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
