"""virtual-caller: FastAGI (Asterisk -> голосовой цикл) + HTTP API (Backend -> звонки).

Оба сервера в одном процессе, потому что делят реестр звонков: API создаёт
звонок, AGI ведёт его и обновляет статус.

    python -m caller
"""

import logging
import socketserver
import threading

from .agi import AGISession, ChannelHungUp
from .ami import AMIClient
from .api import CallControl, make_api_server
from .calls import CallRegistry, TraineeContexts
from .clients import DialogueClient, VoiceClient
from .config import Settings
from .dialogue import DialogueRunner
from .directory import Directory
from .events import EventSink

log = logging.getLogger("virtual_caller")


class ThreadingAGIServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    # без allow_reuse_address после рестарта контейнера bind ждал бы TIME_WAIT
    allow_reuse_address = True
    daemon_threads = True


def make_agi_server(runner: DialogueRunner, host: str, port: int) -> ThreadingAGIServer:
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                runner.handle(AGISession(self.rfile, self.wfile))
            except ChannelHungUp:
                # закрыли до окончания разговора; без переменных AGI — это проба healthcheck
                log.debug("AGI-соединение закрыто без разговора")
            except Exception:
                log.exception("ошибка обработки AGI-соединения")

    return ThreadingAGIServer((host, port), Handler)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    s = Settings.from_env()
    registry = CallRegistry()
    contexts = TraineeContexts()
    directory = Directory.load(s.directory_path)
    events = EventSink(s.sessions_log_path, s.backend_url, fmt=s.backend_events_format, token=s.backend_token,
                       backend_ids=lambda call_id: getattr(registry.get(call_id), "backend", None))
    voice = VoiceClient(s.voice_service_url, s.http_timeout_sec)
    runner = DialogueRunner(s, voice, DialogueClient(s.ml_api_url, s.http_timeout_sec), events, registry,
                            directory, contexts)
    control = CallControl(s, registry, events, AMIClient(s.ami_host, s.ami_port, s.ami_user, s.ami_password),
                          voice, directory, contexts)

    agi_server = make_agi_server(runner, s.agi_host, s.agi_port)
    api_server = make_api_server(control, s.api_host, s.api_port)
    threading.Thread(target=api_server.serve_forever, name="api", daemon=True).start()
    log.info("FastAGI %s:%d, API %s:%d, ML=%s, Backend=%s, служб в справочнике: %d", s.agi_host, s.agi_port,
             s.api_host, s.api_port, s.ml_api_url, s.backend_url or "(только sessions.log)", len(directory.contacts))
    try:
        agi_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        api_server.shutdown()
        agi_server.server_close()


if __name__ == "__main__":
    main()
