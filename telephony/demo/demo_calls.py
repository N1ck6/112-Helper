"""Демонстрация телефонии: тестовые учебные звонки без человека (или на реальный телефон).

Реплики «диспетчера» заранее синтезируются голосом Irina (voice-service, женский
голос) в data/tts/operator_9XXX.wav; имитация рабочего места Local/9XXX@autotest
(extensions.conf) проигрывает их в звонок. Собеседники отвечают голосом по своей
категории (Dmitri — мужчины, Irina — женщины), реплики — из ML-сервиса.

    python telephony/demo/demo_calls.py                  # все сценарии по очереди
    python telephony/demo/demo_calls.py dispatch report  # выбранные
    python telephony/demo/demo_calls.py --parallel 10    # нагрузка: 10 звонков одновременно
    python telephony/demo/demo_calls.py dispatch --trainee ws01   # позвонит на софтфон ws01:
                                                          # после ответа говорите сами

Только стандартная библиотека Python 3.10+. Стенд: cd telephony && docker compose up -d.
"""

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request

API = "http://localhost:8092"
VOICE = "http://localhost:8091"

# Фразы диспетчера (синтез Irina). Номер = exten в [autotest] (Local/9XXX@autotest).
OPERATOR_PHRASES = {
    "9001": "Говорит диспетчер ДДС района. Возгорание мусора по адресу Ясный проезд, дом десять. "
            "Пострадавших нет, есть угроза жилому дому. Направьте пожарный расчёт.",
    "9002": "Вас понял. Статус работы завершены фиксирую.",
    "9003": "Здравствуйте, это дежурно-диспетчерская служба. Вы звонили в сто двенадцать по поводу пожара?",
    "9004": "Говорит диспетчер ДДС. У нас пострадавший, требуется бригада.",
    "9005": "Служба сто двенадцать, что у вас случилось? Назовите адрес. Есть пострадавшие? Бригада уже выехала.",
}

# Карточка из демо-очереди frontend (frontend/js/app.js) — то, что видит обучающийся.
DEMO_CARD = {
    "id": "913126", "category": "nature", "title": "Пожар: мусор на улице",
    "address": "Москва, ул. Ясный проезд, 10", "caller": "Александр А., очевидец",
    "phone": "+7 900 000-00-00", "description": "Горит мусор у контейнерной площадки, огонь близко к дому",
    "services": ["Служба 101 (МЧС)", "ОДС ПСЦ", "Упр. района"],
}

SCENARIOS = {
    "dispatch": ("ДДС звонит в службу 101: доклад с адресом -> «информация принята»",
                 {"call_type": "dispatch", "service": "Служба 101 (МЧС)", "channel": "Local/9001@autotest"}),
    "dispatch_no_address": ("ДДС звонит в СМП без адреса -> собеседник переспрашивает адрес",
                            {"call_type": "dispatch", "service": "Служба 103 (СМП)", "channel": "Local/9004@autotest"}),
    "report": ("Старший бригады Мосводоканала звонит в ДДС с докладом о завершении работ",
               {"call_type": "report", "contact": "2201", "report": {"status": "completed"},
                "channel": "Local/9002@autotest"}),
    "applicant": ("ДДС перезванивает заявителю по номеру из карточки",
                  {"call_type": "applicant", "channel": "Local/9003@autotest"}),
    "incident_112": ("Заявитель звонит в 112 (голосовые вводные для режима оператора 112)",
                     {"call_type": "incident_112", "scenario_id": "scenario_001", "channel": "Local/9005@autotest"}),
}


def http(method: str, url: str, data: dict | None = None, timeout: float = 30):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "null")


def prepare_operator_phrases(voice_url: str = VOICE) -> None:
    """Синтезировать фразы диспетчера голосом Irina (female) в /tts/operator_9XXX.wav."""
    for exten, text in OPERATOR_PHRASES.items():
        status, data = http("POST", f"{voice_url}/tts", {"text": text, "voice": "female",
                                                         "save_as": f"operator_{exten}"}, timeout=60)
        if status != 200:
            raise RuntimeError(f"voice-service /tts {status}: {data}")


def run_call(payload: dict, timeout: float = 180) -> dict:
    status, call = http("POST", f"{API}/calls", payload)
    if status != 202:
        raise RuntimeError(f"POST /calls {status}: {call}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, call = http("GET", f"{API}/calls/{call['call_id']}")
        if call["status"] in ("ended", "failed"):
            return call
        time.sleep(1)
    return call


def print_call(title: str, call: dict) -> None:
    persona = call.get("persona") or {}
    who = " ".join(x for x in (persona.get("position"), persona.get("name"), f"({persona.get('service')})") if x)
    print(f"\n=== {title}")
    print(f"call_id={call['call_id']} тип={call['call_type']} собеседник: {who} голос={persona.get('gender')}")
    for t in call.get("transcript", []):
        label = "Собеседник" if t["role"] == "caller" else "Диспетчер "
        print(f"  {label}: {t['text'] or '(молчание)'}")
    print(f"Итог: {call['status']} / {call['reason']}, {call.get('duration_sec')} с, запись: {call.get('recording_url')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenarios", nargs="*", metavar="scenario",
                        help=f"из: {', '.join(SCENARIOS)} (по умолчанию все)")
    parser.add_argument("--parallel", type=int, default=0, help="N одновременных звонков dispatch")
    parser.add_argument("--trainee", help="SIP-аккаунт рабочего места: звонить на реальный телефон")
    args = parser.parse_args()
    unknown = [s for s in args.scenarios if s not in SCENARIOS]
    if unknown:
        parser.error(f"неизвестные сценарии {unknown}; доступны: {', '.join(SCENARIOS)}")

    status, health = http("GET", f"{API}/health", timeout=5)
    print(f"virtual-caller: {health}")
    if status != 200:
        print("Стенд не готов: cd telephony && docker compose up -d")
        return 1
    prepare_operator_phrases()
    print(f"Фразы диспетчера синтезированы: {', '.join(f'operator_{k}' for k in OPERATOR_PHRASES)}")

    if args.parallel:
        results, started = [], time.monotonic()

        def one(i):
            results.append(run_call({**SCENARIOS["dispatch"][1], "card": DEMO_CARD,
                                     "session_id": f"load-{i}-{int(time.time())}"}, timeout=300))
        threads = [threading.Thread(target=one, args=(i,)) for i in range(args.parallel)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        reasons = [r["reason"] for r in results]
        print(f"\n{args.parallel} одновременных звонков за {time.monotonic() - started:.0f} с: "
              f"{reasons.count('completed')} completed, прочие: {[x for x in reasons if x != 'completed']}")
        return 0 if reasons.count("completed") == args.parallel else 2

    for name in args.scenarios or SCENARIOS:
        title, payload = SCENARIOS[name]
        payload = {**payload, "card": DEMO_CARD, "session_id": f"demo-{name}-{int(time.time())}"}
        if args.trainee:
            payload.pop("channel")
            payload["trainee"] = args.trainee
            print(f"\n>>> Звонок на {args.trainee}: возьмите трубку и говорите сами ({title})")
        print_call(title, run_call(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
