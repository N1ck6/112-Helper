"""Перебивание собеседника и реплики оператора без потерь (telephony/virtual_caller/caller/ear.py).

  * unit — поток голоса оператора из файла sln: начало и конец речи, вырезка с запасом,
    голосовой цикл без RECORD FILE (FakeAGI);
  * живая проверка — tests/test_stage8_web.py (прозвон с имитацией диспетчера) и
    лог virtual-caller «оператор перебил собеседника».

    pytest tests/test_stage10_barge_in.py -v
"""

import array
import dataclasses
import math
import sys
import time
import wave

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "telephony" / "virtual_caller"))

from caller.calls import CallRegistry  # noqa: E402
from caller.config import Settings  # noqa: E402
from caller.dialogue import CallContext, DialogueRunner  # noqa: E402
from caller.ear import Ear, frames_for  # noqa: E402
from caller.events import EventSink  # noqa: E402
from test_stage6_dialogue import FakeVoice, _wait  # noqa: E402


def pcm(*parts: tuple[float, int]) -> bytes:
    """Куски (секунды, амплитуда): 0 — тишина, иначе синус 440 Гц."""
    out = array.array("h")
    for sec, amp in parts:
        n = int(sec * 8000)
        out.extend(int(amp * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(n))
    return out.tobytes()


def test_ear_finds_speech_and_pause(tmp_path):
    path = tmp_path / "c1_rx.sln"
    path.write_bytes(pcm((1.0, 0), (1.5, 3000), (0.1, 0), (0.5, 3000), (2.0, 0)))
    ear = Ear(path, threshold=400).start()
    try:
        assert _wait(lambda: ear.mark() >= frames_for(5.0) - 1, 3)
        onset = ear.find_onset(0, frames_for(0.3))
        assert abs(onset - frames_for(1.0)) <= 1
        # пауза 0.1 с внутри речи — не конец реплики, 1 с тишины — конец
        end = ear.find_end(onset, frames_for(1.0))
        assert abs(end - frames_for(3.1)) <= 2
        assert len(ear.pcm(onset, end)) == (end - onset) * 320
    finally:
        ear.stop()


def test_ear_ignores_short_noise(tmp_path):
    path = tmp_path / "c2_rx.sln"
    path.write_bytes(pcm((0.5, 0), (0.1, 5000), (1.0, 0), (0.04, 5000), (1.0, 0)))
    ear = Ear(path, threshold=400).start()
    try:
        assert _wait(lambda: ear.mark() >= frames_for(2.6) - 1, 3)
        assert ear.find_onset(0, frames_for(0.3)) is None
    finally:
        ear.stop()


class StreamAGI:
    """Канал, пока virtual-caller «слушает» поток: WAIT FOR DIGIT и отбой."""

    def __init__(self):
        self.hungup = False
        self.waited = 0

    def wait_for_digit(self, timeout_ms):
        self.waited += 1
        time.sleep(timeout_ms / 1000)
        return None


def test_listen_from_stream_keeps_first_words(tmp_path):
    settings = dataclasses.replace(Settings.from_env(), recordings_local_dir=tmp_path, silence_sec=1,
                                   max_utterance_sec=10, min_speech_sec=0.3)
    path = tmp_path / "c3_rx.sln"
    # оператор начал говорить поверх собеседника: onset уже известен (кадр 50 = 1.0 с)
    path.write_bytes(pcm((1.0, 0), (2.0, 3000), (1.5, 0)))
    voice = FakeVoice(["адрес Ясный проезд десять"])
    runner = DialogueRunner(settings, voice, None, EventSink(tmp_path / "s.log"), CallRegistry())
    ctx = CallContext("c3", "s", "", ear=Ear(path, 400).start())
    try:
        assert _wait(lambda: ctx.ear.mark() >= frames_for(4.4), 3)
        ctx.onset = frames_for(1.0)
        text, audio, _ = runner._listen(StreamAGI(), ctx, 0)
    finally:
        ctx.ear.stop()
    assert text == "адрес Ясный проезд десять" and audio.endswith("c3_op00.wav")
    with wave.open(str(tmp_path / "c3_op00.wav")) as w:
        seconds = w.getnframes() / w.getframerate()
    assert 2.5 <= seconds <= 2.9   # 0.5 с запаса до речи + 2 с речи + 0.2 с хвоста


def test_listen_from_stream_silence_is_empty(tmp_path):
    settings = dataclasses.replace(Settings.from_env(), recordings_local_dir=tmp_path, silence_sec=1)
    path = tmp_path / "c4_rx.sln"
    path.write_bytes(pcm((0.5, 0)))
    runner = DialogueRunner(settings, FakeVoice([]), None, EventSink(tmp_path / "s.log"), CallRegistry())
    ctx = CallContext("c4", "s", "", ear=Ear(path, 400).start())
    agi = StreamAGI()
    try:
        text, _, _ = runner._listen(agi, ctx, 0)
    finally:
        ctx.ear.stop()
    assert text == "" and agi.waited >= 8   # ~2 x SILENCE_SEC ожидания
