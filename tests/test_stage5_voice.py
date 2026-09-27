"""Этап 5 — STT/TTS-интерфейсы (telephony/voice_service).

Две группы:
  * unit  — без Docker: движки mock + HTTP-сервер в потоке. Проверяют
            контракт API, WAV-утилиты, фабрики движков.
  * integration — к запущенному контейнеру voice-service (порт 8091);
            skip, если он не поднят. С реальными движками проверяет
            цикл Text -> TTS -> Audio -> STT -> Text.

    pytest tests/test_stage5_voice.py -v
"""

import dataclasses
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "telephony" / "voice_service"))

from voice import audio  # noqa: E402
from voice.config import Settings  # noqa: E402
from voice.server import VoiceService, serve_in_thread  # noqa: E402
from voice.stt import create_stt  # noqa: E402
from voice.stt.mock import MockSTT  # noqa: E402
from voice.tts import create_tts  # noqa: E402
from voice.tts.mock import MockTTS  # noqa: E402

VOICE_URL = os.environ.get("VOICE_SERVICE_URL", "http://localhost:8091")


def _http(method: str, url: str, body: bytes | None = None, ctype: str | None = None):
    req = urllib.request.Request(url, data=body, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _post_json(url: str, data: dict):
    return _http("POST", url, json.dumps(data).encode("utf-8"), "application/json")


# ---------------------------------------------------------------- unit ---

@pytest.fixture
def settings(tmp_path, monkeypatch):
    for k in ("STT_ENGINE", "TTS_ENGINE", "MOCK_STT_TEXT"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    (tmp_path / "recordings").mkdir()
    return dataclasses.replace(s, audio_root=tmp_path / "recordings", tts_output_dir=tmp_path / "tts",
                               models_dir=tmp_path / "models")


@pytest.fixture
def local_api(settings):
    service = VoiceService(settings, stt=MockSTT("тестовый текст"), tts=MockTTS())
    service.load()
    server, url = serve_in_thread(service)
    yield url, settings
    server.shutdown()
    server.server_close()


def test_resample_and_mono():
    stereo_44k = audio.tone_wav(0.5, 44100)
    out = audio.to_wav_mono16(stereo_44k, 8000)
    info = audio.wav_info(out)
    assert (info.sample_rate, info.channels, info.sample_width) == (8000, 1, 2)
    assert abs(info.duration_sec - 0.5) < 0.02


def test_linear_resampler_length():
    pcm, _ = audio.read_pcm16_mono(audio.tone_wav(1.0, 22050))
    assert abs(len(audio._resample_linear(pcm, 22050, 8000)) // 2 - 8000) <= 1


def test_wav_info_rejects_garbage():
    with pytest.raises(audio.AudioFormatError):
        audio.wav_info(b"not a wav at all")


def test_factories(settings):
    assert create_stt(settings).name == "mock"
    assert create_tts(settings).name == "mock"
    with pytest.raises(ValueError):
        create_stt(dataclasses.replace(settings, stt_engine="nope"))
    with pytest.raises(ValueError):
        create_tts(dataclasses.replace(settings, tts_engine="nope"))


def test_real_engines_report_missing_models(settings):
    """Без моделей сервис стартует, но /health честно показывает причину."""
    service = VoiceService(dataclasses.replace(settings, stt_engine="faster_whisper", tts_engine="piper"))
    service.load()
    assert not service.healthy
    assert "download_models.py" in service.status["stt"]["error"] or "faster-whisper" in service.status["stt"]["error"]
    assert "download_models.py" in service.status["tts"]["error"] or "piper" in service.status["tts"]["error"]


def test_health_ok(local_api):
    url, _ = local_api
    status, _, body = _http("GET", f"{url}/health")
    data = json.loads(body)
    assert status == 200 and data["status"] == "ok"
    assert data["stt"]["engine"] == "mock" and data["tts"]["ready"] is True


def test_tts_returns_wav_8k(local_api):
    url, _ = local_api
    status, headers, body = _post_json(f"{url}/tts", {"text": "Здравствуйте, у меня пожар"})
    assert status == 200 and headers["Content-Type"] == "audio/wav"
    info = audio.wav_info(body)
    assert (info.sample_rate, info.channels) == (8000, 1)
    assert float(headers["X-Duration-Sec"]) == pytest.approx(info.duration_sec, abs=0.01)


def test_tts_save_as_for_asterisk(local_api):
    url, settings = local_api
    status, _, body = _post_json(f"{url}/tts", {"text": "Адрес: Ленина пять", "save_as": "call1_prompt1"})
    data = json.loads(body)
    assert status == 200
    path = Path(data["path"])
    assert path == settings.tts_output_dir / "call1_prompt1.wav" and path.exists()
    assert data["asterisk_sound"] == str(path.with_suffix(""))


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "x", "sample_rate": 1234},
                                     {"text": "x", "save_as": "../evil"}, {"text": "x" * 5000}])
def test_tts_validation(local_api, payload):
    url, _ = local_api
    status, _, body = _post_json(f"{url}/tts", payload)
    assert status == 400 and "error" in json.loads(body)


def test_stt_raw_wav(local_api):
    url, _ = local_api
    status, _, body = _http("POST", f"{url}/stt?language=ru", audio.tone_wav(1.0, 8000), "audio/wav")
    data = json.loads(body)
    assert status == 200
    assert data["text"] == "тестовый текст" and data["language"] == "ru"
    assert data["duration_sec"] == pytest.approx(1.0, abs=0.01)
    assert {"segments", "engine", "processing_sec"} <= data.keys()


def test_stt_by_path_inside_recordings(local_api):
    url, settings = local_api
    (settings.audio_root / "response_1.wav").write_bytes(audio.tone_wav(0.5, 8000))
    status, _, body = _post_json(f"{url}/stt", {"path": "response_1.wav"})
    assert status == 200 and json.loads(body)["duration_sec"] == pytest.approx(0.5, abs=0.01)


def test_stt_path_traversal_blocked(local_api):
    url, _ = local_api
    status, _, _ = _post_json(f"{url}/stt", {"path": "../../etc/passwd"})
    assert status == 400


def test_stt_rejects_non_wav(local_api):
    url, _ = local_api
    status, _, _ = _http("POST", f"{url}/stt", b"garbage-bytes", "audio/wav")
    assert status == 400


def test_unknown_route(local_api):
    url, _ = local_api
    assert _http("GET", f"{url}/nope")[0] == 404


# --------------------------------------------------------- integration ---

@pytest.fixture
def remote_health():
    try:
        status, _, body = _http("GET", f"{VOICE_URL}/health")
    except OSError as exc:
        pytest.skip(f"voice-service недоступен на {VOICE_URL} ({exc}). "
                    f"Запустите: cd telephony && docker compose up --build -d")
    data = json.loads(body)
    if status != 200:
        pytest.fail(f"voice-service degraded: {data}")
    return data


def test_integration_tts_stt_roundtrip(remote_health):
    phrase = "Помогите, пожар на улице Ленина"
    status, _, wav = _post_json(f"{VOICE_URL}/tts", {"text": phrase, "sample_rate": 8000})
    assert status == 200 and audio.wav_info(wav).sample_rate == 8000
    status, _, body = _http("POST", f"{VOICE_URL}/stt?language=ru", wav, "audio/wav")
    assert status == 200
    text = json.loads(body)["text"]
    assert text
    if remote_health["stt"]["engine"] != "mock" and remote_health["tts"]["engine"] != "mock":
        assert "пожар" in text.lower(), f"STT не распознал синтезированную фразу: {text!r}"


# ------------------------------------------- голоса, кэш, нормализация ---

def test_tts_voice_and_cache(local_api):
    url, settings = local_api
    payload = {"text": "Слушаю вас", "voice": "male", "cache": True}
    status, _, body = _post_json(f"{url}/tts", payload)
    first = json.loads(body)
    assert status == 200 and "cache_male_" in first["asterisk_sound"]
    status, _, body = _post_json(f"{url}/tts", payload)
    second = json.loads(body)
    assert second["path"] == first["path"] and second["engine"] == "cache" and second["processing_sec"] == 0.0
    # другой голос — другой файл; мужской mock-голос ниже тоном, но той же длины
    status, _, body = _post_json(f"{url}/tts", {**payload, "voice": "female"})
    assert json.loads(body)["path"] != first["path"]
    assert _post_json(f"{url}/tts", {"text": "x", "voice": "../evil"})[0] == 400


def test_mock_tts_voices_differ():
    male = MockTTS().synthesize("проверка", 8000, "male").wav
    female = MockTTS().synthesize("проверка", 8000, "female").wav
    assert male != female and len(male) == len(female)


def test_text_normalization_for_addresses():
    from voice.textnorm import normalize_for_tts
    assert normalize_for_tts("Москва, ул. Ясный проезд, д. 10, кв. 5") == \
        "Москва, улица Ясный проезд, дом 10, квартира 5"
    assert normalize_for_tts("Тверской б-р, 14") == "Тверской бульвар, 14"
    assert normalize_for_tts("Шоссейная ул., 62") == "Шоссейная улица, 62"
    assert normalize_for_tts("Помогите! Пожар.") == "Помогите! Пожар."
