"""Голосовой цикл учебного звонка (этап 6).

    ML: реплика абонента -> TTS -> STREAM FILE -> RECORD FILE (до паузы)
    -> STT -> ML: следующая реплика ... пока ML не вернёт end_call
    или не сработает лимит (MAX_TURNS, MAX_CALL_SEC).

Реплики генерирует ML-сервис по истории разговора (stateless API), поэтому
здесь нет логики сценария — только телефония и порядок шагов.
Отказы внешних сервисов не роняют звонок: нет TTS — играем FALLBACK_SOUND,
нет STT — считаем, что оператор молчал; нет ML — завершаем звонок.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass

from .agi import AGISession, ChannelHungUp
from .calls import Call, CallRegistry
from .clients import DialogueClient, ServiceError, VoiceClient
from .config import Settings
from .events import EventSink

log = logging.getLogger("virtual_caller.dialogue")

SAMPLE_RATE = 8000  # формат "wav" в Asterisk: PCM16 mono 8 кГц
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]")


def trainee_from_channel(channel: str | None) -> str | None:
    """PJSIP/alice-00000001 -> alice; для Local/... и прочих — None."""
    if channel and channel.startswith("PJSIP/"):
        return channel[len("PJSIP/"):].rsplit("-", 1)[0]
    return None


@dataclass
class CallContext:
    call_id: str
    session_id: str
    scenario_id: str

    def ids(self) -> dict:
        return {"call_id": self.call_id, "session_id": self.session_id, "scenario_id": self.scenario_id}

    def file_stem(self) -> str:
        return SAFE_NAME_RE.sub("_", self.call_id)


class DialogueRunner:
    def __init__(self, settings: Settings, voice: VoiceClient, dialogue: DialogueClient,
                 events: EventSink, registry: CallRegistry, clock=time.monotonic):
        self.s = settings
        self.voice = voice
        self.dialogue = dialogue
        self.events = events
        self.registry = registry
        self.clock = clock

    # --- вход из FastAGI ------------------------------------------------
    def handle(self, agi: AGISession) -> str:
        env = agi.read_environment()
        call_id = env.get("agi_uniqueid") or str(uuid.uuid4())
        scenario_id = env.get("agi_network_script") or "scenario_001"
        channel = env.get("agi_channel")
        known = self.registry.get(call_id)
        try:
            session_id = agi.get_variable("SESSION_ID") or (known.session_id if known else None)
        except ChannelHungUp:
            session_id = known.session_id if known else None
        session_id = session_id or str(uuid.uuid4())

        if known is None:
            self.registry.add(Call(call_id=call_id, session_id=session_id, scenario_id=scenario_id,
                                   direction="inbound", trainee=trainee_from_channel(channel), channel=channel))
        ctx = CallContext(call_id, session_id, scenario_id)
        call = self.registry.update(call_id, channel=channel, status="in_progress", answered_at=time.time())
        self.events.emit("call.started", **ctx.ids(), direction=call.direction, trainee=call.trainee,
                         channel=channel, caller_id=env.get("agi_callerid"))
        return self.run(agi, ctx)

    # --- цикл диалога ---------------------------------------------------
    def run(self, agi: AGISession, ctx: CallContext) -> str:
        started = self.clock()
        history: list[dict] = []
        operator_text: str | None = None
        reason = "completed"
        try:
            for turn in range(self.s.max_turns):
                t0 = self.clock()
                try:
                    reply = self.dialogue.next_turn(
                        session_id=ctx.session_id, scenario_id=ctx.scenario_id, call_id=ctx.call_id,
                        turn=turn, history=list(history), operator_text=operator_text)
                except ServiceError as exc:
                    self._error(ctx, "ml", exc)
                    agi.stream_file(self.s.fallback_sound)
                    reason = "ml_error"
                    break
                ml_sec = self.clock() - t0

                if reply.reply_text:
                    audio, tts_sec = self._say(agi, ctx, turn, reply.reply_text)
                    history.append({"role": "caller", "text": reply.reply_text})
                    self._utterance(ctx, turn, "caller", reply.reply_text, audio,
                                    {"ml_sec": round(ml_sec, 3), "tts_sec": round(tts_sec, 3)})
                if reply.end_call:
                    break
                if turn == self.s.max_turns - 1:
                    reason = "max_turns"
                    break
                if self.clock() - started >= self.s.max_call_sec:
                    reason = "max_duration"
                    break

                operator_text, audio, stt_sec = self._listen(agi, ctx, turn)
                history.append({"role": "operator", "text": operator_text})
                self._utterance(ctx, turn, "operator", operator_text, audio, {"stt_sec": round(stt_sec, 3)})
        except ChannelHungUp:
            reason = "operator_hangup"
        except Exception as exc:  # звонок не должен повиснуть из-за бага в цикле
            log.exception("ошибка в голосовом цикле call_id=%s", ctx.call_id)
            self._error(ctx, "internal", exc)
            reason = "internal_error"
        finally:
            if not agi.hungup:
                agi.hangup()
            self._finish(ctx, reason, started)
        return reason

    # --- шаги -----------------------------------------------------------
    def _say(self, agi: AGISession, ctx: CallContext, turn: int, text: str) -> tuple[str | None, float]:
        name = f"{ctx.file_stem()}_c{turn:02d}"
        t0 = self.clock()
        try:
            sound = self.voice.synthesize_to_file(text, name, ctx.call_id)
            audio = f"{sound}.wav"
        except ServiceError as exc:
            self._error(ctx, "tts", exc)
            sound, audio = self.s.fallback_sound, None
        tts_sec = self.clock() - t0
        agi.stream_file(sound)
        return audio, tts_sec

    def _listen(self, agi: AGISession, ctx: CallContext, turn: int) -> tuple[str, str, float]:
        name = f"{ctx.file_stem()}_op{turn:02d}"
        resp = agi.record_file(f"{self.s.recordings_dir}/{name}", "wav", "#",
                               self.s.max_utterance_sec * 1000, self.s.silence_sec)
        audio = f"{self.s.recordings_dir}/{name}.wav"
        if (resp.endpos or 0) / SAMPLE_RATE < self.s.min_speech_sec:
            return "", audio, 0.0
        t0 = self.clock()
        try:
            text = self.voice.transcribe_file(f"{name}.wav", ctx.call_id)
        except ServiceError as exc:
            self._error(ctx, "stt", exc)
            text = ""
        return text, audio, self.clock() - t0

    def _utterance(self, ctx: CallContext, turn: int, role: str, text: str,
                   audio: str | None, latency: dict) -> None:
        item = {"turn": turn, "role": role, "text": text, "audio": audio}
        self.registry.append_turn(ctx.call_id, item)
        self.events.emit("call.utterance", **ctx.ids(), **item, latency=latency)

    def _error(self, ctx: CallContext, stage: str, exc: Exception) -> None:
        log.error("call_id=%s stage=%s: %s", ctx.call_id, stage, exc)
        self.events.emit("call.error", **ctx.ids(), stage=stage, error=str(exc))

    def _finish(self, ctx: CallContext, reason: str, started: float) -> None:
        recording_url = f"{self.s.recordings_base_url}/{ctx.file_stem()}.wav"
        call = self.registry.update(ctx.call_id, status="ended", reason=reason,
                                    ended_at=time.time(), recording_url=recording_url)
        self.events.emit("call.ended", **ctx.ids(), reason=reason,
                         duration_sec=round(self.clock() - started, 1),
                         recording_url=recording_url,
                         transcript=list(call.transcript) if call else [])
