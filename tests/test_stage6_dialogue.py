"""Этап 6-7 — голосовой цикл и API звонков.

  * unit — без Docker: AGI-протокол, цикл диалога (фейковый канал + логика реплик ML-сервиса),
           реплики заявителя 112, доставка событий, HTTP API звонков с фейковым AMI.
  * integration — к запущенному стенду: POST /calls на Local/operator@autotest
           (имитация диспетчера из extensions.conf) -> полный разговор с ML -> события
           в журнале sessions.log и непустая запись. SKIP, если стенд не поднят.

    pytest tests/test_stage6_dialogue.py -v
"""

import dataclasses
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from conftest import RECORDINGS_DIR, REPO_ROOT, SESSIONS_LOG

sys.path.insert(0, str(REPO_ROOT / "telephony" / "virtual_caller"))

from fakes import SCENARIOS, EventStore, make_backend_server, make_ml_server, ml_dialogue  # noqa: E402
from caller.agi import AGIResponse, AGISession, ChannelHungUp, parse_response  # noqa: E402
from caller.api import CallControl, make_api_server  # noqa: E402
from caller.calls import CallRegistry  # noqa: E402
from caller.clients import DialogueClient, DialogueReply, ServiceError  # noqa: E402
from caller.config import Settings  # noqa: E402
from caller.dialogue import ML_ERROR_TEXT, DialogueRunner, trainee_from_channel  # noqa: E402
from caller.events import EventSink  # noqa: E402

CALL_API_URL = os.environ.get("CALL_API_URL", "http://localhost:8092")


def _http(method: str, url: str, data: dict | None = None, timeout: float = 10):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "null")


def _serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


# ------------------------------------------------------------ фейки ---

class FakeAGI:
    """Канал без Asterisk: оператор «говорит» заранее заданные фразы."""

    def __init__(self, env=None, variables=None, hangup_on_record=None):
        self.env = env or {"agi_uniqueid": "1700000000.1", "agi_network_script": "scenario_001",
                           "agi_channel": "PJSIP/alice-00000001", "agi_callerid": "alice"}
        self.variables = variables or {}
        self.hangup_on_record = hangup_on_record
        self.hungup = False
        self.played: list[str] = []
        self.records = 0

    def read_environment(self):
        return self.env

    def get_variable(self, name):
        return self.variables.get(name)

    def stream_file(self, sound, escape_digits=""):
        self.played.append(sound)
        return AGIResponse(200, 0, None, 8000, "200 result=0 endpos=8000")

    def record_file(self, path, fmt="wav", escape_digits="#", timeout_ms=0, silence_sec=0, beep=False):
        self.records += 1
        if self.hangup_on_record == self.records:
            self.hungup = True
            raise ChannelHungUp("fake hangup")
        return AGIResponse(200, 0, "timeout", 16000, "200 result=0 (timeout) endpos=16000")

    def hangup(self):
        self.hungup = True


class FakeVoice:
    def __init__(self, heard: list[str], tts_fails=False):
        self.heard = list(heard)
        self.tts_fails = tts_fails
        self.synthesized: list[str] = []
        self.voices: list[str] = []

    def synthesize_to_file(self, text, call_id, voice=None):
        if self.tts_fails:
            raise ServiceError("tts down")
        self.synthesized.append(text)
        self.voices.append(voice)
        return f"/tts/cache_{voice}_{len(self.synthesized):02d}"

    def transcribe_file(self, filename, call_id):
        return self.heard.pop(0) if self.heard else ""

    def health(self):
        return True


class MockML:
    """DialogueClient поверх логики реплик ML-сервиса без HTTP."""

    def __init__(self, fail=False):
        self.fail = fail
        self.requests = []

    def next_turn(self, *, session_id, scenario_id, call_id, turn, history, operator_text,
                  call_type="incident_112", persona=None, context=None):
        req = {"session_id": session_id, "scenario_id": scenario_id, "call_id": call_id, "turn": turn,
               "history": history, "operator_text": operator_text, "call_type": call_type,
               "persona": persona, "context": context}
        self.requests.append(req)
        if self.fail:
            raise ServiceError("ml down")
        r = ml_dialogue.next_turn(req, SCENARIOS, None)
        return DialogueReply(r["reply_text"], r["end_call"], r.get("voice"))


class FakeAMI:
    def __init__(self, outcome="answered", ok=True):
        self.outcome = outcome
        self.ok = ok
        self.originated = []
        self.hung = []

    def ping(self):
        return self.ok

    def originate(self, *, call_id, channel, context, variables, caller_id, ring_timeout_sec, on_channel=None,
                  exten="s"):
        if on_channel:
            on_channel(f"{channel}-0001")
        self.originated.append({"call_id": call_id, "channel": channel, "context": context, "variables": variables,
                                "exten": exten, "caller_id": caller_id})
        return self.outcome

    def channel_alive(self, channel):
        return False

    def hangup(self, channel):
        self.hung.append(channel)

    def endpoints(self):
        return [{"endpoint": "alice", "state": "Not in use", "registered": True, "active_channels": ""}]


@pytest.fixture
def settings(tmp_path):
    return dataclasses.replace(Settings.from_env(), sessions_log_path=tmp_path / "sessions.log",
                               backend_url="", max_turns=8, recordings_base_url="http://rec")


def _runner(settings, voice, ml, registry=None):
    registry = registry or CallRegistry()
    events = EventSink(settings.sessions_log_path)
    return DialogueRunner(settings, voice, ml, events, registry), registry


def _events(settings):
    return [json.loads(line) for line in settings.sessions_log_path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------- AGI ---

def test_parse_response():
    r = parse_response("200 result=1 (abc) endpos=1600")
    assert (r.code, r.result, r.data, r.endpos) == (200, 1, "abc", 1600)
    assert parse_response("200 result=-1 endpos=0").result == -1


def test_agi_session_env_and_dead_channel():
    incoming = io.BytesIO(b"agi_uniqueid: 42.1\nagi_network_script: scenario_002\n\n"
                          b"200 result=-1 endpos=0\n511 Command Not Permitted on a dead channel\n")
    out = io.BytesIO()
    agi = AGISession(incoming, out)
    assert agi.read_environment()["agi_network_script"] == "scenario_002"
    with pytest.raises(ChannelHungUp):
        agi.stream_file("/tts/x")      # -1 -> CHANNEL STATUS -> 511
    assert agi.hungup
    assert out.getvalue().decode() == 'STREAM FILE /tts/x ""\nCHANNEL STATUS\n'


def test_agi_hangup_notification_line():
    agi = AGISession(io.BytesIO(b"HANGUP\n200 result=-1 endpos=0\n"), io.BytesIO())
    with pytest.raises(ChannelHungUp):
        agi.stream_file("/tts/x")      # строка HANGUP -> канал мёртв без лишних команд
    agi.hangup()                       # на мёртвом канале не бросает


def test_agi_missing_file_is_not_hangup():
    agi = AGISession(io.BytesIO(b"200 result=-1 endpos=0\n200 result=6\n"), io.BytesIO())
    assert agi.stream_file("/tts/missing").result == -1
    assert not agi.hungup


def test_agi_record_file_command_format():
    agi = AGISession(io.BytesIO(b"200 result=0 (timeout) endpos=8000\n"), io.BytesIO())
    resp = agi.record_file("/recordings/c_op00", "wav", "#", 20000, silence_sec=3)
    assert resp.endpos == 8000
    assert agi.wfile.getvalue() == b'RECORD FILE /recordings/c_op00 wav "#" 20000 0 s=3\n'


def test_trainee_from_channel():
    assert trainee_from_channel("PJSIP/alice-0000000a") == "alice"
    assert trainee_from_channel("Local/700@internal-0001;2") is None


# ------------------------------------------------ реплики заявителя 112 ---

def test_caller_112_conversation_flow():
    sc = SCENARIOS["scenario_001"]
    assert ml_dialogue.dialogue_turn(sc, 0, [], None)["reply_text"] == sc["opening"]
    # закрытие без адреса — абонент сам напоминает адрес и не кладёт трубку
    r = ml_dialogue.dialogue_turn(sc, 1, [{"role": "caller", "text": sc["opening"]}], "Бригада выехала")
    assert r["end_call"] is False and "Ленина" in r["reply_text"]
    # спросили адрес и сообщили о выезде -> прощание
    r = ml_dialogue.dialogue_turn(sc, 1, [], "Назовите адрес. Бригада уже выехала")
    assert r["end_call"] is True and r["reply_text"].endswith(sc["closing"])


def test_caller_112_silence_and_fallback():
    sc = SCENARIOS["scenario_001"]
    history = [{"role": "caller", "text": sc["opening"]}, {"role": "operator", "text": ""}]
    assert ml_dialogue.dialogue_turn(sc, 1, history, "") == {"reply_text": sc["silence"], "end_call": False}
    history += [{"role": "caller", "text": sc["silence"]}, {"role": "operator", "text": ""}]
    assert ml_dialogue.dialogue_turn(sc, 2, history, "")["end_call"] is True
    assert ml_dialogue.dialogue_turn(sc, 1, [], "бла бла")["reply_text"] == sc["fallbacks"][0]
    assert ml_dialogue.dialogue_turn(sc, sc["max_turns"] - 1, [], "адрес")["end_call"] is True


# ----------------------------------------------------- голосовой цикл ---

def test_dialogue_full_conversation(settings):
    voice = FakeVoice(["Где вы находитесь?", "Есть пострадавшие?", "Принято, бригада выехала"])
    ml = MockML()
    runner, registry = _runner(settings, voice, ml)
    agi = FakeAGI(variables={"SESSION_ID": "sess-1", "CALL_TYPE": "incident_112"})

    assert runner.handle(agi) == "completed"
    assert agi.hungup and agi.records == 3
    assert voice.synthesized[0] == SCENARIOS["scenario_001"]["opening"]
    assert agi.played[0] == "/tts/cache_female_01" and voice.voices[0] == "female"
    # ML получает историю, включая последнюю реплику оператора
    assert ml.requests[1]["history"][-1] == {"role": "operator", "text": "Где вы находитесь?"}

    call = registry.get("1700000000.1")
    assert call.status == "ended" and call.session_id == "sess-1" and call.direction == "inbound"
    assert call.trainee == "alice" and len(call.transcript) == 7

    events = _events(settings)
    assert [e["event"] for e in events][0] == "call.started"
    ended = events[-1]
    assert ended["event"] == "call.ended" and ended["reason"] == "completed"
    assert ended["recording_url"] == "http://rec/1700000000.1.wav"
    assert ended["transcript"][-1]["text"].endswith(SCENARIOS["scenario_001"]["closing"])


def test_dialogue_operator_hangup(settings):
    runner, registry = _runner(settings, FakeVoice(["адрес"]), MockML())
    agi = FakeAGI(hangup_on_record=1)
    assert runner.handle(agi) == "operator_hangup"
    assert registry.get("1700000000.1").reason == "operator_hangup"


def test_dialogue_ml_down_ends_call(settings):
    """ML недоступен: собеседник не молчит до отбоя, а говорит о неполадке и кладёт трубку."""
    voice = FakeVoice([])
    runner, _ = _runner(settings, voice, MockML(fail=True))
    agi = FakeAGI()
    assert runner.handle(agi) == "ml_error"
    assert voice.synthesized == [ML_ERROR_TEXT] and agi.hungup
    assert any(e["event"] == "call.error" and e["stage"] == "ml" for e in _events(settings))


def test_dialogue_tts_down_plays_fallback(settings):
    runner, _ = _runner(settings, FakeVoice(["адрес, бригада выехала"], tts_fails=True), MockML())
    agi = FakeAGI()
    assert runner.handle(agi) == "completed"
    assert agi.played == [settings.fallback_sound, settings.fallback_sound]


def test_dialogue_max_turns(settings):
    settings = dataclasses.replace(settings, max_turns=2)
    runner, _ = _runner(settings, FakeVoice(["что-то непонятное"] * 5), MockML())
    assert runner.handle(FakeAGI()) == "max_turns"


def test_dialogue_via_http_ml(settings):
    """Тот же цикл, но ML — по HTTP (контракт POST /dialogue/turn)."""
    server = make_ml_server()
    url = _serve(server)
    try:
        ml = DialogueClient(url, timeout=5)
        runner, _ = _runner(settings, FakeVoice(["Адрес? Бригада выехала"]), ml)
        assert runner.handle(FakeAGI()) == "completed"
    finally:
        server.shutdown()


# ------------------------------------------------------ события в Backend ---

def test_events_delivered_raw(tmp_path):
    store = EventStore()
    server = make_backend_server(store)
    url = _serve(server)
    try:
        sink = EventSink(tmp_path / "s.log", backend_url=f"{url}/backend")
        sink.emit("call.started", call_id="c1", session_id="s1")
        sink.emit("call.ended", call_id="c1", session_id="s1", reason="completed")
        assert sink.wait_delivered(5)
        assert [e["event"] for e in store.query("c1")] == ["call.started", "call.ended"]
        assert len((tmp_path / "s.log").read_text(encoding="utf-8").splitlines()) == 2
    finally:
        server.shutdown()


def test_events_logged_when_backend_down(tmp_path):
    sink = EventSink(tmp_path / "s.log", backend_url="http://127.0.0.1:9", timeout=0.2)
    sink.emit("call.started", call_id="c1")
    assert "call.started" in (tmp_path / "s.log").read_text(encoding="utf-8")


# ------------------------------------------------------ API звонков ---

@pytest.fixture
def call_api(settings):
    def start(ami):
        registry = CallRegistry()
        control = CallControl(settings, registry, EventSink(settings.sessions_log_path), ami, FakeVoice([]))
        server = make_api_server(control, "127.0.0.1", 0)
        servers.append(server)
        return _serve(server), registry
    servers = []
    yield start
    for s in servers:
        s.shutdown()


def _wait(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_api_start_call_answered(call_api):
    ami = FakeAMI("answered")
    url, registry = call_api(ami)
    status, call = _http("POST", f"{url}/calls", {"scenario_id": "scenario_001", "trainee": "alice",
                                                  "session_id": "sess-9"})
    assert status == 202 and call["status"] == "dialing" and call["session_id"] == "sess-9"
    assert _wait(lambda: ami.originated)
    o = ami.originated[0]
    assert o["channel"] == "PJSIP/alice" and o["context"] == "training-run"
    assert o["variables"] == {"SCENARIO_ID": "scenario_001", "SESSION_ID": "sess-9", "CALL_TYPE": "incident_112"}
    assert o["call_id"] == call["call_id"]
    status, got = _http("GET", f"{url}/calls/{call['call_id']}")
    assert status == 200 and got["channel"] == "PJSIP/alice-0001"
    # ответили -> статус ведёт AGI; API не должен пометить звонок failed
    assert registry.get(call["call_id"]).status == "dialing"


def test_api_start_call_no_answer(call_api, settings):
    url, registry = call_api(FakeAMI("no_answer"))
    _, call = _http("POST", f"{url}/calls", {"scenario_id": "scenario_002", "trainee": "bob"})
    assert _wait(lambda: registry.get(call["call_id"]).status == "failed")
    assert registry.get(call["call_id"]).reason == "no_answer"
    assert any(e["event"] == "call.failed" for e in _events(settings))


@pytest.mark.parametrize("payload", [
    {"trainee": "alice"},
    {"scenario_id": "../etc", "trainee": "alice"},
    {"scenario_id": "scenario_001"},
    {"scenario_id": "scenario_001", "channel": "SIP/evil;rm"},
    {"scenario_id": "scenario_001", "trainee": "alice", "session_id": "a b"},
])
def test_api_validation(call_api, payload):
    url, _ = call_api(FakeAMI())
    assert _http("POST", f"{url}/calls", payload)[0] == 400


def test_api_hangup_and_errors(call_api):
    ami = FakeAMI("answered")
    url, registry = call_api(ami)
    assert _http("GET", f"{url}/calls/nope")[0] == 404
    _, call = _http("POST", f"{url}/calls", {"scenario_id": "scenario_001", "trainee": "alice"})
    assert _wait(lambda: registry.get(call["call_id"]).channel)
    assert _http("POST", f"{url}/calls/{call['call_id']}/hangup")[0] == 202
    assert ami.hung == ["PJSIP/alice-0001"]
    registry.update(call["call_id"], status="ended")
    assert _http("POST", f"{url}/calls/{call['call_id']}/hangup")[0] == 409


def test_api_health_and_endpoints(call_api):
    url, _ = call_api(FakeAMI(ok=False))
    status, body = _http("GET", f"{url}/health")
    assert status == 503 and body["ami"] is False
    status, eps = _http("GET", f"{url}/endpoints")
    assert status == 200 and eps[0]["endpoint"] == "alice"
    assert _http("GET", f"{url}/calls")[0] == 200


# -------------------------------------------------------- integration ---

@pytest.fixture
def stand():
    try:
        status, health = _http("GET", f"{CALL_API_URL}/health", timeout=5)
    except OSError as exc:
        pytest.skip(f"virtual-caller недоступен ({exc}). Запустите стенд: docker compose --profile llm up -d")
    if status != 200 or not health.get("ml"):
        pytest.fail(f"стенд не готов: virtual-caller {status} {health}")
    return health


def test_integration_outbound_call_full_dialogue(stand):
    """API звонит «диспетчеру» Local/operator@autotest (Playback вместо голоса),
    virtual-caller ведёт диалог с ML-сервисом до конца."""
    status, call = _http("POST", f"{CALL_API_URL}/calls", {
        "scenario_id": "scenario_001", "session_id": f"it-{int(time.time())}",
        "channel": "Local/operator@autotest"})
    assert status == 202, call
    call_id = call["call_id"]

    final = {}
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        _, final = _http("GET", f"{CALL_API_URL}/calls/{call_id}")
        if final["status"] in ("ended", "failed"):
            break
        time.sleep(1)
    assert final["status"] == "ended", final
    roles = [t["role"] for t in final["transcript"]]
    assert roles[:2] == ["caller", "operator"], final["transcript"]
    assert final["transcript"][0]["text"] == SCENARIOS["scenario_001"]["opening"]

    time.sleep(1)
    lines = SESSIONS_LOG.read_text(encoding="utf-8").splitlines() if SESSIONS_LOG.exists() else []
    names = [e["event"] for e in map(json.loads, lines) if e.get("call_id") == call_id]
    assert names[0] == "call.dialing" and "call.started" in names and names[-1] == "call.ended", names

    wav = RECORDINGS_DIR / f"{call_id}.wav"
    assert wav.exists() and wav.stat().st_size > 44 + 8000, f"запись пустая или нет: {wav}"
