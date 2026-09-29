"""Контракт ML API для Backend (backend/docs/INTEGRATION.md §1, ТЗ_итоговое §4 «ML API для Backend»).

Backend вызывает ML по путям /api/v1/...; здесь они переводятся на функции ML-сервиса:

  POST /api/v1/generate/scenarios  -> scenario_generator.generate_scenario по классификатору;
  POST /api/v1/evaluate/attempt    -> evaluator.evaluate_answer: свободный текстовый ответ по сценарию ML
                                      (карточку АРМ-112 с полями оценивает backend — 501).

Чего в ML нет (коррекция по комментарию, аналитика, индексация материалов, оценка статусов ДДС
и полей карточки) — ответ 501: backend в этом случае считает по своим правилам (HybridMLClient).
"""

import random
from typing import Any, Callable, Dict, List

from evaluator import evaluate_answer
from scenario_generator import generate_scenario

MODEL_NAME = "system-112-ml"
MODEL_VERSION = "2.0"

# Уровни сложности backend -> генератора ML
DIFFICULTY_MAP = {"basic": "easy", "easy": "easy", "medium": "medium", "hard": "hard"}
# Регламент приёма вызова в кодах действий backend (app/models/enums.py ActionType)
EXPECTED_ACTIONS = ["call_accepted", "field_filled", "classified", "card_submitted"]
# Поля карточки, в которых обучающийся пишет свободный текст
TEXT_FIELDS = ("description", "operator_message", "note")


class NotImplementedByML(Exception):
    """ML не умеет этот запрос — backend посчитает сам по правилам."""


def _incident_numbers(payload: Dict[str, Any], classify: Callable[[str], Dict[str, Any]]) -> List[str | None]:
    """Типы происшествий классификатора под запрос преподавателя (категория, подсказка)."""
    query = " ".join(str(payload.get(k) or "") for k in ("prompt", "category_name")).strip()
    if not query:
        return [None]  # генератор выберет случайный тип
    result = classify(query)
    numbers = [result.get("incident_number")] + [a.get("incident_number") for a in result.get("alternatives", [])]
    numbers = [n for n in numbers if n]
    return numbers or [None]


# Адреса учебных происшествий: реальные улицы Москвы с их округом и районом
ADDRESSES = [
    ("ЮЗАО", "Академический", "улица Профсоюзная", "12"),
    ("ЦАО", "Тверской", "улица Тверская", "6"),
    ("СВАО", "Останкинский", "улица Академика Королёва", "3"),
    ("ЗАО", "Раменки", "Мичуринский проспект", "6"),
    ("ВАО", "Измайлово", "Измайловский бульвар", "20"),
    ("САО", "Тимирязевский", "Дмитровское шоссе", "9"),
    ("ЮВАО", "Рязанский", "Рязанский проспект", "64"),
    ("СЗАО", "Строгино", "улица Кулакова", "20"),
    ("ЦАО", "Хамовники", "Комсомольский проспект", "28"),
    ("САО", "Аэропорт", "Ленинградский проспект", "64"),
]
APPLICANTS = [("Иванова Мария Сергеевна", "female"), ("Петров Сергей Николаевич", "male"),
              ("Соколова Анна Викторовна", "female"), ("Кузнецов Андрей Павлович", "male"),
              ("Смирнова Елена Игоревна", "female"), ("Волков Дмитрий Олегович", "male"),
              ("Морозова Ольга Андреевна", "female"), ("Новиков Игорь Васильевич", "male")]


def _story(incident_type: str, address: str, victims: int) -> str:
    """Суть «со слов заявителя»: пишет локальная LLM, без неё — по шаблону."""
    try:
        from . import llm
        data = llm.chat_json(
            "Ты составляешь учебную карточку вызова 112 Москвы. Напиши, что говорит заявитель оператору "
            "про происшествие именно указанного типа: 1–2 коротких предложения от первого лица, "
            "конкретно (что видит, где именно в доме или на улице), без адреса, имён и слова «заявитель». "
            'Ответь JSON {"description": "..."}. /no_think',
            f"Тип происшествия: «{incident_type}». Пострадавших: {victims}.")
        text = str(data.get("description") or "").strip()
        if 10 <= len(text) <= 400:
            return text
    except Exception:  # noqa: BLE001 — нет LLM: шаблон
        pass
    tail = f", есть пострадавшие ({victims})" if victims else ", пострадавших нет"
    return f"У нас {incident_type}{tail}."


# Основная служба классификатора -> код службы в списке оповещения АРМ-112 (backend/app/core/arm112.py)
SERVICE_CODES = {"MCHS": "101", "POLICE": "102", "AMBULANCE": "103", "MOSGAZ": "104"}


def _services(classification: Dict[str, Any], victims: int) -> List[str]:
    """Службы, которые оператор должен выбрать: основная по классификатору, при пострадавших — 103."""
    codes: List[str] = []
    main = SERVICE_CODES.get(str(classification.get("main_service") or "").upper())
    if main:
        codes.append(main)
    if victims and "103" not in codes:
        codes.append("103")
    return codes


def _expected_fields(classification: Dict[str, Any], rnd: random.Random, difficulty: str) -> Dict[str, Any]:
    """Эталон карточки АРМ-112 (коды полей — backend/app/core/arm112.py)."""
    incident_type = classification.get("incident_type") or "происшествие"
    okrug, area, street, house = rnd.choice(ADDRESSES)
    name, _ = rnd.choice(APPLICANTS)
    victims = rnd.randint(1, 3) if ("пострадав" in incident_type.lower() or difficulty == "hard") else 0
    address = f"г. Москва, {street}, д. {house}"
    return {
        "aon_phone": f"+7 (9{rnd.randint(10, 99)}) {rnd.randint(100, 999)}-{rnd.randint(10, 99)}-{rnd.randint(10, 99)}",
        # статус заявителя не в эталоне: заявитель его не называет, оператор определяет сам
        "applicant_name": name,
        "address_region": "г. Москва",
        "address_district": okrug,
        "address_area": area,
        "address_street": street,
        "address_house": house,
        "incident_class": incident_type,
        "has_victims": bool(victims),
        "victims_count": victims,
        "description": _story(incident_type, address, victims),
        "notification_services": _services(classification, victims),
    }


def _to_backend_scenario(scenario: Dict[str, Any], payload: Dict[str, Any], rnd: random.Random) -> Dict[str, Any]:
    classification = scenario.get("classification") or {}
    caller = scenario.get("caller") or {}
    questions = scenario.get("questions") or []
    actions = scenario.get("expected_actions") or []
    expected = _expected_fields(classification, rnd, scenario.get("difficulty") or "medium")
    address = f"{expected['address_street']}, д. {expected['address_house']}"
    return {
        "title": scenario.get("title"),
        "description": expected["description"],
        "category_code": payload.get("category_code"),
        "difficulty": payload.get("difficulty", "basic"),
        "briefing": {
            "caller": {"name": expected["applicant_name"], "phone": expected["aon_phone"],
                       "state": caller.get("emotion")},
            "dialogue": [{"role": "caller", "text": expected["description"]},
                         {"role": "caller", "text": f"Адрес: {address}"}],
            "address": address,
            "signs": [],
            "classification": classification,
            "main_service": classification.get("main_service"),
        },
        "reference": {
            "expected_fields": expected,
            "expected_actions": EXPECTED_ACTIONS,
            "expected_text": {
                "min_length": 20,
                # полный сценарий ML: по нему /evaluate/attempt оценивает ответ обучающегося
                "ml_scenario": scenario,
            },
        },
        # вопрос оператора -> ожидаемое действие (генератор ML строит их парами)
        "questions": [{"text": q, "options": [], "correct": [actions[i]] if i < len(actions) else []}
                      for i, q in enumerate(questions)],
    }


def generate_scenarios(payload: Dict[str, Any], classifier_data: Any,
                       classify: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
    count = max(1, min(int(payload.get("count") or 1), 20))
    difficulty = DIFFICULTY_MAP.get(str(payload.get("difficulty") or "basic").lower(), "medium")
    numbers = _incident_numbers(payload, classify)
    rnd = random.Random(payload.get("seed"))
    scenarios = []
    for i in range(count):
        scenario = generate_scenario(classifier_data=classifier_data, difficulty=difficulty,
                                     incident_number=numbers[i % len(numbers)])
        scenarios.append(_to_backend_scenario(scenario, payload, rnd))
    return {"model": MODEL_NAME, "version": MODEL_VERSION, "scenarios": scenarios}


def _answer_text(payload: Dict[str, Any]) -> str:
    submitted = payload.get("submitted_payload") or {}
    parts = [str(submitted.get(k) or "") for k in TEXT_FIELDS]
    return " ".join(p for p in parts if p.strip()).strip()


def _timing(duration_s: float, norm_s: float) -> tuple[float, list]:
    if norm_s <= 0 or duration_s <= norm_s:
        return 100.0, []
    overtime = (duration_s - norm_s) / norm_s
    return max(0.0, 100.0 - overtime * 60.0), [{
        "category": "timing", "severity": "critical" if overtime > 1 else "major", "code": "norm_exceeded",
        "message": f"Превышен норматив: {duration_s:.1f} с вместо {norm_s:.0f} с",
        "field_code": None, "expected": f"{norm_s:.0f}", "actual": f"{duration_s:.1f}",
        "penalty": 20.0 if overtime > 1 else 10.0}]


def evaluate_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Оценка ответа по критериям сценария ML + тайминг относительно норматива."""
    if payload.get("lesson_mode") == "card_action" or (payload.get("response") or {}).get("statuses"):
        raise NotImplementedByML("оценка статусов ДДС выполняется правилами backend")
    submitted = payload.get("submitted_payload") or {}
    if any(k.startswith("address_") or k == "incident_class" for k in submitted):
        raise NotImplementedByML("карточка АРМ-112: поля, время и регламент сравнивает backend")
    scenario = (payload.get("expected_text") or {}).get("ml_scenario")
    if not isinstance(scenario, dict) or not scenario.get("evaluation_criteria"):
        raise NotImplementedByML("карточка не из сценария ML — оценка по правилам backend")
    text = _answer_text(payload)
    if not text:
        raise NotImplementedByML("нет текста ответа для оценки ML")

    result = evaluate_answer(scenario=scenario, operator_answer=text)
    accuracy = float(result["score"])
    timing, errors = _timing(float(payload.get("duration_seconds") or 0), float(payload.get("norm_seconds") or 0))
    for action in result.get("missed_actions", []):
        errors.append({"category": "procedure", "severity": "major", "code": "ml_action_missed",
                       "message": f"Не выполнено: {action}", "field_code": None,
                       "expected": action, "actual": "", "penalty": 8.0})
    for mistake in result.get("mistakes", []):
        errors.append({"category": "grammar", "severity": "minor", "code": "ml_text_mistake",
                       "message": str(mistake), "field_code": None, "expected": None,
                       "actual": None, "penalty": 3.0})
    grammar = max(0.0, 100.0 - 10.0 * len(result.get("mistakes", [])))
    score = round(0.7 * accuracy + 0.2 * timing + 0.1 * grammar, 2)
    critical = sum(1 for e in errors if e["severity"] == "critical")
    passed = score >= float(payload.get("min_score") or 70.0) and critical == 0
    return {
        "model": MODEL_NAME, "version": MODEL_VERSION,
        "score": score, "max_score": 100.0, "passed": passed,
        "accuracy_score": round(accuracy, 2), "procedure_score": round(accuracy, 2),
        "timing_score": round(timing, 2), "grammar_score": round(grammar, 2),
        "errors": errors,
        "details": {"feedback": result.get("feedback"), "criteria": result.get("criteria"),
                    "correct_actions": result.get("correct_actions"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "norm_seconds": payload.get("norm_seconds")},
    }
