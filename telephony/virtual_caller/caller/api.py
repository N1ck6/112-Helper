"""HTTP API телефонии для Frontend и Backend. Контракт — telephony/API.md.

    GET    /health                       состояние AMI и voice-service
    GET    /directory                    справочник служб (номера для набора)
    GET    /numbers                      телефонная книга: службы + 3000, 700, 701, 600
    GET    /endpoints                    SIP-аккаунты рабочих мест: регистрация и статус оператора
    PUT    /trainees/{trainee}/context   какая карточка открыта на рабочем месте
    GET    /trainees/{trainee}/context
    DELETE /trainees/{trainee}/context
    PUT    /trainees/{trainee}/status    {"available": true|false} — статус оператора из АРМ
    GET    /trainees/{trainee}/status
    POST   /calls                        учебный звонок (dispatch | report | applicant | incident_112) -> 202
                                         или {"dial": "2101"} — набор номера с панели телефона
    GET    /calls[?trainee=&session_id=] последние звонки
    GET    /calls/{call_id}              статус, расшифровка, запись
    POST   /calls/{call_id}/hangup       завершить звонок
    GET    /events[?trainee=&session_id=&call_id=]  поток событий (Server-Sent Events)

CORS разрешён (CORS_ORIGINS): frontend обращается к API прямо из браузера.
"""

import json
import logging
import queue
import re
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .ami import AMIClient, AMIError
from .calls import ACTIVE, Call, CallRegistry, TraineeContexts
from .clients import VoiceClient, reachable
from .config import Settings
from .directory import APPLICANT, CALL_TYPES, DISPATCH, INCIDENT_112, REPORT, Directory
from .dialogue import APPLICANT_112
from .events import EventSink

log = logging.getLogger("virtual_caller.api")

ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# Канал задаётся явно только для тестов/особых случаев: PJSIP/<аккаунт> или Local/<exten>@<context>
CHANNEL_RE = re.compile(r"^(PJSIP/[A-Za-z0-9_.-]{1,64}|Local/[A-Za-z0-9_.-]{1,64}@[A-Za-z0-9_-]{1,64})$")
CALL_PATH_RE = re.compile(r"^/calls/([A-Za-z0-9_.-]{1,64})(/hangup)?$")
TRAINEE_PATH_RE = re.compile(r"^/trainees/([A-Za-z0-9_.-]{1,64})/(context|status)$")
DIAL_RE = re.compile(r"^[0-9]{2,6}$")
RUN_CONTEXT = "training-run"  # см. extensions.conf
DIAL_CONTEXT = "internal"     # контекст телефонов рабочих мест: набор с панели = набор с трубки
CHANNEL_POLL_SEC = 2
# Входящие рабочему месту от системы/преподавателя: не идут оператору со статусом «недоступен»
INCOMING_TYPES = (REPORT, INCIDENT_112)
SSE_HEARTBEAT_SEC = 15
# Что видит обучающийся на экране телефона при входящем звонке
CALLER_ID_FMT = {
    DISPATCH: '"{service}" <{number}>',                  # набор службы из UI: «звоним в …»
    REPORT: '"{position} ({service})" <{number}>',         # доклад старшего группы
    APPLICANT: '"Заявитель: {name}" <{number}>',
}


def _caller_id(fmt: str, persona: dict) -> str:
    safe = {k: str(v or "").replace('"', "'") for k, v in persona.items()}
    number = re.sub(r"[^0-9+]", "", safe.get("number", "")) or "700"
    return fmt.format(**{**safe, "number": number})


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class CallControl:
    """Логика API без HTTP — отдельно, чтобы тестировать без сокетов."""

    def __init__(self, settings: Settings, registry: CallRegistry, events: EventSink,
                 ami: AMIClient, voice: VoiceClient, directory: Directory | None = None,
                 contexts: TraineeContexts | None = None):
        self.s = settings
        self.registry = registry
        self.events = events
        self.ami = ami
        self.voice = voice
        self.directory = directory or Directory([])
        self.contexts = contexts or TraineeContexts()

    def health(self) -> tuple[HTTPStatus, dict]:
        ami_ok = self.ami.ping()
        voice_ok = self.voice.health()
        # без ML собеседник не отвечает — звонок сразу завершается фразой о неполадке
        ml_ok = reachable(self.s.ml_api_url)
        backend_ok = reachable(self.s.backend_url) if self.s.backend_url else None
        body = {
            "status": "ok" if ami_ok and voice_ok and ml_ok else "degraded",
            "ami": ami_ok,
            "voice_service": voice_ok,
            "ml": ml_ok,
            "backend": backend_ok,
            "ml_api_url": self.s.ml_api_url,
            "backend_url": self.s.backend_url or None,
            "directory_contacts": len(self.directory.contacts),
            "active_calls": sum(1 for c in self.registry.list() if c.status in ACTIVE),
        }
        return (HTTPStatus.OK if ami_ok else HTTPStatus.SERVICE_UNAVAILABLE), body

    # --- контекст рабочего места -----------------------------------------
    def set_context(self, trainee: str, payload: dict) -> dict:
        card = payload.get("card")
        if card is not None and not isinstance(card, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "card должен быть объектом")
        session_id = payload.get("session_id")
        if session_id is not None and not ID_RE.match(str(session_id)):
            raise ApiError(HTTPStatus.BAD_REQUEST, "session_id: [A-Za-z0-9_.-], до 64 символов")
        return self.contexts.set(trainee, {"session_id": session_id, "card": card})

    def get_context(self, trainee: str) -> dict:
        ctx = self.contexts.get(trainee)
        if ctx is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"у {trainee} нет открытой карточки")
        return ctx

    def set_status(self, trainee: str, payload: dict) -> dict:
        if not isinstance(payload.get("available"), bool):
            raise ApiError(HTTPStatus.BAD_REQUEST, 'нужно {"available": true|false}')
        item = self.contexts.set_available(trainee, payload["available"])
        self.events.emit("operator.status", trainee=trainee, available=item["available"])
        return item

    # --- звонки ---------------------------------------------------------
    def _channel_for(self, payload: dict) -> tuple[str | None, str]:
        trainee = payload.get("trainee")
        channel = payload.get("channel")
        if trainee is not None and not ID_RE.match(str(trainee)):
            raise ApiError(HTTPStatus.BAD_REQUEST, "trainee: [A-Za-z0-9_.-], до 64 символов")
        if channel:
            if not CHANNEL_RE.match(str(channel)):
                raise ApiError(HTTPStatus.BAD_REQUEST, "channel: PJSIP/<аккаунт> или Local/<exten>@<context>")
        elif trainee:
            channel = f"PJSIP/{trainee}"
        else:
            raise ApiError(HTTPStatus.BAD_REQUEST, "нужен trainee (SIP-аккаунт рабочего места)")
        return (str(trainee) if trainee else None), str(channel)

    def start_call(self, payload: dict) -> Call:
        if payload.get("dial") is not None:
            return self.dial(payload)
        call_type = str(payload.get("call_type") or INCIDENT_112)
        if call_type not in CALL_TYPES:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"call_type: {' | '.join(CALL_TYPES)}")
        trainee, channel = self._channel_for(payload)
        # вызов «от системы» (доклад, вызов 112) не идёт оператору на паузе;
        # звонок, который обучающийся запустил сам кнопкой, — идёт
        if (call_type in INCOMING_TYPES and payload.get("initiated_by") != "trainee"
                and not self.contexts.available(trainee)):
            raise ApiError(HTTPStatus.CONFLICT, f"оператор {trainee} недоступен (статус «недоступен» в АРМ)")

        workplace = self.contexts.get(trainee) or {}
        card = payload.get("card") if isinstance(payload.get("card"), dict) else workplace.get("card")
        session_id = str(payload.get("session_id") or workplace.get("session_id") or uuid.uuid4())
        if not ID_RE.match(session_id):
            raise ApiError(HTTPStatus.BAD_REQUEST, "session_id: [A-Za-z0-9_.-], до 64 символов")
        scenario_id = str(payload.get("scenario_id") or "")
        if scenario_id and not ID_RE.match(scenario_id):
            raise ApiError(HTTPStatus.BAD_REQUEST, "scenario_id: [A-Za-z0-9_.-], до 64 символов")

        persona, report = None, None
        if call_type in (DISPATCH, REPORT):
            ref = payload.get("contact") or payload.get("service")
            contact = self.directory.resolve(ref)
            if contact is None:
                raise ApiError(HTTPStatus.NOT_FOUND, f"служба не найдена в справочнике: {ref!r} (GET /directory)")
            persona = Directory.persona(contact, call_type)
            if call_type == REPORT:
                report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
        elif call_type == APPLICANT:
            persona = Directory.applicant(card)
        elif not scenario_id:
            raise ApiError(HTTPStatus.BAD_REQUEST, "для incident_112 нужен scenario_id")
        else:
            persona = dict(APPLICANT_112)

        call = self.registry.add(Call(call_id=uuid.uuid4().hex, session_id=session_id, scenario_id=scenario_id,
                                      direction="outbound", trainee=trainee,
                                      call_type=call_type, persona=persona, card=card, report=report))
        self.events.emit("call.dialing", call_id=call.call_id, session_id=session_id, scenario_id=scenario_id,
                         call_type=call_type, trainee=call.trainee, channel=channel,
                         persona=persona and {k: persona.get(k) for k in ("service", "name", "position", "number")})
        threading.Thread(target=self._originate, args=(call, channel), daemon=True,
                         name=f"originate-{call.call_id[:8]}").start()
        return call

    def _originate(self, call: Call, channel: str) -> None:
        variables = {"SCENARIO_ID": call.scenario_id, "SESSION_ID": call.session_id,
                     "CALL_TYPE": call.call_type}
        if call.call_type in (DISPATCH, APPLICANT):
            # обучающийся сам «звонит» кнопкой в UI: после ответа слышит гудки, затем собеседника
            variables["RINGBACK_SEC"] = str(self.s.ringback_sec)
        fmt = CALLER_ID_FMT.get(call.call_type)
        caller_id = _caller_id(fmt, call.persona) if fmt and call.persona else self.s.outbound_caller_id
        try:
            outcome = self.ami.originate(
                call_id=call.call_id, channel=channel, context=RUN_CONTEXT, variables=variables,
                caller_id=caller_id, ring_timeout_sec=self.s.ring_timeout_sec,
                on_channel=lambda name: self.registry.update(call.call_id, channel=name))
        except (OSError, AMIError) as exc:
            log.error("originate call_id=%s: %s", call.call_id, exc)
            outcome = "ami_error"
        if outcome == "answered":
            return  # дальше звонок ведёт AGI (DialogueRunner), он же пришлёт call.started/call.ended
        self._fail(call, outcome)

    # --- набор номера с панели телефона (click-to-dial) --------------------
    def dial(self, payload: dict) -> Call:
        """Телефон рабочего места звонит, трубку сняли — Asterisk набирает номер.

        Дальше всё как при наборе с трубки: 2XXX — служба, 3000 — заявитель,
        700/701 — вызов 112, 600 — эхо-тест, прочее — «номер не обслуживается».
        """
        number = str(payload.get("dial") or "").strip()
        if not DIAL_RE.match(number):
            raise ApiError(HTTPStatus.BAD_REQUEST, "dial: номер из 2–6 цифр")
        trainee, channel = self._channel_for(payload)
        workplace = self.contexts.get(trainee) or {}
        session_id = str(payload.get("session_id") or workplace.get("session_id") or uuid.uuid4())
        if not ID_RE.match(session_id):
            raise ApiError(HTTPStatus.BAD_REQUEST, "session_id: [A-Za-z0-9_.-], до 64 символов")
        target = self.directory.dial_target(number)
        call = self.registry.add(Call(call_id=uuid.uuid4().hex, session_id=session_id,
                                      scenario_id=target.get("scenario_id") or "", direction="inbound",
                                      trainee=trainee, call_type=target["call_type"], persona=target["persona"],
                                      card=workplace.get("card"), dialed=number))
        persona = target["persona"] or {"service": target["title"], "number": number}
        self.events.emit("call.dialing", call_id=call.call_id, session_id=session_id, scenario_id=call.scenario_id,
                         call_type=call.call_type, trainee=trainee, channel=channel, dialed=number,
                         persona={k: persona.get(k) for k in ("service", "name", "position", "number")})
        threading.Thread(target=self._originate_dial, args=(call, channel, target["handled_by_agi"]),
                         daemon=True, name=f"dial-{call.call_id[:8]}").start()
        return call

    def _originate_dial(self, call: Call, channel: str, handled_by_agi: bool) -> None:
        variables = {"SESSION_ID": call.session_id}
        if call.trainee:
            variables["TRAINEE"] = call.trainee  # для Local-каналов автотестов: чья карточка
        try:
            outcome = self.ami.originate(
                call_id=call.call_id, channel=channel, context=DIAL_CONTEXT, exten=call.dialed,
                variables=variables, caller_id=f'"Набор {call.dialed}" <{call.dialed}>',
                ring_timeout_sec=self.s.ring_timeout_sec,
                on_channel=lambda name: self.registry.update(call.call_id, channel=name))
        except (OSError, AMIError) as exc:
            log.error("dial call_id=%s: %s", call.call_id, exc)
            outcome = "ami_error"
        if outcome != "answered":
            self._fail(call, outcome)
            return
        if handled_by_agi:
            return  # AGI пришлёт call.started / call.ended
        self._watch_channel(call)

    def _watch_channel(self, call: Call) -> None:
        """Эхо-тест и прочие номера без собеседника: события — по жизни канала."""
        current = self.registry.update(call.call_id, status="in_progress", answered_at=time.time())
        self.events.emit("call.started", call_id=call.call_id, session_id=call.session_id, scenario_id="",
                         call_type=call.call_type, trainee=call.trainee, direction="inbound",
                         channel=current.channel if current else None, dialed=call.dialed, persona=None)
        started = time.monotonic()
        while time.monotonic() - started < self.s.max_call_sec:
            time.sleep(CHANNEL_POLL_SEC)
            name = (self.registry.get(call.call_id) or call).channel
            try:
                if not name or not self.ami.channel_alive(name):
                    break
            except (OSError, AMIError):
                break
        self.registry.update(call.call_id, status="ended", reason="completed", ended_at=time.time())
        self.events.emit("call.ended", call_id=call.call_id, session_id=call.session_id, scenario_id="",
                         call_type=call.call_type, trainee=call.trainee, reason="completed",
                         duration_sec=round(time.monotonic() - started, 1), recording_url=None,
                         persona=None, transcript=[])

    def _fail(self, call: Call, outcome: str) -> None:
        current = self.registry.get(call.call_id)
        if current and current.status == "dialing":
            self.registry.update(call.call_id, status="failed", reason=outcome, ended_at=time.time())
            self.events.emit("call.failed", call_id=call.call_id, session_id=call.session_id,
                             scenario_id=call.scenario_id, call_type=call.call_type,
                             trainee=call.trainee, reason=outcome)

    def list_calls(self, trainee: str | None = None, session_id: str | None = None) -> list[Call]:
        return [c for c in self.registry.list()
                if (not trainee or c.trainee == trainee) and (not session_id or c.session_id == session_id)]

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
            items = self.ami.endpoints()
        except (OSError, AMIError) as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, f"AMI: {exc}") from exc
        return [{**e, "available": self.contexts.available(e.get("endpoint"))} for e in items]


class ApiHandler(BaseHTTPRequestHandler):
    control: CallControl  # проставляется в make_api_server()
    server_version = "virtual-caller/1.1"
    protocol_version = "HTTP/1.1"

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.control.s.cors_origins)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: HTTPStatus, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 256 * 1024:
            raise ApiError(HTTPStatus.BAD_REQUEST, "нужно JSON-тело до 256 КБ")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"невалидный JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "ожидается JSON-объект")
        return data

    def do_OPTIONS(self):  # CORS preflight для POST/PUT с JSON
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method: str) -> None:
        started = time.monotonic()
        url = urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if method == "GET" and path == "/events":
            return self._sse(query)
        status = HTTPStatus.OK
        try:
            status, data = self._route(method, path, query)
            self._json(status, data)
        except ApiError as exc:
            status = exc.status
            self.close_connection = True  # тело запроса могло остаться непрочитанным
            self._json(status, {"error": exc.message})
        except Exception as exc:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            log.exception("%s %s", method, path)
            self._json(status, {"error": f"{type(exc).__name__}: {exc}"})
        finally:
            log.info("%s %s -> %d за %.3f с", method, path, int(status), time.monotonic() - started)

    def _route(self, method: str, path: str, query: dict):
        c = self.control
        if method == "GET" and path == "/health":
            return c.health()
        if method == "GET" and path == "/directory":
            return HTTPStatus.OK, c.directory.public()
        if method == "GET" and path == "/numbers":
            return HTTPStatus.OK, c.directory.numbers()
        if method == "GET" and path == "/endpoints":
            return HTTPStatus.OK, c.endpoints()
        if path == "/calls":
            if method == "POST":
                return HTTPStatus.ACCEPTED, c.start_call(self._read_json()).to_dict()
            if method == "GET":
                return HTTPStatus.OK, [x.to_dict() for x in c.list_calls(query.get("trainee"), query.get("session_id"))]
        m = CALL_PATH_RE.match(path)
        if m and method == "GET" and not m.group(2):
            return HTTPStatus.OK, c.get_call(m.group(1)).to_dict()
        if m and method == "POST" and m.group(2):
            return HTTPStatus.ACCEPTED, c.hangup(m.group(1)).to_dict()
        m = TRAINEE_PATH_RE.match(path)
        if m and m.group(2) == "status":
            trainee = m.group(1)
            if method == "PUT":
                return HTTPStatus.OK, c.set_status(trainee, self._read_json())
            if method == "GET":
                return HTTPStatus.OK, {"trainee": trainee, "available": c.contexts.available(trainee)}
        elif m:
            trainee = m.group(1)
            if method == "PUT":
                return HTTPStatus.OK, c.set_context(trainee, self._read_json())
            if method == "GET":
                return HTTPStatus.OK, c.get_context(trainee)
            if method == "DELETE":
                c.contexts.delete(trainee)
                return HTTPStatus.OK, {"deleted": True}
        raise ApiError(HTTPStatus.NOT_FOUND, f"нет маршрута {method} {path}")

    def _sse(self, query: dict) -> None:
        """Server-Sent Events: каждое событие звонка — `data: {json}`; фильтр по trainee/session_id/call_id."""
        filters = {k: query.get(k) for k in ("trainee", "session_id", "call_id")}
        q = self.control.events.subscribe(filters)
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        log.info("SSE подписка %s", {k: v for k, v in filters.items() if v})
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    record = q.get(timeout=SSE_HEARTBEAT_SEC)
                    payload = json.dumps(record, ensure_ascii=False)
                    self.wfile.write(f"event: {record['event']}\ndata: {payload}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # держит соединение через прокси
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.control.events.unsubscribe(q)
            self.close_connection = True

    def log_message(self, fmt, *args):  # access-лог пишется в _handle
        pass


def make_api_server(control: CallControl, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundApiHandler", (ApiHandler,), {"control": control})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
