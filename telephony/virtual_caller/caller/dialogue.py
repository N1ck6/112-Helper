"""Голосовой цикл учебного звонка.

    ML: реплика собеседника -> TTS (голос по полу собеседника) -> STREAM FILE
    -> RECORD FILE (до паузы) -> STT -> ML: следующая реплика ...
    пока ML не вернёт end_call или не сработает MAX_TURNS / MAX_CALL_SEC.

Типы звонков (directory.py): dispatch — диспетчер ДДС звонит в службу,
report — старший группы звонит в ДДС с докладом, applicant — диспетчер
перезванивает заявителю, incident_112 — заявитель звонит оператору 112.
Что говорит собеседник, решает ML-сервис по истории, карточке и persona —
здесь только телефония и порядок шагов.
Отказы внешних сервисов не роняют звонок: нет TTS — FALLBACK_SOUND,
нет STT — «оператор молчал», нет ML — конец звонка.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from .agi import AGISession, ChannelHungUp
from .calls import Call, CallRegistry, TraineeContexts
from .clients import DialogueClient, ServiceError, VoiceClient
from .config import Settings
from .directory import APPLICANT, DISPATCH, INCIDENT_112, REPORT, Directory, voice_for
from .events import EventSink

log = logging.getLogger("virtual_caller.dialogue")

SAMPLE_RATE = 8000  # формат "wav" в Asterisk: PCM16 mono 8 кГц
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]")
UNKNOWN_NUMBER_TEXT = "Набранный номер не обслуживается."
# Собеседник по умолчанию для входящего вызова 112 (заявитель из сценария ML)
APPLICANT_112 = {"id": "applicant_112", "service": "Заявитель", "name": None,
                 "position": "заявитель", "gender": "female"}


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
    call_type: str = INCIDENT_112
    trainee: str | None = None
    persona: dict | None = None
    card: dict | None = None
    report: dict | None = None
    extra: dict = field(default_factory=dict)

    def ids(self) -> dict:
        return {"call_id": self.call_id, "session_id": self.session_id, "scenario_id": self.scenario_id,
                "call_type": self.call_type, "trainee": self.trainee}

    def file_stem(self) -> str:
        return SAFE_NAME_RE.sub("_", self.call_id)

    def ml_context(self) -> dict:
        return {"card": self.card, "report": self.report, "trainee": self.trainee}


def persona_brief(persona: dict | None) -> dict | None:
    if not persona:
        return None
    return {k: persona.get(k) for k in ("id", "number", "service", "name", "position", "gender")}


class DialogueRunner:
    def __init__(self, settings: Settings, voice: VoiceClient, dialogue: DialogueClient,
                 events: EventSink, registry: CallRegistry, directory: Directory | None = None,
                 contexts: TraineeContexts | None = None, clock=time.monotonic):
        self.s = settings
        self.voice = voice
        self.dialogue = dialogue
        self.events = events
        self.registry = registry
        self.directory = directory or Directory([])
        self.contexts = contexts or TraineeContexts()
        self.clock = clock

    # --- вход из FastAGI ------------------------------------------------
    def _var(self, agi: AGISession, name: str) -> str | None:
        try:
            return agi.get_variable(name) or None
        except ChannelHungUp:
            return None

    def handle(self, agi: AGISession) -> str:
        env = agi.read_environment()
        call_id = env.get("agi_uniqueid") or str(uuid.uuid4())
        scenario_id = env.get("agi_network_script") or ""
        channel = env.get("agi_channel")
        known = self.registry.get(call_id)

        if known is not None:  # исходящий звонок из API: всё уже известно
            ctx = CallContext(call_id, known.session_id, known.scenario_id or scenario_id, known.call_type,
                              known.trainee, known.persona, known.card, known.report)
        else:                  # обучающийся набрал номер сам: 7xx, 2XXX, 3000
            ctx = self._inbound_context(agi, call_id, scenario_id, channel)
            self.registry.add(Call(call_id=call_id, session_id=ctx.session_id, scenario_id=ctx.scenario_id,
                                   direction="inbound", trainee=ctx.trainee, call_type=ctx.call_type,
                                   persona=ctx.persona, card=ctx.card, channel=channel))
        call = self.registry.update(call_id, channel=channel, status="in_progress", answered_at=time.time())
        self.events.emit("call.started", **ctx.ids(), direction=call.direction, channel=channel,
                         caller_id=env.get("agi_callerid"), persona=persona_brief(ctx.persona),
                         card_id=(ctx.card or {}).get("id"))
        if ctx.call_type == DISPATCH and ctx.persona is None:
            return self._unknown_number(agi, ctx)
        return self.run(agi, ctx)

    def _inbound_context(self, agi: AGISession, call_id: str, scenario_id: str, channel: str | None) -> CallContext:
        trainee = self._var(agi, "TRAINEE") or trainee_from_channel(channel)
        workplace = self.contexts.get(trainee) or {}
        card = workplace.get("card")
        session_id = self._var(agi, "SESSION_ID") or workplace.get("session_id") or str(uuid.uuid4())
        call_type = self._var(agi, "CALL_TYPE") or INCIDENT_112
        persona = None
        if call_type in (DISPATCH, REPORT):
            contact = self.directory.resolve(self._var(agi, "CONTACT_ID"))
            persona = Directory.persona(contact, call_type) if contact else None
        elif call_type == APPLICANT:
            persona = Directory.applicant(card)
        else:
            persona = dict(APPLICANT_112)
        return CallContext(call_id, session_id, scenario_id, call_type, trainee, persona, card)

    def _unknown_number(self, agi: AGISession, ctx: CallContext) -> str:
        started = self.clock()
        try:
            self._say(agi, ctx, 0, UNKNOWN_NUMBER_TEXT, record=False)
        except ChannelHungUp:
            pass
        finally:
            if not agi.hungup:
                agi.hangup()
            self._finish(ctx, "unknown_number", started)
        return "unknown_number"

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
                        turn=turn, history=list(history), operator_text=operator_text,
                        call_type=ctx.call_type, persona=ctx.persona, context=ctx.ml_context())
                except ServiceError as exc:
                    self._error(ctx, "ml", exc)
                    agi.stream_file(self.s.fallback_sound)
                    reason = "ml_error"
                    break
                ml_sec = self.clock() - t0

                if reply.reply_text:
                    history.append({"role": "caller", "text": reply.reply_text})
                    self._say(agi, ctx, turn, reply.reply_text, latency={"ml_sec": round(ml_sec, 3)})
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
    def _say(self, agi: AGISession, ctx: CallContext, turn: int, text: str,
             latency: dict | None = None, record: bool = True) -> None:
        """Озвучить реплику собеседника голосом по его полу и проиграть в канал."""
        t0 = self.clock()
        try:
            sound = self.voice.synthesize_to_file(text, ctx.call_id, voice_for(ctx.persona))
            audio = f"{sound}.wav"
        except ServiceError as exc:
            self._error(ctx, "tts", exc)
            sound, audio = self.s.fallback_sound, None
        tts_sec = self.clock() - t0
        # событие до проигрывания: frontend показывает реплику, пока она звучит
        if record:
            self._utterance(ctx, turn, "caller", text, audio, {**(latency or {}), "tts_sec": round(tts_sec, 3)})
        agi.stream_file(sound)

    def _listen(self, agi: AGISession, ctx: CallContext, turn: int) -> tuple[str, str, float]:
        name = f"{ctx.file_stem()}_op{turn:02d}"
        audio = f"{self.s.recordings_dir}/{name}.wav"
        # Тишина в RECORD FILE считается и с начала записи: оператор, который
        # задумался на SILENCE_SEC, получил бы пустую реплику. Поэтому пустую
        # первую запись слушаем ещё раз (файл перезаписывается) — собеседник
        # переспросит только после 2 × SILENCE_SEC молчания.
        for _ in range(2):
            resp = agi.record_file(f"{self.s.recordings_dir}/{name}", "wav", "#",
                                   self.s.max_utterance_sec * 1000, self.s.silence_sec)
            if (resp.endpos or 0) / SAMPLE_RATE >= self.s.min_speech_sec:
                break
        else:
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
                         recording_url=recording_url, persona=persona_brief(ctx.persona),
                         card_id=(ctx.card or {}).get("id"),
                         transcript=list(call.transcript) if call else [])
