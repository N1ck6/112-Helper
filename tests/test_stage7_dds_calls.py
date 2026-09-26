"""Звонки ДДС: диспетчер -> служба (dispatch), доклад старшего (report), перезвон
заявителю (applicant); справочник служб; LLM-адаптер ML; API для frontend.

  * unit — без Docker;
  * integration — к стенду (cd telephony && docker compose up -d, COMPOSE_PROFILES=mocks):
    фразы диспетчера синтезируются голосом Irina в /tts/operator_9XXX.wav и
    проигрываются имитацией рабочего места Local/9XXX@autotest. SKIP без стенда.

    pytest tests/test_stage7_dds_calls.py -v
"""

import dataclasses
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import RECORDINGS_DIR, REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "telephony" / "virtual_caller"))
sys.path.insert(0, str(REPO_ROOT / "telephony" / "mocks"))
sys.path.insert(0, str(REPO_ROOT / "telephony" / "demo"))

import ml_dialogue  # noqa: E402
from caller.api import CallControl, make_api_server  # noqa: E402
from caller.calls import CallRegistry, TraineeContexts  # noqa: E402
from caller.config import Settings  # noqa: E402
from caller.dialogue import DialogueRunner  # noqa: E402
from caller.directory import Directory, guess_gender  # noqa: E402
from caller.events import EventSink  # noqa: E402
from test_stage6_dialogue import FakeAGI, FakeAMI, FakeVoice, MockML, _http, _serve, _wait  # noqa: E402

DIRECTORY = Directory.load(REPO_ROOT / "telephony" / "virtual_caller" / "directory.json")
CARD = {"id": "913126", "title": "Пожар: мусор на улице", "address": "Москва, ул. Ясный проезд, 10",
        "caller": "Александр А., очевидец", "description": "Горит мусор у контейнерной площадки",
        "services": ["Служба 101 (МЧС)", "ОДС ПСЦ", "Упр. района"]}
CALL_API_URL = os.environ.get("CALL_API_URL", "http://localhost:8092")
MOCKS_URL = os.environ.get("MOCKS_URL", "http://localhost:8093")
VOICE_URL = os.environ.get("VOICE_SERVICE_URL", "http://localhost:8091")


# ----------------------------------------------------------- справочник ---

@pytest.mark.parametrize("name,number", [
    # названия служб из демо-данных frontend (frontend/js/app.js)
    ("Служба 101 (МЧС)", "2101"), ("Служба 103 (СМП)", "2103"), ("ОМВД", "2102"),
    ("Мосводоканал", "2201"), ("ГБУ «Жилищник»", "2202"), ("Упр. района", "2203"), ("ОДС ПСЦ", "2204"),
    ("2205", "2205"), ("mosgortrans", "2206"),
])
def test_directory_resolves_frontend_service_names(name, number):
    assert DIRECTORY.resolve(name)["number"] == number


def test_directory_unknown_and_personas():
    assert DIRECTORY.resolve("Служба такси") is None and DIRECTORY.resolve("") is None
    mchs = DIRECTORY.resolve("2101")
    assert Directory.persona(mchs)["position"] == "Старший диспетчер ЦУКС"
    assert Directory.persona(mchs, "report")["position"].startswith("Начальник караула")   # старший группы
    assert Directory.persona(DIRECTORY.resolve("2204"), "report")["service"] == "ОДС ПСЦ"  # без leader — дежурный
    assert "accept" not in DIRECTORY.public()[0]


def test_applicant_gender_guess():
    assert guess_gender("Александр А., очевидец") == "male"
    assert guess_gender("Мария К., родственник") == "female"
    assert guess_gender("Илья") == "male" and guess_gender(None) == "female"
    assert Directory.applicant(CARD)["gender"] == "male"


# ------------------------------------------------------------- ML rules ---

def _req(call_type, turn, history, operator_text, persona=None, card=CARD, report=None):
    return {"call_type": call_type, "turn": turn, "history": history, "operator_text": operator_text,
            "persona": persona or Directory.persona(DIRECTORY.resolve("2101"), call_type),
            "context": {"card": card, "report": report}}


def test_rules_dispatch_asks_address_then_accepts():
    greet = ml_dialogue.rules_turn(_req("dispatch", 0, [], None), {})
    assert greet == {"reply_text": "Старший диспетчер ЦУКС Петров, слушаю вас.", "end_call": False}
    h = [{"role": "caller", "text": greet["reply_text"]}, {"role": "operator", "text": "Горит мусор, пришлите расчёт"}]
    ask = ml_dialogue.rules_turn(_req("dispatch", 1, h, h[-1]["text"]), {})
    assert ask["reply_text"] == ml_dialogue.ASK_ADDRESS and not ask["end_call"]
    h += [{"role": "caller", "text": ask["reply_text"]}, {"role": "operator", "text": "Ясный проезд, дом десять"}]
    done = ml_dialogue.rules_turn(_req("dispatch", 2, h, h[-1]["text"]), {})
    assert done["end_call"] and "информация принята" in done["reply_text"]


def test_rules_dispatch_accepts_when_address_given_and_silence():
    h = [{"role": "caller", "text": "…"}, {"role": "operator", "text": "Пожар на Ясном проезде десять"}]
    assert ml_dialogue.rules_turn(_req("dispatch", 1, h, h[-1]["text"]), {})["end_call"]
    h = [{"role": "caller", "text": "…"}, {"role": "operator", "text": ""}]
    assert not ml_dialogue.rules_turn(_req("dispatch", 1, h, ""), {})["end_call"]
    h += [{"role": "caller", "text": "…"}, {"role": "operator", "text": ""}]
    assert ml_dialogue.rules_turn(_req("dispatch", 2, h, ""), {})["end_call"]


def test_rules_report_and_applicant():
    rep = ml_dialogue.rules_turn(_req("report", 0, [], None, report={"status": "arrival"}), {})
    assert "Прибыли на место по адресу Москва, ул. Ясный проезд, 10" in rep["reply_text"]
    assert rep["reply_text"].startswith("Дежурно-диспетчерская служба? Говорит Начальник караула")
    h = [{"role": "caller", "text": rep["reply_text"]}, {"role": "operator", "text": "Принято, прибытие фиксирую"}]
    assert ml_dialogue.rules_turn(_req("report", 1, h, h[-1]["text"]), {})["end_call"]

    persona = Directory.applicant(CARD)
    first = ml_dialogue.rules_turn(_req("applicant", 0, [], None, persona=persona), {})
    assert first["reply_text"] == "Алло?"
    h = [{"role": "caller", "text": "Алло?"}, {"role": "operator", "text": "Вы звонили в 112 по поводу пожара"}]
    story = ml_dialogue.rules_turn(_req("applicant", 1, h, h[-1]["text"], persona=persona), {})
    assert story["reply_text"].startswith("Да, звонил. Горит мусор") and not story["end_call"]
    h += [{"role": "caller", "text": story["reply_text"]}, {"role": "operator", "text": "Расчёт выехал"}]
    assert ml_dialogue.rules_turn(_req("applicant", 2, h, h[-1]["text"], persona=persona), {})["end_call"]


def test_rules_incident_without_scenario():
    with pytest.raises(ml_dialogue.DialogueError):
        ml_dialogue.rules_turn({"call_type": "incident_112", "scenario_id": "nope", "turn": 0}, {})


# ------------------------------------------------------------------ LLM ---

class _FakeOpenAI(BaseHTTPRequestHandler):
    replies: list = []
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((self.path, body, self.headers.get("Authorization")))
        text = type(self).replies.pop(0)
        data = json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_llm():
    handler = type("H", (_FakeOpenAI,), {"replies": [], "seen": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    url = _serve(server)
    yield handler, ml_dialogue.LLMConfig(api_url=f"{url}/v1", model="test-model", api_key="k", timeout_sec=5)
    server.shutdown()


def test_llm_turn_openai_compatible(fake_llm):
    handler, cfg = fake_llm
    handler.replies += ["**Петров**, слушаю вас.", "Понял, информация принята. [КОНЕЦ]"]
    r = ml_dialogue.next_turn(_req("dispatch", 0, [], None), {}, cfg)
    assert r == {"reply_text": "Петров, слушаю вас.", "end_call": False, "engine": "llm:test-model"}
    path, body, auth = handler.seen[0]
    assert path == "/v1/chat/completions" and body["model"] == "test-model" and auth == "Bearer k"
    assert "Старший диспетчер ЦУКС" in body["messages"][0]["content"] and "Ясный проезд" in body["messages"][0]["content"]
    h = [{"role": "caller", "text": "Петров, слушаю"}, {"role": "operator", "text": "Пожар на Ясном"}]
    r = ml_dialogue.next_turn(_req("dispatch", 1, h, "Пожар на Ясном"), {}, cfg)
    assert r["end_call"] and "[КОНЕЦ]" not in r["reply_text"]
    assert [m["role"] for m in handler.seen[1][1]["messages"]] == ["system", "assistant", "user"]


def test_llm_down_falls_back_to_rules():
    cfg = ml_dialogue.LLMConfig(api_url="http://127.0.0.1:9/v1", model="m", timeout_sec=0.5)
    r = ml_dialogue.next_turn(_req("dispatch", 0, [], None), {}, cfg)
    assert r["engine"] == "rules-fallback" and "слушаю вас" in r["reply_text"]


def test_llm_config_from_env(monkeypatch):
    monkeypatch.setenv("DIALOGUE_ENGINE", "rules")
    assert ml_dialogue.LLMConfig.from_env() is None
    monkeypatch.setenv("DIALOGUE_ENGINE", "llm")
    monkeypatch.setenv("LLM_API_URL", "http://host.docker.internal:11434/v1/")
    cfg = ml_dialogue.LLMConfig.from_env()
    assert cfg.api_url == "http://host.docker.internal:11434/v1" and cfg.model


# ------------------------------------------------------ голосовой цикл ---

@pytest.fixture
def settings(tmp_path):
    return dataclasses.replace(Settings.from_env(), sessions_log_path=tmp_path / "sessions.log",
                               backend_url="", max_turns=8, recordings_base_url="http://rec")


def _dds_runner(settings, voice, contexts=None):
    registry = CallRegistry()
    runner = DialogueRunner(settings, voice, MockML(), EventSink(settings.sessions_log_path), registry,
                            DIRECTORY, contexts or TraineeContexts())
    return runner, registry


def test_trainee_dials_service_uses_workplace_card_and_male_voice(settings):
    contexts = TraineeContexts()
    contexts.set("ws01", {"session_id": "s-7", "card": CARD})
    voice = FakeVoice(["Горит мусор, есть угроза дому", "Ясный проезд, дом десять"])
    runner, registry = _dds_runner(settings, voice, contexts)
    agi = FakeAGI(env={"agi_uniqueid": "1.5", "agi_network_script": "", "agi_channel": "PJSIP/ws01-00000002"},
                  variables={"CALL_TYPE": "dispatch", "CONTACT_ID": "2101"})
    assert runner.handle(agi) == "completed"
    call = registry.get("1.5")
    assert (call.trainee, call.session_id, call.call_type, call.card["id"]) == ("ws01", "s-7", "dispatch", "913126")
    assert set(voice.voices) == {"male"}
    texts = [t["text"] for t in call.transcript if t["role"] == "caller"]
    assert texts[1] == ml_dialogue.ASK_ADDRESS and "информация принята" in texts[-1]
    started = json.loads(settings.sessions_log_path.read_text(encoding="utf-8").splitlines()[0])
    assert started["persona"]["service"] == "Служба 101 (МЧС)" and started["card_id"] == "913126"


def test_unknown_service_number(settings):
    voice = FakeVoice([])
    runner, registry = _dds_runner(settings, voice)
    agi = FakeAGI(env={"agi_uniqueid": "1.6", "agi_channel": "PJSIP/ws02-1"},
                  variables={"CALL_TYPE": "dispatch", "CONTACT_ID": "2999"})
    assert runner.handle(agi) == "unknown_number"
    assert voice.synthesized == ["Набранный номер не обслуживается."] and agi.hungup
    assert registry.get("1.6").reason == "unknown_number"


def test_applicant_callback_female_voice(settings):
    contexts = TraineeContexts()
    contexts.set("ws03", {"card": {**CARD, "caller": "Мария К."}})
    voice = FakeVoice(["Вы звонили в 112 по поводу пожара?", "Расчёт уже едет"])
    runner, registry = _dds_runner(settings, voice, contexts)
    agi = FakeAGI(env={"agi_uniqueid": "1.7", "agi_channel": "PJSIP/ws03-1"}, variables={"CALL_TYPE": "applicant"})
    assert runner.handle(agi) == "completed"
    assert set(voice.voices) == {"female"}
    assert registry.get("1.7").transcript[2]["text"].startswith("Да, звонила")


# ------------------------------------------------------ API для frontend ---

@pytest.fixture
def api(settings):
    servers = []

    def start(ami=None):
        registry, contexts = CallRegistry(), TraineeContexts()
        events = EventSink(settings.sessions_log_path)
        control = CallControl(settings, registry, events, ami or FakeAMI(), FakeVoice([]), DIRECTORY, contexts)
        server = make_api_server(control, "127.0.0.1", 0)
        servers.append(server)
        return _serve(server), registry, control
    yield start
    for s in servers:
        s.shutdown()


def _raw(method, url, data=None, headers=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_api_directory_context_and_cors(api):
    url, _, _ = api()
    status, headers, body = _raw("GET", f"{url}/directory")
    assert status == 200 and headers["Access-Control-Allow-Origin"] == "*"
    assert {"number": "2101", "service": "Служба 101 (МЧС)"}.items() <= json.loads(body)[0].items()
    status, headers, _ = _raw("OPTIONS", f"{url}/calls", headers={"Origin": "http://localhost:8080",
                                                               "Access-Control-Request-Method": "POST"})
    assert status == 204 and "POST" in headers["Access-Control-Allow-Methods"]
    assert _http("GET", f"{url}/trainees/ws01/context")[0] == 404
    status, ctx = _http("PUT", f"{url}/trainees/ws01/context", {"session_id": "s-1", "card": CARD})
    assert status == 200 and ctx["card"]["id"] == "913126"
    assert _http("GET", f"{url}/trainees/ws01/context")[1]["session_id"] == "s-1"
    assert _http("PUT", f"{url}/trainees/ws01/context", {"card": "x"})[0] == 400
    assert _http("DELETE", f"{url}/trainees/ws01/context")[0] == 200


def test_api_dispatch_click_to_call(api):
    ami = FakeAMI("answered")
    url, registry, control = api(ami)
    _http("PUT", f"{url}/trainees/ws01/context", {"session_id": "s-2", "card": CARD})
    status, call = _http("POST", f"{url}/calls", {"call_type": "dispatch", "trainee": "ws01",
                                                 "service": "Служба 101 (МЧС)"})
    assert status == 202 and call["persona"]["number"] == "2101" and call["session_id"] == "s-2"
    assert call["card"]["id"] == "913126"
    assert _wait(lambda: ami.originated)
    o = ami.originated[0]
    assert o["channel"] == "PJSIP/ws01"
    assert o["variables"] == {"SCENARIO_ID": "", "SESSION_ID": "s-2", "CALL_TYPE": "dispatch", "RINGBACK_SEC": "3"}
    assert _http("GET", f"{url}/calls?trainee=ws01")[1][0]["call_id"] == call["call_id"]
    assert _http("GET", f"{url}/calls?trainee=ws09")[1] == []


def test_api_report_and_validation(api):
    ami = FakeAMI("answered")
    url, _, _ = api(ami)
    status, call = _http("POST", f"{url}/calls", {"call_type": "report", "trainee": "ws02", "contact": "2101",
                                                 "report": {"status": "arrival"}, "card": CARD})
    assert status == 202 and call["persona"]["position"].startswith("Начальник караула")
    assert call["report"] == {"status": "arrival"}
    assert _wait(lambda: ami.originated) and "RINGBACK_SEC" not in ami.originated[0]["variables"]
    assert _http("POST", f"{url}/calls", {"call_type": "dispatch", "trainee": "ws02", "service": "Такси"})[0] == 404
    assert _http("POST", f"{url}/calls", {"call_type": "incident_112", "trainee": "ws02"})[0] == 400
    assert _http("POST", f"{url}/calls", {"call_type": "fax", "trainee": "ws02"})[0] == 400


def test_caller_id_shown_on_trainee_phone(api):
    seen = []

    class AMI(FakeAMI):
        def originate(self, **kw):
            seen.append(kw["caller_id"])
            return "no_answer"
    url, _, _ = api(AMI())
    _http("POST", f"{url}/calls", {"call_type": "report", "trainee": "ws02", "contact": "2201"})
    _http("POST", f"{url}/calls", {"call_type": "dispatch", "trainee": "ws02", "contact": "2103"})
    assert _wait(lambda: len(seen) == 2)
    assert '"Мастер аварийной бригады (Мосводоканал)" <2201>' in seen
    assert '"Служба 103 (СМП)" <2103>' in seen


def test_api_sse_stream(api):
    url, _, control = api()
    host, port = url.replace("http://", "").split(":")
    sock = socket.create_connection((host, int(port)), timeout=5)
    sock.sendall(b"GET /events?trainee=ws05 HTTP/1.1\r\nHost: x\r\n\r\n")
    buf = b""
    while b": connected" not in buf:
        buf += sock.recv(4096)
    control.events.emit("call.started", call_id="c1", trainee="ws09")   # чужое рабочее место — не придёт
    control.events.emit("call.started", call_id="c2", trainee="ws05")
    deadline = time.monotonic() + 5
    while b'"c2"' not in buf and time.monotonic() < deadline:
        buf += sock.recv(4096)
    sock.close()
    text = buf.decode("utf-8")
    assert "text/event-stream" in text and "event: call.started" in text
    assert '"c2"' in text and '"c1"' not in text


# ---------------------------------------------------------- integration ---

sys_demo = None


@pytest.fixture(scope="module")
def stand():
    try:
        status, health = _http("GET", f"{CALL_API_URL}/health", timeout=5)
        mocks_status, _ = _http("GET", f"{MOCKS_URL}/health", timeout=5)
    except OSError as exc:
        pytest.skip(f"стенд не запущен ({exc}): cd telephony && docker compose up -d (COMPOSE_PROFILES=mocks)")
    if status != 200 or mocks_status != 200:
        pytest.fail(f"стенд не готов: {health}")
    import demo_calls  # telephony/demo — подготовка фраз диспетчера голосом Irina
    demo_calls.prepare_operator_phrases(VOICE_URL)
    return health


def _run_call(payload: dict, timeout: float = 150) -> dict:
    status, call = _http("POST", f"{CALL_API_URL}/calls", payload)
    assert status == 202, call
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, call = _http("GET", f"{CALL_API_URL}/calls/{call['call_id']}")
        if call["status"] in ("ended", "failed"):
            return call
        time.sleep(1)
    raise AssertionError(f"звонок не завершился: {call}")


def _callers(call):
    return [t["text"] for t in call["transcript"] if t["role"] == "caller"]


def test_integration_dispatch_full_report(stand):
    """Диспетчер (фраза с адресом) звонит в МЧС: «слушаю» -> доклад -> «информация принята»."""
    call = _run_call({"call_type": "dispatch", "contact": "2101", "channel": "Local/9001@autotest",
                      "trainee": "ws01", "card": CARD, "session_id": f"it7-{int(time.time())}"})
    assert call["status"] == "ended" and call["reason"] == "completed", call
    assert _callers(call)[0] == "Старший диспетчер ЦУКС Петров, слушаю вас."
    assert "информация принята" in _callers(call)[-1]
    operator = [t["text"] for t in call["transcript"] if t["role"] == "operator" and t["text"]]
    assert any("ясн" in t.lower() for t in operator), f"STT не распознал адрес: {operator}"
    wav = RECORDINGS_DIR / f"{call['call_id']}.wav"
    assert wav.stat().st_size > 44 + 16000


def test_integration_dispatch_without_address_is_asked(stand):
    call = _run_call({"call_type": "dispatch", "contact": "2103", "channel": "Local/9004@autotest", "card": CARD})
    assert ml_dialogue.ASK_ADDRESS in _callers(call), call["transcript"]


def test_integration_report_and_applicant(stand):
    rep = _run_call({"call_type": "report", "contact": "2201", "channel": "Local/9002@autotest",
                     "card": CARD, "report": {"status": "completed"}})
    assert rep["reason"] == "completed" and "завершены" in _callers(rep)[0]
    app = _run_call({"call_type": "applicant", "channel": "Local/9003@autotest", "card": CARD})
    assert _callers(app)[0] == "Алло?" and app["reason"] == "completed", app["transcript"]


def test_integration_trainee_dials_service_number(stand, ami):
    """Рабочее место набирает 2101 с телефона: карточка берётся из контекста рабочего места."""
    session = f"dial-{int(time.time())}"
    _http("PUT", f"{CALL_API_URL}/trainees/ws07/context", {"session_id": session, "card": CARD})
    ami.originate_and_wait_hangup(channel="Local/2101@internal", Context="autotest", Exten="9001",
                                  Priority="1", Variable="__TRAINEE=ws07", timeout_s=5.0)
    deadline = time.monotonic() + 120
    calls = []
    while time.monotonic() < deadline:
        calls = [c for c in _http("GET", f"{CALL_API_URL}/calls?session_id={session}")[1] if c["status"] == "ended"]
        if calls:
            break
        time.sleep(1)
    assert calls, "звонок на 2101 не завершился"
    c = calls[0]
    assert (c["direction"], c["call_type"], c["trainee"], c["card"]["id"]) == ("inbound", "dispatch", "ws07", "913126")
    assert c["persona"]["number"] == "2101"


def test_integration_parallel_calls(stand):
    """10 одновременных звонков (ТЗ: не падать при ~10 пользователях) — все доходят до конца."""
    results = []

    def one(i):
        results.append(_run_call({"call_type": "dispatch", "contact": "2101", "channel": "Local/9001@autotest",
                                  "card": CARD, "session_id": f"par-{i}-{int(time.time())}"}, timeout=240))
    threads = [threading.Thread(target=one, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 10
    assert all(r["status"] == "ended" for r in results), [r["reason"] for r in results]
    ok = sum(1 for r in results if r["reason"] == "completed")
    assert ok >= 9, [r["reason"] for r in results]
