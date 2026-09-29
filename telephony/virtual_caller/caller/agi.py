"""Минимальный клиент протокола AGI поверх сокета FastAGI.

Протокол:
  1) Asterisk присылает окружение: строки "agi_xxx: значение", конец — пустая строка.
  2) Мы шлём команду строкой, Asterisk отвечает "200 result=N [(data)] [endpos=M]".
  3) Если абонент положил трубку, Asterisk присылает отдельную строку "HANGUP",
     а команды на мёртвом канале получают "511 ...".

Реализованы только команды, нужные сценарию.
"""

import re
from dataclasses import dataclass

RESULT_RE = re.compile(r"result=(-?\d+)")
DATA_RE = re.compile(r"\((.*)\)")
ENDPOS_RE = re.compile(r"endpos=(\d+)")


class ChannelHungUp(Exception):
    """Канал закрыт (абонент положил трубку или соединение с Asterisk разорвано)."""


@dataclass
class AGIResponse:
    code: int
    result: int
    data: str | None
    endpos: int | None
    raw: str


def parse_response(line: str) -> AGIResponse:
    code_str = line[:3]
    code = int(code_str) if code_str.isdigit() else 0
    m = RESULT_RE.search(line)
    d = DATA_RE.search(line)
    e = ENDPOS_RE.search(line)
    return AGIResponse(
        code=code,
        result=int(m.group(1)) if m else 0,
        data=d.group(1) if d else None,
        endpos=int(e.group(1)) if e else None,
        raw=line,
    )


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', "'") + '"'


class AGISession:
    def __init__(self, rfile, wfile):
        self.rfile = rfile
        self.wfile = wfile
        self.env: dict[str, str] = {}
        self.hungup = False

    def _readline(self) -> str:
        raw = self.rfile.readline()
        if raw == b"":
            self.hungup = True
            raise ChannelHungUp("соединение AGI закрыто")
        return raw.decode("utf-8", errors="replace").strip("\r\n")

    def read_environment(self) -> dict[str, str]:
        while True:
            line = self._readline()
            if line == "":
                return self.env
            key, sep, value = line.partition(":")
            if sep:
                self.env[key.strip()] = value.strip()

    def command(self, cmd: str) -> AGIResponse:
        if self.hungup:
            raise ChannelHungUp(f"канал закрыт, команда {cmd.split()[0]} не отправлена")
        self.wfile.write((cmd + "\n").encode("utf-8"))
        self.wfile.flush()
        while True:
            line = self._readline()
            if line.strip() == "HANGUP":
                # асинхронное уведомление об отбое; ответ на команду идёт следом
                self.hungup = True
                continue
            if line.startswith("520-"):
                # многострочная ошибка синтаксиса, заканчивается строкой "520 ..."
                while not line.startswith("520 "):
                    line = self._readline()
            break
        resp = parse_response(line)
        if resp.code == 511:
            self.hungup = True
            raise ChannelHungUp(line)
        return resp

    # --- команды -------------------------------------------------------
    def answer(self) -> AGIResponse:
        return self.command("ANSWER")

    def verbose(self, message: str, level: int = 1) -> AGIResponse:
        return self.command(f"VERBOSE {_quote(message)} {level}")

    def get_variable(self, name: str) -> str | None:
        resp = self.command(f"GET VARIABLE {name}")
        return resp.data if resp.result == 1 else None

    def is_alive(self) -> bool:
        try:
            return self.command("CHANNEL STATUS").result >= 0
        except ChannelHungUp:
            return False

    def stream_file(self, sound: str, escape_digits: str = "") -> AGIResponse:
        """sound — имя без расширения, можно абсолютный путь (/tts/<name>).

        result=-1 бывает и при отбое, и при отсутствии файла — различаем через is_alive().
        """
        resp = self.command(f"STREAM FILE {sound} {_quote(escape_digits)}")
        if resp.result == -1 and not self.is_alive():
            raise ChannelHungUp("отбой во время воспроизведения")
        return resp

    def record_file(self, path: str, fmt: str = "wav", escape_digits: str = "#",
                    timeout_ms: int = 20000, silence_sec: int = 0, beep: bool = False) -> AGIResponse:
        """Запись с канала до timeout_ms, DTMF из escape_digits или silence_sec тишины.

        Тишина считается и с начала записи: если оператор молчит silence_sec, запись заканчивается.
        """
        cmd = f"RECORD FILE {path} {fmt} {_quote(escape_digits)} {timeout_ms} 0"
        if beep:
            cmd += " BEEP"
        if silence_sec > 0:
            cmd += f" s={silence_sec}"
        resp = self.command(cmd)
        if resp.result == -1:
            if resp.data == "writefile":
                raise OSError(f"Asterisk не смог создать файл записи {path}")
            if not self.is_alive():
                raise ChannelHungUp("отбой во время записи")
        return resp

    def wait_for_digit(self, timeout_ms: int) -> str | None:
        """Ждать DTMF до timeout_ms, всё это время канал читается (звук идёт в MixMonitor)."""
        resp = self.command(f"WAIT FOR DIGIT {timeout_ms}")
        if resp.result == -1:
            raise ChannelHungUp("отбой во время ожидания реплики")
        return chr(resp.result) if resp.result > 0 else None

    def hangup(self) -> None:
        try:
            self.command("HANGUP")
        except ChannelHungUp:
            pass
