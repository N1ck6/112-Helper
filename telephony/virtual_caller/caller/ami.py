"""Минимальный клиент AMI для API звонков: Originate, Hangup, список аккаунтов.

На каждую операцию — своё короткое соединение: проще, чем держать одно
общее с разбором всех событий, и падение Asterisk не оставляет «висящего»
состояния в сервисе.
"""

import socket
import time
import uuid


class AMIError(RuntimeError):
    pass


# Reason из события OriginateResponse -> причина для API/Backend
ORIGINATE_REASONS = {
    0: "unavailable",   # аккаунт не зарегистрирован / канал не создан
    1: "rejected",      # обучающийся сбросил вызов
    3: "no_answer",     # не ответил за RING_TIMEOUT_SEC
    4: "answered",
    5: "busy",
    8: "congestion",
}


class AMIConnection:
    def __init__(self, host: str, port: int, user: str, password: str, timeout: float = 5.0):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.rfile = None

    def __enter__(self) -> "AMIConnection":
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.rfile = self.sock.makefile("rb")
        self.rfile.readline()  # баннер "Asterisk Call Manager/x.y"
        resp = self.request("Login", [("Username", self.user), ("Secret", self.password), ("Events", "on")])
        if resp.get("Response") != "Success":
            self.close()
            raise AMIError(f"AMI login: {resp.get('Message', resp)}")
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.send("Logoff", [])
        except OSError:
            pass
        self.close()

    def close(self) -> None:
        if self.sock:
            self.sock.close()
        self.sock = self.rfile = None

    def read_block(self, timeout: float | None = None) -> dict:
        self.sock.settimeout(timeout if timeout is not None else self.timeout)
        block: dict[str, str] = {}
        while True:
            raw = self.rfile.readline()
            if raw == b"":
                raise AMIError("AMI закрыл соединение")
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                if block:
                    return block
                continue
            key, sep, value = line.partition(":")
            if sep:
                block[key.strip()] = value.strip()

    def send(self, action: str, fields: list[tuple[str, str]]) -> str:
        """fields — список пар: AMI допускает повтор ключа (Variable)."""
        action_id = uuid.uuid4().hex
        lines = [f"Action: {action}", f"ActionID: {action_id}"]
        lines += [f"{k}: {v}" for k, v in fields]
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))
        return action_id

    def request(self, action: str, fields: list[tuple[str, str]]) -> dict:
        """Отправить действие и дождаться ответа с тем же ActionID (события по пути пропускаются)."""
        action_id = self.send(action, fields)
        while True:
            block = self.read_block()
            if block.get("ActionID") == action_id and "Response" in block:
                return block

    def collect(self, action: str, fields: list[tuple[str, str]], item_event: str,
                complete_event: str) -> list[dict]:
        """Действие со списком в ответе (события item_event до complete_event)."""
        action_id = self.send(action, fields)
        items = []
        while True:
            block = self.read_block()
            if block.get("ActionID") != action_id:
                continue
            if block.get("Response") == "Error":
                raise AMIError(block.get("Message", str(block)))
            if block.get("Event") == item_event:
                items.append(block)
            elif block.get("Event") == complete_event:
                return items


class AMIClient:
    def __init__(self, host: str, port: int, user: str, password: str):
        self.params = (host, port, user, password)

    def connect(self) -> AMIConnection:
        return AMIConnection(*self.params)

    def ping(self) -> bool:
        try:
            with self.connect() as ami:
                return ami.request("Ping", []).get("Response") == "Success"
        except (OSError, AMIError):
            return False

    def originate(self, *, call_id: str, channel: str, context: str, variables: dict[str, str],
                  caller_id: str, ring_timeout_sec: int, on_channel=None, exten: str = "s") -> str:
        """Звонок на channel; после ответа канал уходит в context,exten,1.

        exten="s" — учебный звонок (training-run); номер — набор с панели телефона:
        после ответа трубки рабочее место «набирает» exten, как будто нажали кнопки на телефоне.

        Блокирует до ответа/отказа. Возвращает причину из ORIGINATE_REASONS.
        call_id становится UNIQUEID канала (ChannelId) — по нему связываются
        запись, события AGI и API. on_channel(name) вызывается, когда Asterisk
        создал канал (нужно для отбоя во время дозвона).
        """
        fields = [("Channel", channel), ("Context", context), ("Exten", exten), ("Priority", "1"),
                  ("CallerID", caller_id), ("Timeout", str(ring_timeout_sec * 1000)),
                  ("Async", "true"), ("ChannelId", call_id)]
        fields += [("Variable", f"{k}={v}") for k, v in variables.items()]
        with self.connect() as ami:
            action_id = ami.send("Originate", fields)
            deadline = time.monotonic() + ring_timeout_sec + 15
            while time.monotonic() < deadline:
                try:
                    block = ami.read_block(timeout=max(0.5, deadline - time.monotonic()))
                except socket.timeout:
                    break
                if block.get("ActionID") == action_id and block.get("Response") == "Error":
                    raise AMIError(block.get("Message", "Originate отклонён"))
                if block.get("Event") == "Newchannel" and block.get("Uniqueid") == call_id and on_channel:
                    on_channel(block.get("Channel"))
                if block.get("Event") == "OriginateResponse" and block.get("ActionID") == action_id:
                    if block.get("Response") == "Success":
                        return "answered"
                    return ORIGINATE_REASONS.get(int(block.get("Reason", "0") or 0), "failed")
        return "timeout"

    def hangup(self, channel: str) -> None:
        with self.connect() as ami:
            resp = ami.request("Hangup", [("Channel", channel)])
        if resp.get("Response") != "Success":
            raise AMIError(resp.get("Message", "Hangup не выполнен"))

    def channel_alive(self, channel: str) -> bool:
        """Канал ещё существует (разговор не закончен) — для номеров без AGI (эхо-тест)."""
        with self.connect() as ami:
            resp = ami.request("Status", [("Channel", channel)])
        return resp.get("Response") == "Success"

    def endpoints(self) -> list[dict]:
        with self.connect() as ami:
            items = ami.collect("PJSIPShowEndpoints", [], "EndpointList", "EndpointListComplete")
        return [{
            "endpoint": e.get("ObjectName"),
            "state": e.get("DeviceState"),
            "registered": e.get("DeviceState") not in (None, "Unavailable", "Invalid"),
            "active_channels": e.get("ActiveChannels", ""),
        } for e in items]
