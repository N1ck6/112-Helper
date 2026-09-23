"""
Тест этапа 1 — SIP-сервер жив и отвечает на мониторинг (AMI).

Запуск:
    cd telephony && docker compose up --build -d
    pytest tests/test_stage1_sip_server.py -v
"""


def test_ami_ping(ami):
    """AMI Ping — простейшая проверка "сервер жив и понимает протокол".

    Это дополняет healthcheck.sh (который проверяет только процесс
    изнутри контейнера) — здесь мы стучимся СНАРУЖИ, как это будет
    делать реальный компонент мониторинга.
    """
    resp = ami.ping()
    # Asterisk 13+: "Response: Success" + "Ping: Pong" (старые версии: "Response: Pong")
    assert "Pong" in (resp.get("Ping"), resp.get("Response")), f"Ожидали Pong от AMI, получили: {resp}"


def test_ami_reports_core_version(ami):
    """Дополнительная проверка через CoreSettings — что Asterisk
    действительно инициализировался (а не просто открыл TCP-порт)."""
    resp = ami.send_action("CoreSettings")
    assert resp.get("Response") == "Success", f"CoreSettings не ответил успехом: {resp}"
