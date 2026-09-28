"""Полный стенд: телефония <-> Backend <-> ML <-> Frontend (корневой docker-compose.yml).

  * unit — без Docker: события в формате Backend, контракт Backend для звонков
    (/api/v1/calls/originate|hangup), реплики ML совпадают с эталоном телефонии (mocks);
  * integration — к полному стенду (docker compose --profile llm up -d из корня),
    всё через nginx :8080 — как ходит браузер. SKIP без стенда.

    pytest tests/test_stage9_integration.py -v
"""

import dataclasses
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "telephony" / "virtual_caller"))
sys.path.insert(0, str(REPO_ROOT / "telephony" / "mocks"))

import ml_dialogue  # noqa: E402
from caller.api import ApiError, CallControl  # noqa: E402
from caller.calls import CallRegistry, TraineeContexts  # noqa: E402
from caller.config import Settings  # noqa: E402
from caller.directory import Directory  # noqa: E402
from caller.events import EventSink, to_backend_event  # noqa: E402
from test_stage6_dialogue import FakeAMI, FakeVoice, _serve, _wait  # noqa: E402
import mock_services  # noqa: E402

# ml/integration/dialogue.py — без FastAPI (пакет integration тянет роутер)
_spec = importlib.util.spec_from_file_location("ml_integration_dialogue",
                                               REPO_ROOT / "ml" / "integration" / "dialogue.py")
ml_real = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ml_real)

DIRECTORY = Directory.load(REPO_ROOT / "telephony" / "virtual_caller" / "directory.json")
STAND_URL = os.environ.get("STAND_URL", "http://localhost:8080")
LESSON = "3f2c1a4e-0000-4000-8000-000000000001"
ATTEMPT = "3f2c1a4e-0000-4000-8000-000000000002"


# ------------------------------------------------- события -> Backend ---

def test_backend_event_mapping():
    ids = {"lesson_id": LESSON, "attempt_id": ATTEMPT}
    ended = to_backend_event({"event": "call.ended", "call_id": "c1", "session_id": LESSON, "trainee": "ws03",
                              "call_type": "incident_112", "persona": {"number": "112"}, "duration_sec": 41.6,
                              "recording_url": "http://rec/c1.wav", "transcript": [{"role": "caller"}]}, ids)
    assert ended["sip_call_id"] == "c1" and ended["event"] == "ended"
    assert ended["lesson_id"] == LESSON and ended["attempt_id"] == ATTEMPT and "student_id" not in ended
    assert (ended["caller_number"], ended["callee_number"]) == ("112", "ws03")      # звонит собеседник
    assert ended["duration_ms"] == 41600 and ended["audio_format"] == "wav"
    assert ended["meta"]["telephony_event"] == "call.ended" and ended["meta"]["transcript"]

    dialed = to_backend_event({"event": "call.dialing", "call_id": "c2", "trainee": "ws01", "dialed": "2101",
                               "persona": {"number": "2101"}}, None)
    assert dialed["event"] == "ringing" and (dialed["caller_number"], dialed["callee_number"]) == ("ws01", "2101")
    assert to_backend_event({"event": "call.failed", "call_id": "c3", "reason": "no_answer"}, None)["event"] == "missed"
    assert to_backend_event({"event": "call.failed", "call_id": "c3", "reason": "ami_error"}, None)["event"] == "failed"
    for name in ("call.utterance", "call.error", "operator.status"):
        assert to_backend_event({"event": name, "call_id": "c4"}, None) is None


def test_backend_webhook_with_token(tmp_path):
    store = mock_services.EventStore()
    server = mock_services.make_server("127.0.0.1", 0, {}, store)
    url = _serve(server)
    try:
        sink = EventSink(tmp_path / "s.log", backend_url=f"{url}/backend", fmt="backend", token="t0k",
                         backend_ids=lambda call_id: {"lesson_id": LESSON})
        sink.emit("call.started", call_id="c1", trainee="ws01")
        sink.emit("call.utterance", call_id="c1", text="—")          # Backend не нужно
        sink.emit("call.ended", call_id="c1", trainee="ws01", duration_sec=3)
        assert sink.wait_delivered(5)
        events = store.query()
        assert [e["event"] for e in events] == ["answered", "ended"]
        assert all(e["lesson_id"] == LESSON for e in events)
        # в sessions.log — все события в исходном виде
        assert len((tmp_path / "s.log").read_text(encoding="utf-8").splitlines()) == 3
    finally:
        server.shutdown()


# ------------------------------------------- контракт Backend: звонки ---

@pytest.fixture
def control(tmp_path):
    settings = dataclasses.replace(Settings.from_env(), sessions_log_path=tmp_path / "sessions.log", backend_url="")
    return CallControl(settings, CallRegistry(), EventSink(settings.sessions_log_path), FakeAMI("no_answer"),
                       FakeVoice([]), DIRECTORY, TraineeContexts())


def test_backend_originate_incoming_112(control):
    resp = control.backend_originate({"lesson_id": LESSON, "attempt_id": ATTEMPT, "card_no": "У-000012",
                                      "callee_number": "03", "caller_number": "+7 (9xx) xxx-xx-01"})
    call = control.registry.get(resp["sip_call_id"])
    assert resp["status"] == "ringing" and resp["callee_number"] == "ws03"      # номер АРМ «03» -> ws03
    assert (call.call_type, call.trainee, call.session_id) == ("incident_112", "ws03", LESSON)
    assert call.scenario_id == control.s.default_112_scenario and call.card == {"number": "У-000012"}
    assert call.backend == {"lesson_id": LESSON, "attempt_id": ATTEMPT}
    assert _wait(lambda: control.registry.get(call.call_id).status == "failed")   # FakeAMI: не ответили


def test_backend_originate_processing_to_service(control):
    resp = control.backend_originate({"lesson_id": LESSON, "direction": "outbound", "kind": "service",
                                      "callee_number": "101", "callee_name": "Служба 101 (МЧС)",
                                      "caller_number": "ws07"})
    call = control.registry.get(resp["sip_call_id"])
    assert (call.call_type, call.trainee, call.persona["number"]) == ("dispatch", "ws07", "2101")
    assert (resp["caller_number"], resp["callee_number"]) == ("ws07", "2101")


def test_backend_originate_unknown_service_dials_number(control):
    resp = control.backend_originate({"direction": "outbound", "kind": "brigade", "callee_number": "2999",
                                      "caller_number": "sip-1001"})
    call = control.registry.get(resp["sip_call_id"])
    assert call.dialed == "2999" and call.trainee == control.s.default_trainee and call.backend is None


def test_backend_hangup_idempotent(control):
    resp = control.backend_originate({"callee_number": "ws02"})
    assert _wait(lambda: control.registry.get(resp["sip_call_id"]).status == "failed")
    assert control.backend_hangup({"sip_call_id": resp["sip_call_id"]})["status"] == "failed"
    with pytest.raises(ApiError):
        control.backend_hangup({"sip_call_id": "nope"})


# --------------------------------------------- ML реализует /dialogue ---

def _req(call_type, turn, history, text, **extra):
    return {"call_type": call_type, "turn": turn, "history": history, "operator_text": text,
            "persona": {"name": "Петров Андрей", "position": "Старший диспетчер ЦУКС", "gender": "male",
                        "service": "Служба 101 (МЧС)", "accept": "Я вас понял, информация принята."},
            "context": {"card": {"address": "Москва, ул. Ясный проезд, 10", "description": "Горит мусор"}}, **extra}


@pytest.mark.parametrize("req", [
    _req("dispatch", 0, [], None),
    _req("dispatch", 1, [{"role": "caller", "text": "слушаю"}], "Пожар, горит мусор"),
    _req("dispatch", 1, [{"role": "caller", "text": "слушаю"}], "Пожар на Ясном проезде"),
    _req("report", 0, [], None),
    _req("applicant", 1, [{"role": "caller", "text": "Алло?"}], "Вы звонили в 112?"),
    _req("incident_112", 0, [], None, scenario_id="scenario_002"),
    _req("incident_112", 1, [{"role": "caller", "text": "Алло"}], "Назовите адрес", scenario_id="scenario_001"),
])
def test_ml_dialogue_matches_telephony_reference(req):
    """Правила ML-сервиса = эталон телефонии: автотесты проходят одинаково на ML и на mocks."""
    ref_scenarios = mock_services.load_scenarios(REPO_ROOT / "telephony" / "mocks" / "scenarios")
    assert ml_real.next_turn(req, ml_real.load_scenarios(), None) == ml_dialogue.next_turn(req, ref_scenarios, None)


def test_ml_incident_112_from_card_without_scenario():
    card = {"description": "Горит машина во дворе", "address": "ул. Ленина, 5"}
    req = {"call_type": "incident_112", "turn": 0, "history": [], "context": {"card": card}}
    assert "Горит машина во дворе" in ml_real.next_turn(req, {}, None)["reply_text"]
    h = [{"role": "caller", "text": "Алло"}]
    reply = ml_real.next_turn({**req, "turn": 1, "history": h, "operator_text": "бригада выезжает"}, {}, None)
    assert reply["end_call"] is False and "Ленина" in reply["reply_text"]       # адрес не спросили
    with pytest.raises(ml_real.DialogueError):
        ml_real.rules_turn({"call_type": "incident_112", "scenario_id": "nope"}, {})


def test_ml_strips_qwen_thinking(monkeypatch):
    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.body).encode()

    answer = {"choices": [{"message": {"content": "<think>рассуждаю</think>\nСлушаю вас. [КОНЕЦ]"}}]}
    monkeypatch.setattr(ml_real.urllib.request, "urlopen", lambda *a, **k: Resp(answer))
    cfg = ml_real.LLMConfig(api_url="http://ollama/v1", model="qwen3:4b")
    assert ml_real.llm_turn(_req("dispatch", 0, [], None), {}, cfg) == {"reply_text": "Слушаю вас.", "end_call": True}


# ------------------------------------------------ живой полный стенд ---

def _call(method, path, data=None, token=None, timeout=15):
    req = urllib.request.Request(STAND_URL + path, method=method,
                                 data=json.dumps(data).encode() if data is not None else None)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "null")


@pytest.fixture(scope="module")
def stand():
    try:
        status, _ = _call("GET", "/api/health/live", timeout=5)
    except OSError as exc:
        pytest.skip(f"полный стенд недоступен ({exc}): docker compose --profile llm up -d --build")
    if status != 200:
        pytest.skip(f"Backend не готов ({status})")


def _login(username, password):
    status, body = _call("POST", "/api/v1/auth/login", {"username": username, "password": password})
    assert status == 200, body
    return body["access_token"]


@pytest.fixture(scope="module")
def admin_token(stand):
    return _login("admin", "Admin#2026")        # учебные записи backend/scripts/seed.py


@pytest.fixture(scope="module")
def teacher_token(stand):
    return _login("teacher", "Teacher#2026")


def test_stand_components_ready(stand):
    status, body = _call("GET", "/api/health/ready", timeout=30)
    assert status == 200, body
    comps = body["components"]
    assert body["database"] == "ok"
    assert comps["ml"]["status"] == "ok" and comps["telephony"]["status"] == "ok", comps
    status, tel = _call("GET", "/telephony/health")
    assert tel["ml"] and tel["backend"] and tel["ml_api_url"] == "http://ml:8000", tel


def test_stand_login_roles(stand):
    status, body = _call("POST", "/api/v1/auth/login", {"username": "student", "password": "Student#2026"})
    assert status == 200
    status, me = _call("GET", "/api/v1/auth/me", token=body["access_token"])
    assert status == 200 and me["roles"] == ["student"]
    status, _ = _call("POST", "/api/v1/auth/login", {"username": "student", "password": "wrong-password"})
    assert status == 401


def test_stand_ml_dialogue_through_nginx(stand):
    status, reply = _call("POST", "/ml/dialogue/turn", _req("dispatch", 0, [], None))
    assert status == 200 and reply["reply_text"] == "Старший диспетчер ЦУКС Петров, слушаю вас."


def test_stand_backend_generates_via_ml(teacher_token):
    status, created = _call("POST", "/api/v1/scenarios/generate",
                            {"count": 1, "difficulty": "basic", "prompt": "Пожар в жилом доме"},
                            token=teacher_token, timeout=60)
    assert status == 201, created
    scenario = created[0]
    assert scenario["ml_model"] == "system-112-ml", scenario   # сгенерировал ML-сервис, а не правила backend
    assert scenario["briefing"]["classification"]["source"] == "Klassifikator.xlsx"
    assert "пожар" in scenario["briefing"]["classification"]["category"].lower()   # «Пожары и задымления»
    assert scenario["references"][0]["expected_text"]["ml_scenario"]["evaluation_criteria"]


def test_stand_telephony_events_reach_backend(admin_token):
    """Backend поднимает вызов -> телефония -> событие на вебхук -> запись в журнале вызовов Backend."""
    # без lesson_id: вне занятия (у настоящего занятия Backend сам передаёт свои id)
    status, call = _call("POST", "/telephony/api/v1/calls/originate", {"callee_number": "ws20", "card_no": "T-1"})
    assert status == 200 and call["callee_number"] == "ws20", call
    deadline = time.monotonic() + 60     # ws20 не зарегистрирован: вызов быстро завершится ошибкой
    found = None
    while time.monotonic() < deadline and not found:
        time.sleep(2)
        _, page = _call("GET", "/api/v1/telephony/calls?size=200", token=admin_token)
        found = [c for c in page.get("items", []) if c["sip_call_id"] == call["sip_call_id"]]
    assert found and found[0]["status"] in ("failed", "missed"), found


def test_ml_llm_native_ollama_without_thinking(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"message": {"content": "Петров, слушаю вас."}}).encode()

    def fake_urlopen(req, timeout):
        seen["url"], seen["body"] = req.full_url, json.loads(req.data)
        return Resp()

    monkeypatch.setattr(ml_real.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("DIALOGUE_ENGINE", "llm")
    monkeypatch.delenv("LLM_API_URL", raising=False)
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    monkeypatch.setenv("DIALOGUE_LLM_MODEL", "qwen3:4b-instruct")
    cfg = ml_real.LLMConfig.from_env()
    assert cfg.native and cfg.model == "qwen3:4b-instruct"
    reply = ml_real.next_turn(_req("dispatch", 0, [], None), {}, cfg)
    assert reply["reply_text"] == "Петров, слушаю вас." and reply["engine"] == "llm:qwen3:4b-instruct"
    assert seen["url"] == "http://ollama:11434/api/chat" and seen["body"]["think"] is False
