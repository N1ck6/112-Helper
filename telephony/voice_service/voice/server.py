"""HTTP API voice-service (stdlib, без веб-фреймворка).

    GET  /health  -> состояние движков (200 ok / 503 degraded)
    POST /stt     -> WAV (Content-Type: audio/wav) или JSON {"path": "..."} -> JSON с текстом
    POST /tts     -> JSON {"text": "..."} -> audio/wav
                     JSON {"text": "...", "save_as": "name"} -> JSON с путём к файлу
                     + "voice": "male" | "female" | имя голоса; "cache": true — файл по хэшу
                       (текст+голос+частота), повторная фраза не синтезируется заново

Заголовок X-Call-Id (необязательный) попадает в лог — связка с call_id.
Контракт подробно: telephony/README.md, раздел «Этап 5».
"""

import hashlib
import json
import logging
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .audio import AudioFormatError, wav_info
from .config import Settings
from .textnorm import normalize_for_tts
from .stt import EngineNotReady, STTEngine, create_stt
from .tts import TTSEngine, TTSResult, create_tts

log = logging.getLogger("voice_service")

SAVE_AS_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
VOICE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
ALLOWED_RATES = (8000, 16000, 22050, 24000, 44100, 48000)


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class VoiceService:
    """Держит движки и их статус. HTTP-слой — отдельно (VoiceHandler)."""

    def __init__(self, settings: Settings, stt: STTEngine | None = None, tts: TTSEngine | None = None):
        self.settings = settings
        self.stt = stt or create_stt(settings)
        self.tts = tts or create_tts(settings)
        self.status = {"stt": {"engine": self.stt.name, "ready": False, "error": None},
                       "tts": {"engine": self.tts.name, "ready": False, "error": None, "voices": []}}

    def load(self) -> None:
        for key, engine in (("stt", self.stt), ("tts", self.tts)):
            started = time.monotonic()
            try:
                engine.load()
                self.status[key]["ready"] = True
                if key == "tts":
                    self.status[key]["voices"] = self.tts.voices()
                log.info("%s engine=%s загружен за %.1f с", key, engine.name, time.monotonic() - started)
            except Exception as exc:  # сервис стартует, /health покажет причину
                self.status[key]["error"] = str(exc)
                log.error("%s engine=%s не загружен: %s", key, engine.name, exc)

    @property
    def healthy(self) -> bool:
        return all(s["ready"] for s in self.status.values())

    def _require(self, key: str) -> None:
        if not self.status[key]["ready"]:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE,
                           f"{key} engine={self.status[key]['engine']} не готов: {self.status[key]['error']}")

    def resolve_audio_path(self, raw: str) -> Path:
        root = self.settings.audio_root.resolve()
        p = Path(raw)
        path = (p if p.is_absolute() else root / p).resolve()
        if root != path and root not in path.parents:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"path вне {root}")
        if not path.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, f"файл не найден: {path}")
        return path

    def stt_request(self, wav: bytes, language: str | None) -> dict:
        self._require("stt")
        try:
            wav_info(wav)
            started = time.monotonic()
            result = self.stt.transcribe(wav, language=language)
        except AudioFormatError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        data = result.to_dict()
        data["processing_sec"] = round(time.monotonic() - started, 3)
        return data

    def tts_request(self, payload: dict):
        self._require("tts")
        text = normalize_for_tts(str(payload.get("text", "")))
        if not text:
            raise ApiError(HTTPStatus.BAD_REQUEST, "поле text пустое")
        if len(text) > self.settings.max_tts_chars:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"text длиннее {self.settings.max_tts_chars} символов")
        try:
            rate = int(payload.get("sample_rate", self.settings.tts_sample_rate))
        except (TypeError, ValueError):
            raise ApiError(HTTPStatus.BAD_REQUEST, "sample_rate должен быть числом") from None
        if rate not in ALLOWED_RATES:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"sample_rate из {ALLOWED_RATES}")
        voice = payload.get("voice")
        if voice is not None and not VOICE_RE.match(str(voice)):
            raise ApiError(HTTPStatus.BAD_REQUEST, "voice: male | female | имя голоса [A-Za-z0-9_.-]")
        save_as = payload.get("save_as")
        if payload.get("cache"):
            # имя по содержимому: одна и та же фраза тем же голосом синтезируется один раз
            digest = hashlib.sha1(f"{self.tts.name}|{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
            save_as = f"cache_{voice or 'default'}_{digest}"
        if save_as is not None:
            save_as = str(save_as).removesuffix(".wav")
            if not SAVE_AS_RE.match(save_as) or save_as.startswith("."):
                raise ApiError(HTTPStatus.BAD_REQUEST, "save_as: только [A-Za-z0-9_.-], до 100 символов")
        out_dir = self.settings.tts_output_dir
        path = out_dir / f"{save_as}.wav" if save_as is not None else None
        if payload.get("cache") and path.is_file():
            info = wav_info(path.read_bytes())
            return TTSResult(b"", info.sample_rate, round(info.duration_sec, 3), "cache"), 0.0, path
        started = time.monotonic()
        result = self.tts.synthesize(text, rate, voice)
        processing = round(time.monotonic() - started, 3)
        if path is None:
            return result, processing, None
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(result.wav)
        tmp.replace(path)  # атомарно: Asterisk не увидит недописанный файл
        return result, processing, path


class VoiceHandler(BaseHTTPRequestHandler):
    service: VoiceService  # проставляется в make_server()
    server_version = "voice-service/1.0"

    # --- ответы ---------------------------------------------------------
    def _send(self, status: HTTPStatus, body: bytes, content_type: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, data: dict):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "пустое тело запроса")
        if length > self.service.settings.max_upload_bytes:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                           f"тело больше {self.service.settings.max_upload_bytes} байт")
        return self.rfile.read(length)

    def _read_json(self) -> dict:
        try:
            data = json.loads(self._read_body().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"невалидный JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "ожидается JSON-объект")
        return data

    # --- маршрутизация --------------------------------------------------
    def do_GET(self):
        self._dispatch({"/health": self._health})

    def do_POST(self):
        self._dispatch({"/stt": self._stt, "/tts": self._tts})

    def _dispatch(self, routes: dict):
        started = time.monotonic()
        url = urlparse(self.path)
        handler = routes.get(url.path)
        status = HTTPStatus.OK
        try:
            if handler is None:
                raise ApiError(HTTPStatus.NOT_FOUND, f"нет маршрута {self.command} {url.path}")
            status = handler(parse_qs(url.query)) or HTTPStatus.OK
        except ApiError as exc:
            status = exc.status
            self._json(status, {"error": exc.message})
        except EngineNotReady as exc:
            status = HTTPStatus.SERVICE_UNAVAILABLE
            self._json(status, {"error": str(exc)})
        except Exception as exc:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            log.exception("Ошибка обработки %s %s", self.command, url.path)
            self._json(status, {"error": f"{type(exc).__name__}: {exc}"})
        finally:
            log.info("%s %s -> %d за %.3f с call_id=%s", self.command, url.path, int(status),
                     time.monotonic() - started, self.headers.get("X-Call-Id", "-"))

    # --- эндпоинты -----------------------------------------------------
    def _health(self, _query):
        status = HTTPStatus.OK if self.service.healthy else HTTPStatus.SERVICE_UNAVAILABLE
        self._json(status, {"status": "ok" if self.service.healthy else "degraded", **self.service.status})
        return status

    def _stt(self, query):
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        language = (query.get("language") or [None])[0]
        if ctype == "application/json":
            payload = self._read_json()
            if not payload.get("path"):
                raise ApiError(HTTPStatus.BAD_REQUEST, "в JSON нужно поле path")
            wav = self.service.resolve_audio_path(str(payload["path"])).read_bytes()
            language = payload.get("language") or language
        else:
            wav = self._read_body()
        self._json(HTTPStatus.OK, self.service.stt_request(wav, language))

    def _tts(self, _query):
        result, processing, path = self.service.tts_request(self._read_json())
        meta = {"engine": result.engine, "sample_rate": result.sample_rate,
                "duration_sec": result.duration_sec, "processing_sec": processing}
        if path is None:
            self._send(HTTPStatus.OK, result.wav, "audio/wav", {
                "X-Engine": result.engine, "X-Sample-Rate": result.sample_rate,
                "X-Duration-Sec": result.duration_sec, "X-Processing-Sec": processing})
        else:
            # asterisk_sound — путь без расширения для AGI STREAM FILE
            # (каталог TTS_OUTPUT_DIR смонтирован в Asterisk по тому же пути).
            self._json(HTTPStatus.OK, {**meta, "path": str(path), "asterisk_sound": str(path.with_suffix(""))})

    def log_message(self, fmt, *args):  # стандартный access-лог заменён своим в _dispatch
        pass


def make_server(service: VoiceService, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundVoiceHandler", (VoiceHandler,), {"service": service})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve_in_thread(service: VoiceService, host: str = "127.0.0.1", port: int = 0):
    """Для тестов: поднять сервер в фоне, вернуть (server, base_url)."""
    server = make_server(service, host, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{host}:{server.server_address[1]}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    settings = Settings.from_env()
    service = VoiceService(settings)
    service.load()
    server = make_server(service, settings.host, settings.port)
    log.info("voice-service слушает %s:%d (stt=%s, tts=%s)", settings.host, settings.port,
             service.stt.name, service.tts.name)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
