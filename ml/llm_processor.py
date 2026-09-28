import json
import time
import urllib.error
import urllib.request
from typing import Any
import os

OLLAMA_HOST = os.environ.get(
    "OLLAMA_URL",
    "http://127.0.0.1:11434",
).rstrip("/")

OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"

MODEL_NAME = "qwen3:4b"

FIRST_REQUEST_TIMEOUT = 240

REGULAR_REQUEST_TIMEOUT = 120

WARMUP_TIMEOUT = 300


SYSTEM_PROMPT = """
Ты — модуль извлечения фактов для учебного симулятора системы 112.

Твоя задача — анализировать сообщение абонента и извлекать ТОЛЬКО информацию,
которая прямо содержится в сообщении.

Правила:
1. Не придумывай отсутствующие сведения.
2. Не делай предположений.
3. Не определяй официальный код инцидента.
4. Не выбирай категорию из классификатора.
5. Не назначай службу самостоятельно.
6. Если информация неизвестна или не сказана, не добавляй её в facts.
7. Отдельно указывай, какие важные сведения отсутствуют.
8. Отвечай ТОЛЬКО валидным JSON.
9. Не добавляй Markdown, пояснения или текст до/после JSON.

Формат ответа:

{
  "facts": [
    "факт 1",
    "факт 2"
  ],
  "unknowns": [
    "неизвестный важный факт 1"
  ],
  "summary": "краткое описание только известных фактов"
}

/no_think
"""


def check_ollama(timeout: int = 5) -> list[str]:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise RuntimeError(
            "Ollama не отвечает на " + OLLAMA_TAGS_URL + ".\n"
            "Проверьте по шагам:\n"
            "  1) Установлена ли Ollama? (https://ollama.com)\n"
            "  2) Запущен ли сервер командой `ollama serve`?\n"
            "  3) Слушает ли он 127.0.0.1:11434? (ollama list)"
        ) from error

    return [m.get("name", "") for m in data.get("models", [])]


def ensure_model_present(models: list[str]) -> None:

    base = MODEL_NAME.split(":")[0].lower()
    if not any(base in name.lower() for name in models):
        raise RuntimeError(
            f"Модель '{MODEL_NAME}' не найдена локально.\n"
            f"Скачайте командой:  ollama pull {MODEL_NAME}\n"
            f"Либо поменяйте MODEL_NAME на что-то из уже скачанных: {models}"
        )



def warmup_model(timeout: int = WARMUP_TIMEOUT) -> None:

    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "think": False,
        "options": {
            "num_predict": 1,
            "temperature": 0,
        },
        "keep_alive": "15m",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
    except TimeoutError as error:
        raise RuntimeError(
            f"Прогрев не завершился за {timeout} секунд. "
            "Модель слишком тяжёлая для этой машины. "
            f"Попробуйте модель полегче: `ollama pull qwen2.5:3b` "
            f"и установите MODEL_NAME = \"qwen2.5:3b\"."
        ) from error



def _extract_json(text: str) -> dict[str, Any]:

    text = text.strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    raise ValueError(
        "Ollama вернула ответ, который не удалось разобрать как JSON. "
        f"Первые 300 символов: {text[:300]!r}"
    )



def analyze_text(
    text: str,
    *,
    timeout: int = REGULAR_REQUEST_TIMEOUT,
    retries: int = 2,
) -> dict[str, Any]:

    if not isinstance(text, str):
        raise TypeError("text должен быть строкой.")

    text = text.strip()
    if not text:
        raise ValueError("Нельзя анализировать пустой текст.")

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 400,
            "num_ctx": 2048,
        },
        "keep_alive": "15m",
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_error: Exception | None = None

    for attempt in range(retries + 1):
        request = urllib.request.Request(
            OLLAMA_CHAT_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_response = response.read().decode("utf-8")
            break  # успех — выходим из retry-цикла

        except TimeoutError as error:
            last_error = error
            if attempt < retries:
                wait = 3 * (attempt + 1)
                print(f"[llm_processor] таймаут, повтор через {wait} сек...")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"Ollama не ответила за {timeout} секунд даже после "
                f"{retries + 1} попыток.\n"
                f"Что можно сделать:\n"
                f"  1) Проверить, что модель загружена (ollama list).\n"
                f"  2) Запустить прогрев: warmup_model().\n"
                f"  3) Увеличить timeout до 300 секунд.\n"
                f"  4) Сменить модель на qwen2.5:3b или llama3.2:3b:\n"
                f"     ollama pull qwen2.5:3b\n"
                f"     MODEL_NAME = \"qwen2.5:3b\""
            ) from error

        except urllib.error.URLError as error:
            raise RuntimeError(
                "Не удалось подключиться к Ollama. "
                "Проверь, что сервер запущен (`ollama serve`)."
            ) from error

    else:

        raise RuntimeError("Не удалось получить ответ от Ollama.") from last_error

    try:
        ollama_response = json.loads(raw_response)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Ollama вернула некорректный JSON-ответ."
        ) from error

    message = ollama_response.get("message", {})
    content = message.get("content", "")

    if not content:
        raise RuntimeError(
            "Ollama не вернула содержимое ответа модели. "
            f"Полный ответ: {ollama_response}"
        )

    result = _extract_json(content)

    facts = result.get("facts", [])
    unknowns = result.get("unknowns", [])
    summary = result.get("summary", "")

    if not isinstance(facts, list):
        facts = []
    if not isinstance(unknowns, list):
        unknowns = []
    if not isinstance(summary, str):
        summary = ""

    facts = [str(item).strip() for item in facts if str(item).strip()]
    unknowns = [str(item).strip() for item in unknowns if str(item).strip()]

    return {
        "facts": facts,
        "unknowns": unknowns,
        "summary": summary.strip(),
    }



if __name__ == "__main__":
    print("Проверка доступности Ollama...")
    models = check_ollama()
    print(f"Доступные модели: {models}")
    ensure_model_present(models)

    print(f"Прогрев модели '{MODEL_NAME}' (первый раз может занять 1–3 минуты)...")
    warmup_model()
    print("Модель готова.")

    test_text = (
        "На улице горит мусорный контейнер, "
        "рядом никого не видно."
    )

    print("\nОтправляем сообщение в Ollama...")
    t0 = time.time()
    result = analyze_text(test_text)
    elapsed = time.time() - t0

    print(f"Ответ получен за {elapsed:.1f} сек.")
    print(json.dumps(result, ensure_ascii=False, indent=2))