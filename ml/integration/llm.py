"""Локальная LLM стенда (Ollama, модель LLM_MODEL) для методов ML API, которым нужен язык:
проверка грамотности текста обучающегося и рекомендации по его ошибкам.

Ответ модели — JSON (format=json у Ollama). Модель недоступна или ответила не по формату —
LLMUnavailable: маршрут отвечает 501, backend выполняет метод своими правилами.
"""

import json
import os
import re
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "qwen3:4b-instruct")
TIMEOUT_SEC = float(os.environ.get("LLM_TIMEOUT_SEC", "20")) * 3   # не реплика в трубке — можно дольше

GRAMMAR_PROMPT = (
    "Ты корректор служебных текстов диспетчерской службы 112 Москвы. Найди в тексте орфографические, "
    "грамматические и пунктуационные ошибки, а также искажённые названия улиц. Разговорные сокращения "
    "служб (СМП, ДДС, МЧС) и номера домов ошибками не считай. Ответь JSON-объектом "
    '{"errors": [{"fragment": "как в тексте", "correction": "как правильно", "reason": "кратко"}]}. '
    'Если ошибок нет — {"errors": []}. /no_think'
)

ADVICE_PROMPT = (
    "Ты преподаватель, который готовит операторов системы-112 и диспетчеров ДДС Москвы. По статистике "
    "ошибок обучающегося дай до трёх конкретных рекомендаций: что тренировать и как. Опирайся на "
    "регламент: приём вызова, адрес с номером дома, классификация по ЕКП, статус «Принята» или "
    "«Не принята» за 30 секунд, комментарии к отказу. Ответь JSON-объектом "
    '{"recommendations": [{"title": "до 60 символов", "text": "1–2 предложения"}]}. /no_think'
)


class LLMUnavailable(Exception):
    pass


def chat_json(system: str, user: str) -> dict:
    body = json.dumps({"model": MODEL, "stream": False, "think": False, "format": "json",
                       "options": {"temperature": 0.2, "num_predict": 600},
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            content = json.loads(resp.read().decode("utf-8"))["message"]["content"]
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        data = json.loads(content)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        raise LLMUnavailable(f"LLM {MODEL}: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMUnavailable("LLM ответила не объектом JSON")
    return data


def check_grammar(text: str) -> dict:
    """Ошибки в формате backend (backend/app/integrations/ml_client.py, _grammar_check)."""
    text = (text or "").strip()
    if not text:
        return {"model": MODEL, "score": 100.0, "errors": []}
    found = chat_json(GRAMMAR_PROMPT, text[:4000]).get("errors") or []
    errors = []
    for item in found[:20]:
        if not isinstance(item, dict):
            continue
        fragment, correction = str(item.get("fragment") or "").strip(), str(item.get("correction") or "").strip()
        if not fragment or fragment == correction or fragment not in text:
            continue   # модель выдумала фрагмент, которого нет в тексте, — не штрафуем
        errors.append({"category": "grammar", "severity": "minor", "code": "llm_grammar",
                       "message": str(item.get("reason") or "Ошибка в написании")[:300],
                       "field_code": None, "expected": correction, "actual": fragment, "penalty": 2.0})
    return {"model": MODEL, "score": max(0.0, 100.0 - 8.0 * len(errors)), "errors": errors}


def recommendations(payload: dict) -> dict:
    stats = {k: payload.get(k) for k in ("top_errors", "avg_score", "attempts", "role", "student_name") if k in payload}
    items = chat_json(ADVICE_PROMPT, json.dumps(stats, ensure_ascii=False)[:4000]).get("recommendations") or []
    buckets = payload.get("top_errors") or []
    result = []
    for i, item in enumerate(items[:3]):
        if isinstance(item, dict) and item.get("title") and item.get("text"):
            result.append({"title": str(item["title"])[:120], "text": str(item["text"])[:600],
                           "priority": 1 if i == 0 else 2, "based_on": buckets[i] if i < len(buckets) else None})
    if not result:
        raise LLMUnavailable("LLM не дала рекомендаций")
    return {"model": MODEL, "recommendations": result}
