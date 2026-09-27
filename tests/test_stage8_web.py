"""Связка АРМ (frontend) ↔ телефония: набор номера с панели, статус оператора,
телефонная книга, голос по полу заявителя, работа без ML и без моделей STT/TTS.

  * unit — без Docker;
  * integration — к полному стенду из корня (docker compose up -d): КАЖДЫЙ номер
    набирается через API панели (POST /calls {"dial"}), «трубку» держит имитация
    рабочего места Local/9XXX@autotest; nginx стенда проксирует API. SKIP без стенда.

    pytest tests/test_stage8_web.py -v
"""

import dataclasses
import json
import os
import sys
import threading
import time
import urllib.request

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "telephony" / "virtual_caller"))
sys.path.insert(0, str(REPO_ROOT / "telephony" / "mocks"))
sys.path.insert(0, str(REPO_ROOT / "telephony" / "voice_service"))
sys.path.insert(0, str(REPO_ROOT / "telephony" / "demo"))

import ml_dialogue  # noqa: E402
from caller.calls import CallRegistry, TraineeContexts  # noqa: E402
from caller.directory import Directory  # noqa: E402
from caller.events import EventSink  # noqa: E402
from test_stage6_dialogue import SCENARIOS, FakeAGI, FakeAMI, FakeVoice, MockML, _http, _wait  # noqa: E402
from test_stage7_dds_calls import CARD, DIRECTORY, api, settings  # noqa: E402,F401
from caller.dialogue import DialogueRunner  # noqa: E402

CALL_API_URL = os.environ.get("CALL_API_URL", "http://localhost:8092")
WEB_URL = os.environ.get("WEB_URL", "http://localhost:8080")
VOICE_URL = os.environ.get("VOICE_SERVICE_URL", "http://localhost:8091")


# ------------------------------------------------------ телефонная книга ---

def test_numbers_cover_frontend_services_and_special_numbers():
    numbers = {n["number"]: n for n in DIRECTORY.numbers()}
    assert {"2101", "2102", "2103", "2104", "2201", "2202", "2203", "2204", "2205", "2206", "2207", "2208",
            "3000", "700", "701", "600"} <= set(numbers)
    # все службы, которые frontend подставляет в карточку (frontend/js/app.js, ALL_SERVICES)
    app_js = (REPO_ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    block = app_js.split("const ALL_SERVICES = [", 1)[1].split("];", 1)[0]
    services = [line.strip().strip('",') for line in block.splitlines() if line.strip().startswith('"')]
    assert services and all(DIRECTORY.resolve(s) for s in services), services


def test_dial_target():
    assert DIRECTORY.dial_target("2103")["persona"]["name"] == "Ковалёва Елена"
    assert DIRECTORY.dial_target("701") == {"call_type": "incident_112", "title": "Учебный вызов 112: ДТП с пострадавшими",
                                            "persona": None, "handled_by_agi": True, "scenario_id": "scenario_002"}
    assert DIRECTORY.dial_target("600")["handled_by_agi"] is False
    unknown = DIRECTORY.dial_target("5555")
    assert unknown["handled_by_agi"] and unknown["persona"] is None


# -------------------------------------------------- набор с панели (API) ---

def test_api_dial_originates_into_dialplan(api):
    ami = FakeAMI("answered")
    url, registry, _ = api(ami)
    _http("PUT", f"{url}/trainees/ws04/context", {"session_id": "s-d", "card": CARD})
    status, call = _http("POST", f"{url}/calls", {"dial": "2101", "trainee": "ws04"})
    assert status == 202 and call["dialed"] == "2101" and call["call_type"] == "dispatch"
    assert call["persona"]["number"] == "2101" and call["card"]["id"] == "913126" and call["session_id"] == "s-d"
    assert _wait(lambda: ami.originated)
    o = ami.originated[0]
    assert (o["channel"], o["context"], o["exten"]) == ("PJSIP/ws04", "internal", "2101")
    assert o["variables"] == {"SESSION_ID": "s-d", "TRAINEE": "ws04"}
    assert o["caller_id"] == '"Набор 2101" <2101>'
    assert _http("GET", f"{url}/numbers")[1][0]["number"] == "2101"
    assert _http("POST", f"{url}/calls", {"dial": "21a", "trainee": "ws04"})[0] == 400
    assert _http("POST", f"{url}/calls", {"dial": "2101"})[0] == 400          # нет рабочего места


def test_api_dial_echo_is_tracked_by_channel(api):
    ami = FakeAMI("answered")   # channel_alive -> False: «разговор» сразу закончился
    url, registry, control = api(ami)
    _, call = _http("POST", f"{url}/calls", {"dial": "600", "trainee": "ws04"})
    assert _wait(lambda: registry.get(call["call_id"]).status == "ended", timeout=8)

    def kinds():
        lines = control.events.log_path.read_text(encoding="utf-8").splitlines() if control.events.log_path.exists() else []
        return [e["event"] for e in map(json.loads, lines) if e.get("call_id") == call["call_id"]]
    assert _wait(lambda: len(kinds()) == 3, timeout=5), kinds()
    assert kinds() == ["call.dialing", "call.started", "call.ended"]


def test_api_dial_failed_when_phone_offline(api):
    url, registry, _ = api(FakeAMI("unavailable"))
    _, call = _http("POST", f"{url}/calls", {"dial": "2101", "trainee": "ws09"})
    assert _wait(lambda: registry.get(call["call_id"]).status == "failed")
    assert registry.get(call["call_id"]).reason == "unavailable"


def test_dialogue_dialed_call_resolves_by_dialplan(settings):
    """Звонок с панели уже в реестре (dialed) — AGI уточняет собеседника по набранному номеру."""
    registry, contexts = CallRegistry(), TraineeContexts()
    contexts.set("ws04", {"card": CARD})
    from caller.calls import Call
    registry.add(Call(call_id="d1", session_id="s-d", scenario_id="", direction="inbound", trainee="ws04",
                      call_type="dispatch", dialed="2103"))
    voice = FakeVoice(["Говорит ДДС, Ясный проезд, дом десять, пострадавший"])
    runner = DialogueRunner(settings, voice, MockML(), EventSink(settings.sessions_log_path), registry,
                            DIRECTORY, contexts)
    agi = FakeAGI(env={"agi_uniqueid": "d1", "agi_channel": "PJSIP/ws04-00000009"},
                  variables={"CALL_TYPE": "dispatch", "CONTACT_ID": "2103"})
    assert runner.handle(agi) == "completed"
    call = registry.get("d1")
    assert (call.session_id, call.persona["number"], call.card["id"]) == ("s-d", "2103", "913126")
    assert set(voice.voices) == {"female"}


# --------------------------------------------------- статус оператора ---

def test_operator_status_blocks_system_calls_only(api):
    ami = FakeAMI("answered")
    url, _, _ = api(ami)
    assert _http("PUT", f"{url}/trainees/ws05/status", {"available": "yes"})[0] == 400
    assert _http("PUT", f"{url}/trainees/ws05/status", {"available": False})[1] == {"trainee": "ws05", "available": False}
    assert _http("GET", f"{url}/trainees/ws05/status")[1]["available"] is False
    report = {"call_type": "report", "trainee": "ws05", "contact": "2101"}
    assert _http("POST", f"{url}/calls", report)[0] == 409                       # от системы — нет
    assert _http("POST", f"{url}/calls", {**report, "initiated_by": "trainee"})[0] == 202  # сам нажал — да
    assert _http("POST", f"{url}/calls", {"dial": "2101", "trainee": "ws05"})[0] == 202    # набор — всегда
    assert next(e for e in _http("GET", f"{url}/endpoints")[1] if e["endpoint"] == "alice")["available"] is True
    _http("PUT", f"{url}/trainees/ws05/status", {"available": True})
    assert _http("POST", f"{url}/calls", report)[0] == 202


def test_health_reports_ml(api, settings):
    url, _, control = api()
    control.s = dataclasses.replace(settings, ml_api_url="http://127.0.0.1:9")   # никто не слушает
    health = _http("GET", f"{url}/health")[1]
    assert health["ml"] is False and health["status"] == "degraded"


# ---------------------------------------------- голос заявителя сценария ---

def test_scenario_gender_switches_voice(settings):
    """Заявитель ДТП (scenario_002) — мужчина: ML отдаёт voice=male, реплики мужским голосом."""
    assert ml_dialogue.next_turn({"call_type": "incident_112", "scenario_id": "scenario_002", "turn": 0},
                                 SCENARIOS, None)["voice"] == "male"
    assert "voice" not in ml_dialogue.next_turn({"call_type": "dispatch", "turn": 0, "persona": {}}, SCENARIOS, None)
    voice = FakeVoice(["Где вы?", "Пострадавшие есть?", "Бригада выехала"])
    runner = DialogueRunner(settings, voice, MockML(), EventSink(settings.sessions_log_path), CallRegistry())
    agi = FakeAGI(env={"agi_uniqueid": "v1", "agi_network_script": "scenario_002", "agi_channel": "PJSIP/ws06-1"},
                  variables={"CALL_TYPE": "incident_112"})
    runner.handle(agi)
    assert voice.voices and set(voice.voices) == {"male"}


# ---------------------------------------------- voice-service без моделей ---

def test_voice_service_falls_back_to_mock_without_models(tmp_path, monkeypatch):
    from voice.config import Settings as VoiceSettings
    from voice import server as voice_server
    monkeypatch.setattr(voice_server, "download_for", lambda engine, s: False)   # «нет интернета»
    s = dataclasses.replace(VoiceSettings.from_env(), stt_engine="faster_whisper", tts_engine="piper",
                            models_dir=tmp_path / "models", audio_root=tmp_path, tts_output_dir=tmp_path / "tts",
                            models_auto_download=True, engine_fallback="mock")
    service = voice_server.VoiceService(s)
    service.load()
    assert service.healthy and service.degraded
    assert service.stt.name == "mock" and service.tts.name == "mock"
    assert service.status["stt"]["fallback"] and "whisper" in service.status["stt"]["error"]


# ---------------------------------------------------------- integration ---

@pytest.fixture(scope="module")
def stand():
    try:
        status, health = _http("GET", f"{CALL_API_URL}/health", timeout=5)
    except OSError as exc:
        pytest.skip(f"стенд не запущен ({exc}): docker compose up -d (из корня)")
    if status != 200 or not health.get("ml"):
        pytest.fail(f"стенд не готов: {health}")
    import demo_calls  # фразы «диспетчера» голосом Irina для Local/9XXX@autotest
    demo_calls.prepare_operator_phrases(VOICE_URL)
    _http("PUT", f"{CALL_API_URL}/trainees/ws08/context", {"session_id": "it8", "card": CARD})
    return health


def _dial(number: str, operator: str, timeout: float = 150, hangup_after: float | None = None) -> dict:
    status, call = _http("POST", f"{CALL_API_URL}/calls",
                         {"dial": number, "trainee": "ws08", "channel": f"Local/{operator}@autotest"})
    assert status == 202, call
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        _, call = _http("GET", f"{CALL_API_URL}/calls/{call['call_id']}")
        if call["status"] in ("ended", "failed"):
            return call
        if hangup_after and call["status"] == "in_progress" and time.monotonic() - started > hangup_after:
            _http("POST", f"{CALL_API_URL}/calls/{call['call_id']}/hangup", {})
            hangup_after = None
        time.sleep(1)
    raise AssertionError(f"звонок на {number} не завершился: {call}")


def _callers(call):
    return [t["text"] for t in call["transcript"] if t["role"] == "caller"]


def test_integration_every_service_number_answers(stand):
    """Все 12 служб справочника: гудки -> «<должность> <фамилия>, слушаю вас» -> «информация принята»."""
    contacts = {c["number"]: c for c in DIRECTORY.contacts}
    results = {}

    def one(number):
        results[number] = _dial(number, "9001", timeout=240)
    threads = [threading.Thread(target=one, args=(n,)) for n in contacts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    bad = {}
    for number, call in results.items():
        c = contacts[number]
        callers = _callers(call)
        surname = c["name"].split()[0]
        ok = (call["reason"] == "completed" and callers and surname in callers[0] and "слушаю" in callers[0]
              and callers[-1] == c["accept"])
        voices = {t["audio"].split("cache_")[1].split("_")[0] for t in call["transcript"]
                  if t["role"] == "caller" and t.get("audio")}
        if not ok or voices != {c["gender"]}:
            bad[number] = (call["reason"], callers, voices)
    assert not bad, bad


def test_integration_applicant_3000(stand):
    call = _dial("3000", "9003")
    assert call["reason"] == "completed" and call["call_type"] == "applicant", call
    callers = _callers(call)
    assert callers[0] == "Алло?" and callers[1].startswith("Да, звонил") and callers[-1] == "Хорошо, спасибо, ждём."


@pytest.mark.parametrize("number,scenario,gender", [("700", "scenario_001", "female"), ("701", "scenario_002", "male")])
def test_integration_incident_112(stand, number, scenario, gender):
    call = _dial(number, "9005")
    assert call["call_type"] == "incident_112" and call["scenario_id"] == scenario, call
    assert call["reason"] == "completed", call["transcript"]
    assert _callers(call)[0] == SCENARIOS[scenario]["opening"]
    audio = [t["audio"] for t in call["transcript"] if t["role"] == "caller" and t.get("audio")]
    assert audio and all(f"cache_{gender}_" in a for a in audio), audio


@pytest.mark.parametrize("number", ["2999", "5555"])
def test_integration_unknown_number(stand, number):
    call = _dial(number, "9001", timeout=60)
    assert call["reason"] == "unknown_number" and call["status"] == "ended", call


def test_integration_echo_600(stand):
    call = _dial("600", "9001", timeout=60, hangup_after=4)
    assert call["status"] == "ended" and call["call_type"] == "echo" and call["duration_sec"] >= 3, call


def test_integration_web_proxy_and_frontend(stand):
    try:
        with urllib.request.urlopen(f"{WEB_URL}/dashboard.html", timeout=5) as resp:
            html, cache = resp.read().decode("utf-8"), resp.headers.get("Cache-Control")
    except OSError as exc:
        pytest.skip(f"frontend не запущен ({exc}): docker compose up -d (из корня)")
    assert '<script src="js/telephony.js"></script>' in html and cache == "no-cache"
    assert _http("GET", f"{WEB_URL}/telephony/health")[1]["ml"] is True
    assert len(_http("GET", f"{WEB_URL}/telephony/numbers")[1]) >= 16
    with urllib.request.urlopen(f"{WEB_URL}/js/telephony.js", timeout=5) as resp:
        assert resp.status == 200
