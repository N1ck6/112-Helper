"""Контракт ML API для Backend (backend/docs/INTEGRATION.md §1, ТЗ_итоговое §4 «ML API для Backend»).

Backend вызывает ML по путям /api/v1/...; здесь они переводятся на функции ML-сервиса:

  POST /api/v1/generate/scenarios  -> scenario_generator.generate_scenario по классификатору;
  POST /api/v1/evaluate/attempt    -> evaluator.evaluate_answer (для сценариев, созданных ML).

Чего в ML пока нет (коррекция по комментарию, грамматика, аналитика, рекомендации,
индексация материалов, оценка статусов ДДС и полей карточки без ML-сценария) —
ответ 501: backend в этом случае считает по своим правилам (HybridMLClient).
"""

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


def _to_backend_scenario(scenario: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    classification = scenario.get("classification") or {}
    caller = scenario.get("caller") or {}
    questions = scenario.get("questions") or []
    actions = scenario.get("expected_actions") or []
    return {
        "title": scenario.get("title"),
        "description": scenario.get("description"),
        "category_code": payload.get("category_code"),
        "difficulty": payload.get("difficulty", "basic"),
        "briefing": {
            "caller": {"name": caller.get("name"), "state": caller.get("emotion")},
            "dialogue": [],
            "address": caller.get("address"),
            "signs": [],
            "classification": classification,
            "main_service": classification.get("main_service"),
        },
        "reference": {
            "expected_fields": {"incident_class": classification.get("incident_type")},
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
    scenarios = []
    for i in range(count):
        scenario = generate_scenario(classifier_data=classifier_data, difficulty=difficulty,
                                     incident_number=numbers[i % len(numbers)])
        scenarios.append(_to_backend_scenario(scenario, payload))
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
