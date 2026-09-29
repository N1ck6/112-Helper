"""Настройки virtual-caller из переменных окружения — одно место на весь сервис."""

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _url(name: str, default: str) -> str:
    # Базовый URL без завершающего "/": пути добавляются в клиентах.
    return _env(name, default).rstrip("/")


@dataclass(frozen=True)
class Settings:
    # FastAGI (Asterisk -> virtual-caller) и HTTP API (Backend -> virtual-caller)
    agi_host: str
    agi_port: int
    api_host: str
    api_port: int
    # Внешние сервисы. BACKEND_URL пустой -> события только в sessions.log.
    voice_service_url: str
    ml_api_url: str
    backend_url: str
    # Формат событий для BACKEND_URL: raw — как в SSE, backend — контракт
    # backend/docs/INTEGRATION.md §2.2 (ringing/answered/ended…) с заголовком X-Telephony-Token
    backend_events_format: str
    backend_token: str
    http_timeout_sec: float
    # AMI — для исходящих вызовов, отбоя и статуса аккаунтов
    ami_host: str
    ami_port: int
    ami_user: str
    ami_password: str
    # Исходящий учебный вызов
    ring_timeout_sec: int
    outbound_caller_id: str
    # Голосовой цикл
    max_turns: int
    max_call_sec: int
    max_utterance_sec: int
    silence_sec: int
    min_speech_sec: float
    # Перебивание собеседника и запись без потерь (ear.py): поток голоса оператора от Asterisk
    barge_in: bool
    barge_in_min_sec: float
    vad_threshold: float
    recordings_local_dir: Path
    fallback_sound: str
    # Справочник служб, CORS для frontend (браузер ходит в API напрямую)
    directory_path: Path
    cors_origins: str
    ringback_sec: int
    # Звонки, которые поднимает Backend (POST /api/v1/calls/originate)
    default_trainee: str
    default_112_scenario: str
    # Данные
    sessions_log_path: Path
    recordings_dir: str
    recordings_base_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            agi_host=_env("AGI_HOST", "0.0.0.0"),
            agi_port=int(_env("AGI_PORT", _env("LISTEN_PORT", "4573"))),
            api_host=_env("API_HOST", "0.0.0.0"),
            api_port=int(_env("API_PORT", "8092")),
            voice_service_url=_url("VOICE_SERVICE_URL", "http://voice-service:8091"),
            ml_api_url=_url("ML_API_URL", "http://ml:8000"),
            backend_url=os.environ.get("BACKEND_URL", "").strip().rstrip("/"),
            backend_events_format=_env("BACKEND_EVENTS_FORMAT", "backend").lower(),
            backend_token=_env("TELEPHONY_WEBHOOK_TOKEN", ""),
            http_timeout_sec=float(_env("HTTP_TIMEOUT_SEC", "30")),
            ami_host=_env("AMI_HOST", "asterisk"),
            ami_port=int(_env("AMI_PORT", "5038")),
            ami_user=_env("AMI_USER", "call-control"),
            ami_password=_env("AMI_PASSWORD", "changeme_ami_pass"),
            ring_timeout_sec=int(_env("RING_TIMEOUT_SEC", "30")),
            outbound_caller_id=_env("OUTBOUND_CALLER_ID", '"Учебный вызов" <700>'),
            max_turns=int(_env("MAX_TURNS", "12")),
            max_call_sec=int(_env("MAX_CALL_SEC", "300")),
            max_utterance_sec=int(_env("MAX_UTTERANCE_SEC", "20")),
            silence_sec=int(_env("SILENCE_SEC", "4")),
            min_speech_sec=float(_env("MIN_SPEECH_SEC", "0.3")),
            barge_in=_env("BARGE_IN", "1") not in ("0", "false", "no"),
            barge_in_min_sec=float(_env("BARGE_IN_MIN_SEC", "0.3")),
            vad_threshold=float(_env("VAD_THRESHOLD", "400")),
            recordings_local_dir=Path(_env("RECORDINGS_LOCAL_DIR", "/recordings")),
            fallback_sound=_env("FALLBACK_SOUND", "beep"),
            directory_path=Path(_env("DIRECTORY_PATH", str(Path(__file__).parent.parent / "directory.json"))),
            cors_origins=_env("CORS_ORIGINS", "*"),
            ringback_sec=int(_env("RINGBACK_SEC", "3")),
            default_trainee=_env("DEFAULT_TRAINEE", "ws01"),
            default_112_scenario=_env("DEFAULT_112_SCENARIO", "scenario_001"),
            sessions_log_path=Path(_env("SESSIONS_LOG_PATH", "/data/sessions.log")),
            recordings_dir=_env("RECORDINGS_DIR", "/recordings"),
            recordings_base_url=_url("RECORDINGS_BASE_URL", "http://localhost:8090"),
        )
