"""
Тест этапа 2 — SIP-звонок / dialplan срабатывает, без реального софтфона.

Запуск:
    docker compose -f telephony/docker-compose.yml up --build -d
    pytest tests/test_stage2_sip_call.py -v

Как это работает без второго участника звонка:
AMI Originate с Channel="Local/600@internal" создаёт "виртуальный"
звонок — Local-канал, вторая половина которого исполняет dialplan
на извлечении 600 (echo-тест из этапа 2), а первая половина сразу же
исполняет Application=NoOp и тут же завершается, что и роняет весь
мост. Это НЕ полноценная замена ручной проверки голоса через софтфон
(см. README этапа 2) — это проверка "звонок на 600 доходит до dialplan
и корректно разбирается", т.е. SIP-сигнализация + маршрутизация работают.
"""


def test_echo_extension_is_reachable(ami_stage2):
    events = ami_stage2.originate_and_wait_hangup(
        channel="Local/600@internal",
        Application="NoOp",
        timeout_s=10.0,
    )

    reached_600 = any(
        e.get("Event") == "Newexten" and e.get("Extension") == "600" for e in events
    )
    got_hangup = any(e.get("Event") == "Hangup" for e in events)

    assert events, "AMI не прислал вообще никаких событий — Originate не сработал"
    assert reached_600, (
        "Не нашли Newexten с Extension=600 среди событий AMI — "
        f"возможно dialplan [internal] не подключился. events={events}"
    )
    assert got_hangup, f"Звонок не завершился штатным Hangup за 10с. events={events}"
