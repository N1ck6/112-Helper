"""«Ухо» звонка: непрерывный поток голоса оператора и детектор речи (VAD).

Asterisk пишет всё, что говорит оператор, в сырой файл (MixMonitor с опцией r(),
формат sln — PCM16 mono 8 кГц без заголовка), с начала и до конца звонка.
Ear читает этот файл по мере роста и по энергии каждого кадра 20 мс решает,
говорит ли оператор. Это даёт две вещи, которых нет у RECORD FILE:

  * перебивание: оператор заговорил, пока звучит собеседник, — реплика собеседника
    останавливается (DialogueRunner шлёт AMI ControlPlayback stop);
  * ни одно слово не теряется: реплика оператора вырезается из потока с запасом
    PREROLL до начала речи, даже если он начал говорить поверх собеседника.

Кадры копятся в памяти (звонок до MAX_CALL_SEC: 5 минут = 4.8 МБ).
"""

import array
import threading
import time
from pathlib import Path

SAMPLE_RATE = 8000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2   # 320 байт PCM16
POLL_SEC = 0.05


def frames_for(seconds: float) -> int:
    return max(1, int(round(seconds * 1000 / FRAME_MS)))


def frame_level(frame: bytes) -> float:
    """Средняя абсолютная амплитуда кадра PCM16 (как порог тишины в DSP Asterisk)."""
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % 2])
    return sum(abs(s) for s in samples) / len(samples) if samples else 0.0


class Ear:
    def __init__(self, path: Path, threshold: float, wait_file_sec: float = 3.0, clock=time.monotonic):
        self.path = Path(path)
        self.threshold = threshold
        self.clock = clock
        self.audio = bytearray()
        self.speech: list[bool] = []          # по кадру: речь или нет
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wait_file_sec = wait_file_sec
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"ear-{self.path.stem[:12]}")

    # --- поток чтения --------------------------------------------------------
    def start(self) -> "Ear":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        pos = 0
        tail = b""
        while not self._stop.is_set():
            try:
                with self.path.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read()
            except FileNotFoundError:
                chunk = b""
            if chunk:
                pos += len(chunk)
                data = tail + chunk
                whole = len(data) - len(data) % FRAME_BYTES
                frames = [data[i:i + FRAME_BYTES] for i in range(0, whole, FRAME_BYTES)]
                tail = data[whole:]
                with self._lock:
                    for fr in frames:
                        self.audio += fr
                        self.speech.append(frame_level(fr) >= self.threshold)
            self._stop.wait(POLL_SEC)

    # --- запросы из голосового цикла ----------------------------------------
    def available(self) -> bool:
        """Файл потока появился — Asterisk пишет голос оператора (иначе — RECORD FILE)."""
        deadline = self.clock() + self._wait_file_sec
        while self.clock() < deadline:
            if self.path.exists():
                return True
            time.sleep(POLL_SEC)
        return self.path.exists()

    def mark(self) -> int:
        with self._lock:
            return len(self.speech)

    def find_onset(self, since: int, min_frames: int) -> int | None:
        """Первый кадр серии из min_frames кадров речи (допускается 1 кадр тишины внутри)."""
        with self._lock:
            flags = self.speech[since:]
        run, gaps, start = 0, 0, None
        for i, is_speech in enumerate(flags):
            if is_speech:
                if run == 0:
                    start = i
                run += 1
                gaps = 0
                if run >= min_frames:
                    return since + start
            elif run:
                gaps += 1
                if gaps > 1:
                    run, gaps = 0, 0
        return None

    def find_end(self, onset: int, silence_frames: int) -> int | None:
        """Кадр, после которого silence_frames подряд тишины (конец реплики)."""
        with self._lock:
            flags = self.speech[onset:]
        quiet = 0
        for i, is_speech in enumerate(flags):
            quiet = 0 if is_speech else quiet + 1
            if quiet >= silence_frames:
                return onset + i - silence_frames + 1
        return None

    def pcm(self, start: int, end: int) -> bytes:
        with self._lock:
            return bytes(self.audio[max(0, start) * FRAME_BYTES:max(0, end) * FRAME_BYTES])
