"""
FastAGI-сервер для этапа 3 ("виртуальный учебный абонент").

Что это и зачем
----------------
Asterisk умеет на определённом шаге dialplan'а ПОЛНОСТЬЮ передать
управление звонком внешней программе по протоколу AGI. Обычный AGI
запускается как локальный процесс на машине с Asterisk; FastAGI (он же
"Network AGI") — тот же протокол, но по TCP, то есть сервис может жить
в отдельном Docker-контейнере. Это и даёт нам разделение "телефония
(Asterisk) отдельно от логики учебного сценария (Python)" — прямое
требование из инструкции (раздел 5, пункт 2 и 5).

Протокол AGI (кратко, без внешних библиотек — специально, чтобы не
тащить в MVP лишнюю зависимость ради ~10 команд):

  1) Asterisk подключается к нам по TCP и присылает "окружение" —
     строки вида "agi_variable: значение\\n", последняя строка пустая.
     В agi_network_script лежит то, что стояло после хоста:порта в
     agi://virtual-caller:4573/scenario_001 -> "scenario_001".
  2) Дальше мы шлём команды текстом (например "ANSWER\\n"), Asterisk
     построчно отвечает вида "200 result=0\\n".
  3) Когда мы закрываем соединение (или шлём HANGUP), Asterisk
     возвращается к dialplan'у на следующий шаг после AGI().

Почему это НЕ асинхронный ARI/WebSocket: для одного проигрывания
сценария синхронный "команда -> ответ -> следующая команда" проще
читать, писать и тестировать локально — то, что явно требует
инструкция ("сначала простое решение, которое легко заменить").
"""

import json
import logging
import os
import socketserver
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("virtual_caller")

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
# Путь примонтирован в docker-compose как shared volume — и Asterisk-сторона
# (через recordings), и pytest-тесты на хосте могут прочитать этот файл,
# чтобы проверить, что звонок реально был обработан AGI.
SESSIONS_LOG_PATH = Path(os.environ.get("SESSIONS_LOG_PATH", "/data/sessions.log"))
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "4573"))


def log_event(event: str, **fields):
    """Пишет одну JSON-строку в общий лог сессий.

    Формат JSON Lines (по записи на строку) выбран специально: его легко
    дописывать из нескольких потоков без блокировки всего файла, легко
    читать построчно в тестах, и не нужна СУБД для MVP (появится в
    следующих этапах вместе с Backend/PostgreSQL, п.3 этап 8).
    """
    record = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    SESSIONS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SESSIONS_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.info("event=%s %s", event, fields)


def load_scenario(scenario_id: str) -> dict:
    path = SCENARIOS_DIR / f"{scenario_id}.json"
    if not path.exists():
        log.warning("Сценарий %s не найден, использую заглушку", scenario_id)
        return {
            "scenario_id": scenario_id,
            "title": "Неизвестный сценарий (заглушка)",
            "prompts": [{"text": "Сценарий не найден", "sound": "beep"}],
            "record_response_seconds": 0,
        }
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class AGISession:
    """Обёртка над сокетом: читает окружение AGI и умеет слать команды.

    Сознательно не претендует на полную реализацию AGI-спеки — только
    те команды, что реально нужны сценарию (ANSWER/STREAM FILE/
    RECORD FILE/VERBOSE/HANGUP). Остального в MVP не требуется —
    прямое следование принципу "не добавлять лишнюю функциональность"
    (инструкция, п.5.6).
    """

    def __init__(self, rfile, wfile):
        self.rfile = rfile
        self.wfile = wfile
        self.env = {}

    def read_environment(self):
        while True:
            line = self.rfile.readline().decode("utf-8", errors="replace").strip("\r\n")
            if line == "":
                break
            if ":" in line:
                key, _, value = line.partition(":")
                self.env[key.strip()] = value.strip()

    def _send(self, command: str) -> str:
        self.wfile.write((command + "\n").encode("utf-8"))
        self.wfile.flush()
        response = self.rfile.readline().decode("utf-8", errors="replace").strip()
        return response

    def answer(self):
        return self._send("ANSWER")

    def verbose(self, message: str, level: int = 1):
        safe = message.replace('"', "'")
        return self._send(f'VERBOSE "{safe}" {level}')

    def stream_file(self, sound_name: str, escape_digits: str = ""):
        # sound_name — имя файла БЕЗ расширения, Asterisk сам находит
        # .wav/.gsm/... в стандартных директориях звуков.
        return self._send(f'STREAM FILE {sound_name} "{escape_digits}"')

    def record_file(
        self,
        filename: str,
        fmt: str,
        escape_digits: str,
        timeout_ms: int,
        beep: bool = False,
    ):
        command = f'RECORD FILE {filename} {fmt} "{escape_digits}" {timeout_ms}'

        if beep:
            command += " 0 BEEP"

        return self._send(command)

    def get_variable(self, name: str) -> str | None:
        resp = self._send(f"GET VARIABLE {name}")
        # формат ответа: 200 result=1 (значение)  либо  200 result=0
        if "result=1" in resp and "(" in resp:
            return resp.split("(", 1)[1].rsplit(")", 1)[0]
        return None

    def hangup(self):
        return self._send("HANGUP")


class AGIRequestHandler(socketserver.StreamRequestHandler):
    def handle(self):
        session = AGISession(self.rfile, self.wfile)
        try:
            session.read_environment()
        except Exception:
            log.exception("Не удалось прочитать AGI environment")
            return

        env = session.env
        call_id = env.get("agi_uniqueid", "unknown")
        channel = env.get("agi_channel", "unknown")
        caller_id = env.get("agi_callerid", "unknown")
        # Скрипт-аргумент из agi://host:port/<scenario_id>
        scenario_id = env.get("agi_network_script", "scenario_001")
        session_id = str(uuid.uuid4())

        log_event(
            "call_started",
            call_id=call_id,
            channel=channel,
            caller_id=caller_id,
            scenario_id=scenario_id,
            session_id=session_id,
        )

        try:
            scenario = load_scenario(scenario_id)
            session.answer()
            info_sound = scenario.get("info_sound")
            if info_sound:
                session.stream_file(info_sound)
                log_event(
                    "info_played",
                    call_id=call_id,
                    session_id=session_id,
                    scenario_id=scenario_id,
                    sound=info_sound,
                )
                
            session.verbose(f"Сценарий '{scenario['title']}' запущен", 1)

            for prompt in scenario.get("prompts", []):
                session.stream_file(prompt["sound"])
                
                log_event(
                    "prompt_played",
                    call_id=call_id,
                    session_id=session_id,
                    scenario_id=scenario_id,
                    prompt_text=prompt.get("text", ""),
                )

            record_seconds = int(scenario.get("record_response_seconds", 0))
            if record_seconds > 0:
                # Ответ диспетчера пишем отдельным файлом — пригодится
                # для этапа 5 (STT), сюда его будет проще подать целиком.
                rec_name = f"/recordings/response_{call_id}"
                
                log_event(
                    "recording_started",
                    call_id=call_id,
                    session_id=session_id,
                    file=f"{rec_name}.wav",
                    duration_seconds=record_seconds,
                )
                
                result = session.record_file(
                    rec_name,
                    "wav",
                    "#",
                    record_seconds * 1000,
                    beep=True
                )
                
                log_event(
                    "response_recorded",
                    call_id=call_id,
                    session_id=session_id,
                    file=f"{rec_name}.wav",
                    result=result,
                )

            session.hangup()
        except Exception:
            log.exception("Ошибка во время обработки звонка")
        finally:
            log_event(
                "call_ended",
                call_id=call_id,
                session_id=session_id,
                scenario_id=scenario_id,
            )


class ThreadingAGIServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    # allow_reuse_address — иначе после каждого рестарта контейнера
    # пришлось бы ждать TIME_WAIT перед повторным bind на тот же порт.
    allow_reuse_address = True
    daemon_threads = True


def main():
    server = ThreadingAGIServer((LISTEN_HOST, LISTEN_PORT), AGIRequestHandler)
    log.info("FastAGI virtual_caller слушает %s:%s", LISTEN_HOST, LISTEN_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
