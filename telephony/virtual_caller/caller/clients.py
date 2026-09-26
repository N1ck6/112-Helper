"""HTTP-клиенты внешних сервисов: voice-service (STT/TTS) и ML (реплики абонента).

Контракты — telephony/API.md. Реализация ML может быть настоящей или mock
(telephony/mocks) — virtual-caller видит только ML_API_URL.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class ServiceError(RuntimeError):
    """Внешний сервис недоступен или ответил ошибкой."""


def post_json(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", errors="replace")
        raise ServiceError(f"{url} -> HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ServiceError(f"{url} недоступен: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServiceError(f"{url} вернул не JSON: {exc}") from exc


def get_json(url: str, timeout: float) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return exc.code, {}
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ServiceError(f"{url} недоступен: {exc}") from exc


class VoiceClient:
    """voice-service: TTS в файл для Asterisk, STT файла из /recordings."""

    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url
        self.timeout = timeout

    def synthesize_to_file(self, text: str, call_id: str, voice: str | None = None) -> str:
        """Возвращает путь без расширения для STREAM FILE (/tts/<name>).

        cache=true: одинаковые фразы («Слушаю вас») синтезируются один раз.
        """
        data = post_json(f"{self.base_url}/tts", {"text": text, "voice": voice, "cache": True},
                         self.timeout, {"X-Call-Id": call_id})
        sound = data.get("asterisk_sound")
        if not sound:
            raise ServiceError(f"/tts не вернул asterisk_sound: {data}")
        return sound

    def transcribe_file(self, filename: str, call_id: str) -> str:
        """filename — относительно /recordings (общий том Asterisk и voice-service)."""
        data = post_json(f"{self.base_url}/stt", {"path": filename},
                         self.timeout, {"X-Call-Id": call_id})
        return str(data.get("text", "")).strip()

    def health(self) -> bool:
        try:
            status, _ = get_json(f"{self.base_url}/health", 3)
        except ServiceError:
            return False
        return status == 200


@dataclass
class DialogueReply:
    reply_text: str
    end_call: bool


class DialogueClient:
    """ML API: следующая реплика абонента по истории разговора (stateless)."""

    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url
        self.timeout = timeout

    def next_turn(self, *, session_id: str, scenario_id: str, call_id: str, turn: int,
                  history: list[dict], operator_text: str | None, call_type: str = "incident_112",
                  persona: dict | None = None, context: dict | None = None) -> DialogueReply:
        data = post_json(f"{self.base_url}/dialogue/turn", {
            "session_id": session_id,
            "scenario_id": scenario_id,
            "call_id": call_id,
            "call_type": call_type,
            "persona": persona,
            "context": context or {},
            "turn": turn,
            "history": history,
            "operator_text": operator_text,
        }, self.timeout, {"X-Call-Id": call_id})
        if not isinstance(data.get("reply_text", ""), str):
            raise ServiceError(f"ML: reply_text должен быть строкой: {data}")
        return DialogueReply(reply_text=data.get("reply_text", "").strip(),
                             end_call=bool(data.get("end_call", False)))
