"""Эталонная реализация ML-контракта POST /dialogue/turn (telephony/API.md §3).

Два движка:
  * rules — предсказуемые правила по типу звонка (работает без модели);
  * llm   — любая OpenAI-совместимая LLM (Ollama, vLLM, LM Studio или внешний API):
            адрес и модель — LLM_API_URL / LLM_MODEL. Если LLM недоступна или
            ответила мусором — ответ по правилам (звонок не должен срываться).

Это заглушка роли ML: настоящий ML-сервис реализует тот же контракт, а
телефония переключается на него сменой ML_API_URL.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("mocks.ml")

END_MARK = "[КОНЕЦ]"
ADDRESS_STOPWORDS = {"москва", "город", "улица", "проезд", "проспект", "шоссе", "бульвар", "переулок",
                     "площадь", "набережная", "корпус", "строение", "квартира", "подъезд", "район"}


# ------------------------------------------------------------ общее ---

def _matches(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


def _said(history: list[dict], role: str) -> list[str]:
    return [h.get("text") or "" for h in history if h.get("role") == role]


def _trailing_silence(history: list[dict]) -> int:
    """Сколько последних реплик оператора подряд пустые (молчание / не распознано)."""
    n = 0
    for text in reversed(_said(history, "operator")):
        if text.strip():
            break
        n += 1
    return n


def address_stems(address: str | None) -> list[str]:
    """«Москва, ул. Ясный проезд, 10» -> ['ясн']: основы значимых слов адреса.

    Основа = слово без двух последних букв (не короче 3): ловит падежи
    («Ясный» / «Ясном», «Ленина» / «Ленину») без морфологического словаря.
    """
    words = re.findall(r"[а-яёa-z]{4,}", (address or "").lower())
    return [w[:max(3, len(w) - 2)] for w in words if w not in ADDRESS_STOPWORDS]


def address_mentioned(text: str, card: dict | None) -> bool:
    stems = address_stems((card or {}).get("address"))
    return not stems or any(s in text for s in stems)


def _surname(persona: dict) -> str:
    return (persona.get("name") or "").split(" ")[0]


def _female(persona: dict) -> bool:
    return persona.get("gender") == "female"


def _reply(text: str, end: bool = False) -> dict:
    return {"reply_text": text, "end_call": end}


# ------------------------------------------------------- incident_112 ---

def dialogue_turn(scenario: dict, turn: int, history: list[dict], operator_text: str | None) -> dict:
    """Заявитель звонит в 112: факты сценария по ключевым словам вопроса оператора."""
    if turn == 0 or operator_text is None:
        return _reply(scenario["opening"])

    caller_said = _said(history, "caller")
    operator_said = _said(history, "operator")
    facts = scenario.get("facts", [])
    given = {f["id"] for f in facts if any(f["reply"] in said for said in caller_said)}

    if turn >= scenario.get("max_turns", 10) - 1:
        return _reply(scenario.get("timeout_reply", "Всё, до свидания."), True)

    text = operator_text.strip().lower()
    if not text:
        # оператор молчит: после двух подряд «пустых» ответов абонент кладёт трубку
        if len(operator_said) >= 2 and not operator_said[-2].strip():
            return _reply(scenario.get("silence_hangup", "Вас не слышно."), True)
        return _reply(scenario.get("silence", "Алло?"))

    parts = []
    for fact in facts:
        if _matches(text, fact["keywords"]):
            parts.append(fact["reply"])
            given.add(fact["id"])

    end_call = False
    if _matches(text, scenario.get("closing_keywords", [])) and turn >= scenario.get("min_turns_before_closing", 1):
        missing = [f for f in facts if f["id"] in scenario.get("required_before_closing", []) and f["id"] not in given]
        if missing:
            parts.append("Подождите! " + missing[0]["reply"])
        else:
            parts.append(scenario.get("closing", "Спасибо."))
            end_call = True

    if not parts:
        fallbacks = scenario.get("fallbacks") or ["Повторите, пожалуйста."]
        used = sum(1 for said in caller_said if said in fallbacks)
        parts.append(fallbacks[used % len(fallbacks)])
    return _reply(" ".join(parts), end_call)


# ----------------------------------------------------------- dispatch ---

ASK_ADDRESS = "Назовите, пожалуйста, точный адрес происшествия."


def dispatch_turn(persona: dict, card: dict | None, turn: int, history: list[dict],
                  operator_text: str | None) -> dict:
    """Диспетчер ДДС звонит в службу: «слушаю» -> доклад -> «информация принята».

    Если в докладе нет адреса из карточки — собеседник один раз переспрашивает
    (обучающий момент: адрес критичен).
    """
    if turn == 0 or operator_text is None:
        return _reply(f"{persona.get('position') or 'Дежурный'} {_surname(persona)}, слушаю вас.".replace("  ", " "))
    text = operator_text.strip().lower()
    if not text:
        if _trailing_silence(history) >= 2:
            return _reply("Вас не слышно. Перезвоните, пожалуйста.", True)
        return _reply("Алло, слушаю вас, говорите.")
    asked = ASK_ADDRESS in _said(history, "caller")
    if not asked and not address_mentioned(text, card) and turn < 4:
        return _reply(ASK_ADDRESS)
    accept = persona.get("accept") or ("Я вас поняла, информация принята." if _female(persona)
                                       else "Я вас понял, информация принята.")
    return _reply(accept, True)


# ------------------------------------------------------------- report ---

REPORT_TEXT = {
    "arrival": "Прибыли на место{addr}. Приступаем к работам.",
    "in_progress": "Ведём работы{addr}, обстановка под контролем, помощь не требуется.",
    "completed": "Работы{addr} завершены, возвращаемся в подразделение.",
    "refused": "Выполнение работ{addr} невозможно, требуется другая служба.",
}


def report_text(persona: dict, card: dict | None, report: dict | None) -> str:
    report = report or {}
    if report.get("text"):
        return report["text"]
    address = (card or {}).get("address")
    template = REPORT_TEXT.get(report.get("status") or "arrival", REPORT_TEXT["arrival"])
    return template.format(addr=f" по адресу {address}" if address else "")


def report_turn(persona: dict, card: dict | None, report: dict | None, turn: int,
                history: list[dict], operator_text: str | None) -> dict:
    """Старший группы звонит в ДДС с докладом; диспетчер должен подтвердить и отразить статус."""
    body = report_text(persona, card, report)
    if turn == 0 or operator_text is None:
        return _reply(f"Дежурно-диспетчерская служба? Говорит {persona.get('position') or 'старший группы'} "
                      f"{_surname(persona)}. {body} Как приняли?")
    if operator_text.strip():
        return _reply("Понял вас, конец связи.", True)
    if _trailing_silence(history) >= 2:
        return _reply("Связь плохая, доложу повторно.", True)
    return _reply(f"ДДС, как слышите? Повторяю: {body}")


# ---------------------------------------------------------- applicant ---

def applicant_turn(persona: dict, card: dict | None, turn: int, history: list[dict],
                   operator_text: str | None) -> dict:
    """Диспетчер ДДС перезванивает заявителю («Вы звонили в 112 по поводу…»)."""
    card = card or {}
    if turn == 0 or operator_text is None:
        return _reply("Алло?")
    text = operator_text.strip().lower()
    caller_said = _said(history, "caller")
    if not text:
        if _trailing_silence(history) >= 2:
            return _reply("Ничего не слышно, до свидания.", True)
        return _reply("Алло, говорите!")
    story = card.get("description") or card.get("title") or "у нас тут происшествие"
    told = any(story in said for said in caller_said)
    if not told:
        if not _matches(text, ["112", "сто двенадцать", "звонил", "обращал", "вызов"]) and turn == 1:
            return _reply("Кто это? По какому вопросу?")
        verb = "звонила" if _female(persona) else "звонил"
        return _reply(f"Да, {verb}. {story}. Когда приедут?")
    return _reply("Хорошо, спасибо, ждём.", True)


# ------------------------------------------------------------- rules ---

class DialogueError(Exception):
    """Запрос нельзя обработать (например, нет сценария) -> HTTP 404."""


def rules_turn(req: dict, scenarios: dict[str, dict]) -> dict:
    call_type = req.get("call_type") or "incident_112"
    persona = req.get("persona") or {}
    context = req.get("context") or {}
    card = context.get("card")
    turn = int(req.get("turn", 0))
    history = req.get("history") or []
    operator_text = req.get("operator_text")
    if call_type == "dispatch":
        return dispatch_turn(persona, card, turn, history, operator_text)
    if call_type == "report":
        return report_turn(persona, card, context.get("report"), turn, history, operator_text)
    if call_type == "applicant":
        return applicant_turn(persona, card, turn, history, operator_text)
    scenario = scenarios.get(str(req.get("scenario_id")))
    if scenario is None:
        raise DialogueError(f"сценарий {req.get('scenario_id')!r} не найден")
    return dialogue_turn(scenario, turn, history, operator_text)


# --------------------------------------------------------------- LLM ---

@dataclass(frozen=True)
class LLMConfig:
    api_url: str        # базовый URL OpenAI-совместимого API, например http://host.docker.internal:11434/v1
    model: str
    api_key: str = ""
    timeout_sec: float = 20.0
    max_turns: int = 8

    @classmethod
    def from_env(cls) -> "LLMConfig | None":
        if os.environ.get("DIALOGUE_ENGINE", "rules").strip().lower() != "llm":
            return None
        url = os.environ.get("LLM_API_URL", "").strip().rstrip("/")
        if not url:
            log.warning("DIALOGUE_ENGINE=llm, но LLM_API_URL не задан — работают правила")
            return None
        return cls(url, os.environ.get("LLM_MODEL", "qwen2.5:7b"), os.environ.get("LLM_API_KEY", ""),
                   float(os.environ.get("LLM_TIMEOUT_SEC", "20")))


ROLE_PROMPTS = {
    "dispatch": ("Ты — {position} {name}, служба «{service}». Тебе по телефону звонит диспетчер ДДС "
                 "и докладывает о происшествии. Первой репликой представься и скажи «слушаю». "
                 "Выслушай доклад. Если диспетчер не назвал адрес или суть — коротко переспроси. "
                 "Когда информации достаточно, подтверди: «информация принята» и скажи, что предпримет служба."),
    "report": ("Ты — {position} {name}, служба «{service}», старший группы на месте происшествия. "
               "Ты звонишь в ДДС доложить обстановку: {report}. Первой репликой представься и доложи. "
               "Дождись подтверждения диспетчера и закончи разговор."),
    "applicant": ("Ты — {name}, заявитель, который звонил в 112. Тебе перезванивает диспетчер ДДС. "
                  "Первой репликой просто скажи «Алло?». Отвечай на вопросы по сути происшествия, "
                  "волнуйся, но говори по делу."),
    "incident_112": ("Ты — заявитель, звонишь в 112. Описание происшествия из сценария: {scenario}. "
                     "Первой репликой сообщи о беде. Отвечай на вопросы оператора только фактами сценария."),
}

RULES_PROMPT = ("Говори как живой человек по телефону: 1–2 коротких предложения, без списков, "
                "без эмодзи и разметки, по-русски. Числа пиши словами. Не выдумывай адрес — "
                "используй только данные ниже. Когда разговор закончен, добавь в конце " + END_MARK + ".")


def build_messages(req: dict, scenarios: dict[str, dict]) -> list[dict]:
    call_type = req.get("call_type") or "incident_112"
    persona = req.get("persona") or {}
    context = req.get("context") or {}
    card = context.get("card") or {}
    scenario = scenarios.get(str(req.get("scenario_id"))) or {}
    role = ROLE_PROMPTS.get(call_type, ROLE_PROMPTS["incident_112"]).format(
        position=persona.get("position") or "", name=persona.get("name") or "", service=persona.get("service") or "",
        report=report_text(persona, card, context.get("report")),
        scenario=json.dumps({k: scenario.get(k) for k in ("title", "facts")}, ensure_ascii=False))
    facts = f"Карточка происшествия: {json.dumps(card, ensure_ascii=False)}" if card else "Карточки нет."
    messages = [{"role": "system", "content": f"{role}\n{RULES_PROMPT}\n{facts}"}]
    for h in req.get("history") or []:
        # собеседник (caller) — это модель, оператор/диспетчер — пользователь
        messages.append({"role": "assistant" if h.get("role") == "caller" else "user",
                         "content": h.get("text") or "(молчание)"})
    if not req.get("history"):
        messages.append({"role": "user", "content": "(соединение установлено)"})
    return messages


def llm_turn(req: dict, scenarios: dict[str, dict], cfg: LLMConfig) -> dict:
    body = json.dumps({"model": cfg.model, "messages": build_messages(req, scenarios),
                       "temperature": 0.5, "max_tokens": 160}, ensure_ascii=False).encode("utf-8")
    http_req = urllib.request.Request(f"{cfg.api_url}/chat/completions", data=body, method="POST")
    http_req.add_header("Content-Type", "application/json")
    if cfg.api_key:
        http_req.add_header("Authorization", f"Bearer {cfg.api_key}")
    with urllib.request.urlopen(http_req, timeout=cfg.timeout_sec) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = (data["choices"][0]["message"]["content"] or "").strip()
    end = END_MARK in text or int(req.get("turn", 0)) >= cfg.max_turns - 1
    text = re.sub(r"\s+", " ", text.replace(END_MARK, "").replace("*", "")).strip()
    if not text:
        raise ValueError("LLM вернула пустой ответ")
    return {"reply_text": text[:600], "end_call": end}


def next_turn(req: dict, scenarios: dict[str, dict], llm: LLMConfig | None) -> dict:
    if llm is not None:
        try:
            return {**llm_turn(req, scenarios, llm), "engine": f"llm:{llm.model}"}
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
            log.warning("LLM недоступна (%s) — ответ по правилам", exc)
            return {**rules_turn(req, scenarios), "engine": "rules-fallback"}
    return {**rules_turn(req, scenarios), "engine": "rules"}
