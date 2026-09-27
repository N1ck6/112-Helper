"""WAV-утилиты без внешних зависимостей (+ ffmpeg, если он есть).

Внутренний формат обмена между модулями: WAV, PCM 16 бит, моно.
"""

import array
import io
import logging
import math
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass

log = logging.getLogger(__name__)


class AudioFormatError(ValueError):
    """Вход не является поддерживаемым WAV."""


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    channels: int
    sample_width: int
    frames: int

    @property
    def duration_sec(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0


def wav_info(data: bytes) -> WavInfo:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return WavInfo(w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioFormatError(f"не WAV PCM: {exc}") from exc


def pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def read_pcm16_mono(data: bytes) -> tuple[bytes, int]:
    """WAV -> (PCM16 mono, sample_rate). Поддерживает 16-бит моно/стерео."""
    info = wav_info(data)
    if info.sample_width != 2:
        raise AudioFormatError(f"нужен PCM 16 бит, получено {info.sample_width * 8} бит")
    with wave.open(io.BytesIO(data), "rb") as w:
        frames = w.readframes(w.getnframes())
    if info.channels == 1:
        return frames, info.sample_rate
    samples = array.array("h", frames)
    if sys.byteorder == "big":
        samples.byteswap()
    ch = info.channels
    mono = array.array("h", (sum(samples[i:i + ch]) // ch for i in range(0, len(samples), ch)))
    if sys.byteorder == "big":
        mono.byteswap()
    return mono.tobytes(), info.sample_rate


def _resample_linear(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Запасной ресемплер (линейная интерполяция), если нет ffmpeg."""
    src = array.array("h", pcm)
    if sys.byteorder == "big":
        src.byteswap()
    if not src:
        return b""
    n_out = max(1, int(len(src) * dst_rate / src_rate))
    step = src_rate / dst_rate
    out = array.array("h")
    last = len(src) - 1
    for i in range(n_out):
        pos = i * step
        j = int(pos)
        if j >= last:
            out.append(src[last])
            continue
        frac = pos - j
        out.append(int(src[j] + (src[j + 1] - src[j]) * frac))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def to_wav_mono16(data: bytes, sample_rate: int) -> bytes:
    """Привести WAV к PCM16 моно с заданной частотой.

    ffmpeg (есть в Docker-образе) даёт ресемплинг с фильтрацией;
    без него — линейная интерполяция (достаточно для тестов).
    """
    info = wav_info(data)
    if info.channels == 1 and info.sample_width == 2 and info.sample_rate == sample_rate:
        return data
    if shutil.which("ffmpeg"):
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
             "-ac", "1", "-ar", str(sample_rate), "-sample_fmt", "s16", "-f", "wav", "pipe:1"],
            input=data, capture_output=True, check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            # ffmpeg в pipe пишет размер RIFF = 0xFFFFFFFF; пересобираем
            # чистый заголовок, чтобы Asterisk/wave читали файл корректно.
            pcm, rate = _pcm_from_ffmpeg_wav(proc.stdout)
            return pcm16_to_wav(pcm, rate)
        log.warning("ffmpeg не смог конвертировать (%s), линейный ресемплинг",
                    proc.stderr.decode(errors="replace").strip())
    pcm, rate = read_pcm16_mono(data)
    return pcm16_to_wav(_resample_linear(pcm, rate, sample_rate), sample_rate)


def _pcm_from_ffmpeg_wav(data: bytes) -> tuple[bytes, int]:
    """Разбор WAV из ffmpeg pipe (размеры чанков могут быть 0xFFFFFFFF)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AudioFormatError("ffmpeg вернул не WAV")
    pos, rate = 12, 0
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        body = pos + 8
        if cid == b"fmt ":
            rate = int.from_bytes(data[body + 4:body + 8], "little")
        elif cid == b"data":
            end = len(data) if size in (0, 0xFFFFFFFF) or body + size > len(data) else body + size
            return data[body:end], rate
        pos = body + size + (size & 1)
    raise AudioFormatError("в WAV нет data-чанка")


def tone_wav(duration_sec: float, sample_rate: int, freq: float = 440.0, amplitude: float = 0.3) -> bytes:
    """Синус заданной длительности — для mock-TTS и тестов."""
    n = int(duration_sec * sample_rate)
    peak = int(32767 * amplitude)
    samples = array.array("h", (int(peak * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(n)))
    if sys.byteorder == "big":
        samples.byteswap()
    return pcm16_to_wav(samples.tobytes(), sample_rate)
