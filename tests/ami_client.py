"""
Минимальный клиент AMI (Asterisk Manager Interface) для автотестов.
"""

from __future__ import annotations

import socket
import time


class AMIError(RuntimeError):
    pass


class AMIClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.rfile = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self.rfile = self.sock.makefile("rb")
        # Asterisk сразу после коннекта присылает баннер вида
        # "Asterisk Call Manager/x.y.z\r\n" — считываем и отбрасываем.
        self.rfile.readline()

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None
            self.rfile = None

    def _read_block(self) -> dict:
        """Читает один блок Key: Value до пустой строки."""
        block = {}
        while True:
            raw = self.rfile.readline()
            if raw == b"":
                raise AMIError("Соединение закрыто сервером AMI")
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                break
            if ":" in line:
                key, _, value = line.partition(":")
                block[key.strip()] = value.strip()
        return block

    def send_action(self, action: str, **fields) -> dict:
        lines = [f"Action: {action}"]
        for key, value in fields.items():
            lines.append(f"{key}: {value}")
        payload = "\r\n".join(lines) + "\r\n\r\n"
        self.sock.sendall(payload.encode("utf-8"))
        return self._read_block()

    def login(self, username: str, secret: str):
        resp = self.send_action("Login", Username=username, Secret=secret)
        if resp.get("Response") != "Success":
            raise AMIError(f"AMI login не удался: {resp}")
        return resp

    def ping(self) -> dict:
        return self.send_action("Ping")

    def originate_and_wait_hangup(
        self,
        channel: str,
        timeout_s: float = 15.0,
        **fields,
    ) -> list[dict]:
        """Инициирует звонок и собирает события до Hangup (или таймаута).

        `**fields` передаётся в AMI-действие Originate как есть — вызывающий
        код сам решает, что подходит для его сценария:
          - Context / Exten / Priority — запустить конкретный шаг dialplan'а
            на канале сразу после ответа;
          - Application / Data — выполнить конкретное приложение.

        Возвращает список всех прочитанных блоков-событий — тесты сами
        ищут в них то, что им нужно (Newchannel/Newexten/Hangup/и т.п.).
        Если Hangup так и не пришёл до истечения timeout_s — не бросает
        исключение, просто возвращает то, что успело накопиться (вызывающий
        тест сам решает, считать ли это ошибкой).
        """
        self.send_action(
            "Originate",
            Channel=channel,
            Async="true",
            **fields,
        )
        events = []
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                self.sock.settimeout(max(0.5, deadline - time.monotonic()))
                block = self._read_block()
            except socket.timeout:
                break
            events.append(block)
            if block.get("Event") == "Hangup":
                break
        return events

    def logoff(self):
        try:
            self.send_action("Logoff")
        except Exception:
            pass
