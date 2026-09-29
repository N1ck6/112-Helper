from __future__ import annotations

import random
import re
import time
from typing import Any, Protocol

import httpx

from app.core import address as address_rules
from app.core.arm112 import ADDRESS_FIELDS as ARM112_ADDRESS_FIELDS
from app.core.arm112 import FIELD_LABELS as ARM112_FIELD_LABELS
from app.core.arm112 import REQUIRED_CARD_FIELDS as ARM112_REQUIRED_FIELDS
from app.core.arm112 import format_address, service_title
from app.core.config import settings
from app.core.exceptions import IntegrationError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Правила регламента АРМ-112 (не заглушка: этими правилами backend оценивает всё, что не умеет ML)
STUB_MODEL_NAME = "rules-arm112-v1"


class MLClient(Protocol):
    """Интерфейс, который обязан реализовать ML-сервис команды."""

    name: str

    async def generate_scenarios(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def correct_scenario(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def evaluate_attempt(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def check_grammar(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def analytics(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def recommendations(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def index_material(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def dialogue_turn(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def health(self) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- HTTP
class HttpMLClient:
    """Реальный клиент: REST/JSON поверх httpx с таймаутом и единым разбором ошибок."""

    name = "http"

    ENDPOINTS = {
        "generate_scenarios": "/api/v1/generate/scenarios",
        "correct_scenario": "/api/v1/generate/correct",
        "evaluate_attempt": "/api/v1/evaluate/attempt",
        "check_grammar": "/api/v1/analyze/grammar",
        "analytics": "/api/v1/analytics/summary",
        "recommendations": "/api/v1/recommendations",
        "index_material": "/api/v1/knowledge/index",
        "dialogue_turn": "/dialogue/turn",
    }

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self._base_url = (base_url or settings.ML_SERVICE_URL).rstrip("/")
        self._timeout = timeout or settings.ML_TIMEOUT_SECONDS
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._http()
        url = self.ENDPOINTS[key]
        started = time.perf_counter()
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise IntegrationError(
                f"ML-сервис вернул {exc.response.status_code} на {url}", details={"body": exc.response.text[:500]}
            ) from exc
        except httpx.HTTPError as exc:
            raise IntegrationError(f"ML-сервис недоступен: {exc}") from exc
        data = response.json()
        data.setdefault("latency_ms", int((time.perf_counter() - started) * 1000))
        data.setdefault("model", data.get("model", "unknown"))
        return data

    async def generate_scenarios(self, payload): return await self._post("generate_scenarios", payload)

    async def correct_scenario(self, payload): return await self._post("correct_scenario", payload)

    async def evaluate_attempt(self, payload): return await self._post("evaluate_attempt", payload)

    async def check_grammar(self, payload): return await self._post("check_grammar", payload)

    async def analytics(self, payload): return await self._post("analytics", payload)

    async def recommendations(self, payload): return await self._post("recommendations", payload)

    async def index_material(self, payload): return await self._post("index_material", payload)

    async def dialogue_turn(self, payload): return await self._post("dialogue_turn", payload)

    async def health(self) -> dict[str, Any]:
        client = await self._http()
        try:
            response = await client.get("/health")
            return {"status": "ok" if response.is_success else "degraded", "code": response.status_code}
        except httpx.HTTPError as exc:
            return {"status": "down", "error": str(exc)}


INCIDENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "traffic_accident": {
        "title": "ДТП с пострадавшими",
        "fields": {
            "aon_phone": "+7 (495) 000-00-11",
            "applicant_name": "Иванов Сергей Петрович",
            "applicant_role": "очевидец",
            "address_region": "г. Москва",
            "address_district": "ЮЗАО",
            "address_area": "Академический",
            "address_street": "Ленинский проспект",
            "address_house": "45",
            "survey_signs": ["столкновение двух ТС", "пострадавший в салоне", "проезжая часть"],
            "incident_class": "ДТП с пострадавшими",
            "has_victims": True,
            "victims_count": 1,
            "blocked_persons": True,
            "description": (
                "Столкновение двух автомобилей на выезде с прилегающей территории, "
                "водитель одной из машин не может самостоятельно выйти из салона"
            ),
        },
        "caller": {"name": "Иванов Сергей", "state": "взволнован", "phone": "+7 (9xx) xxx-xx-01"},
    },
    "fire": {
        "title": "Возгорание в жилом доме",
        "fields": {
            "aon_phone": "+7 (495) 000-00-12",
            "applicant_name": "Петрова Анна Владимировна",
            "applicant_role": "участник",
            "address_region": "г. Москва",
            "address_district": "ЮЗАО",
            "address_area": "Черёмушки",
            "address_street": "улица Профсоюзная",
            "address_house": "12",
            "address_flat": "47",
            "address_entrance": "2",
            "address_floor": "4",
            "survey_signs": ["дым", "запах гари", "квартира"],
            "incident_class": "Пожар в жилом помещении",
            "has_victims": False,
            "victims_count": 0,
            "description": (
                "Дым из квартиры на четвёртом этаже, в подъезде резкий запах горелого, "
                "жильцы выходят на улицу"
            ),
        },
        "caller": {"name": "Петрова Анна", "state": "паника", "phone": "+7 (9xx) xxx-xx-02"},
    },
    "medical": {
        "title": "Потеря сознания",
        "fields": {
            "aon_phone": "+7 (495) 000-00-13",
            "applicant_name": "Смирнов Олег Игоревич",
            "applicant_role": "должностное лицо",
            "address_region": "г. Москва",
            "address_district": "ЦАО",
            "address_area": "Тверской",
            "address_street": "улица Тверская",
            "address_house": "6",
            "address_flat": "офис 210",
            "address_floor": "2",
            "survey_signs": ["без сознания", "дыхание есть", "рабочее место"],
            "incident_class": "Внезапное ухудшение состояния здоровья",
            "has_victims": True,
            "victims_count": 1,
            "description": "Мужчина 54 лет потерял сознание на рабочем месте, дышит, пульс есть",
        },
        "caller": {"name": "Смирнов Олег", "state": "спокоен", "phone": "+7 (9xx) xxx-xx-03"},
    },
    "utilities": {
        "title": "Прорыв водопровода",
        "fields": {
            "aon_phone": "+7 (495) 000-00-14",
            "applicant_name": "Кузнецова Ольга Николаевна",
            "applicant_role": "очевидец",
            "address_region": "г. Москва",
            "address_district": "СВАО",
            "address_area": "Останкинский",
            "address_street": "улица Академика Королёва",
            "address_house": "3",
            "survey_signs": ["вода на поверхности", "колодец", "подтопление входа"],
            "incident_class": "Коммунальная авария: водоснабжение",
            "has_victims": False,
            "victims_count": 0,
            "description": (
                "Вода поступает из колодца на тротуар, подтоплен вход в подъезд, "
                "движение пешеходов затруднено"
            ),
        },
        "caller": {"name": "Кузнецова Ольга", "state": "спокойна", "phone": "+7 (9xx) xxx-xx-04"},
    },
    "gas": {
        "title": "Запах газа в подъезде",
        "fields": {
            "aon_phone": "+7 (495) 000-00-15",
            "applicant_name": "Фёдоров Игорь Анатольевич",
            "applicant_role": "участник",
            "address_region": "г. Москва",
            "address_district": "ЮАО",
            "address_area": "Чертаново Северное",
            "address_street": "Варшавское шоссе",
            "address_house": "78",
            "address_entrance": "2",
            "address_floor": "1",
            "survey_signs": ["запах газа", "подъезд", "газовая колонка"],
            "incident_class": "Утечка бытового газа",
            "has_victims": False,
            "victims_count": 0,
            "emergency_mark": "нет",
            "description": "Жильцы сообщают о резком запахе газа на первом этаже, окна открыты",
        },
        "caller": {"name": "Фёдоров Игорь", "state": "встревожен", "phone": "+7 (9xx) xxx-xx-05"},
    },
}

TEMPLATE_ALIASES: dict[str, str] = {
    "traffic_injured": "traffic_accident",
    "fire_apartment": "fire",
    "fire_transport": "fire",
    "utilities_water": "utilities",
    "heating": "utilities",
}

#: Поля, обязательные при оценке полноты карточки — из состава АРМ-112.
REQUIRED_CARD_FIELDS = ARM112_REQUIRED_FIELDS
EXPECTED_ACTION_SEQUENCE = ["call_accepted", "field_filled", "classified", "card_submitted"]

DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "accuracy": settings.SCORE_WEIGHT_CORRECTNESS,
    "procedure": settings.SCORE_WEIGHT_SEQUENCE,
    "timing": settings.SCORE_WEIGHT_TIME,
    "grammar": settings.SCORE_WEIGHT_GRAMMAR,
}


WEIGHT_ALIASES: dict[str, str] = {
    "correctness": "accuracy",
    "правильность": "accuracy",
    "sequence": "procedure",
    "последовательность": "procedure",
    "time": "timing",
    "время": "timing",
    "грамматика": "grammar",
}


def _weights(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("weights") or {}
    given: dict[str, float] = {}
    for key, value in raw.items():
        name = WEIGHT_ALIASES.get(str(key).strip().lower(), str(key).strip().lower())
        if name not in DEFAULT_SCORE_WEIGHTS:
            continue
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if weight >= 0:
            given[name] = weight

    if not given:
        total = sum(DEFAULT_SCORE_WEIGHTS.values()) or 1.0
        return {key: value / total for key, value in DEFAULT_SCORE_WEIGHTS.items()}

    untouched = {
        key: value for key, value in DEFAULT_SCORE_WEIGHTS.items() if key not in given
    }
    given_total = sum(given.values())
    if given_total <= 0:
        #: Преподаватель обнулил всё, что назвал: считаем по остальным критериям.
        if not untouched:
            total = sum(DEFAULT_SCORE_WEIGHTS.values()) or 1.0
            return {key: value / total for key, value in DEFAULT_SCORE_WEIGHTS.items()}
        untouched_total = sum(untouched.values()) or 1.0
        result = dict.fromkeys(given, 0.0)
        result.update({key: value / untouched_total for key, value in untouched.items()})
        return result

    untouched_share = sum(untouched.values())
    default_total = sum(DEFAULT_SCORE_WEIGHTS.values()) or 1.0
    remainder = max(0.0, min(1.0, untouched_share / default_total))
    given_share = 1.0 - remainder

    result = {key: value / given_total * given_share for key, value in given.items()}
    if untouched:
        untouched_total = sum(untouched.values()) or 1.0
        result.update(
            {key: value / untouched_total * remainder for key, value in untouched.items()}
        )
    return result


def _is_address_field(field: str) -> bool:
    return field in ARM112_ADDRESS_FIELDS or field.startswith("address")

_GRAMMAR_RULES: list[tuple[str, str, str]] = [
    (r"\bпожарн[оа]я\s+часть\b", "style", "Используйте официальное наименование «пожарная охрана»"),
    (r"\s{2,}", "spacing", "Лишние пробелы"),
    (r"\bпострадавш[иы]х\s+нет\b", "style", "Укажите количество пострадавших числом"),
    (r"[a-zA-Z]{4,}", "language", "Карточка заполняется на русском языке"),
    (r"!{2,}|\?{2,}", "punctuation", "Недопустимое дублирование знаков препинания"),
]


class StubMLClient:
    name = "stub"

    async def generate_scenarios(self, payload: dict[str, Any]) -> dict[str, Any]:
        count = int(payload.get("count", 1))
        category = (payload.get("category_code") or "").lower()
        category = TEMPLATE_ALIASES.get(category, category)
        keys = list(INCIDENT_TEMPLATES)
        chosen = [k for k in keys if k == category] or keys
        rnd = random.Random(payload.get("seed") or 42)

        scenarios = []
        for index in range(count):
            key = chosen[index % len(chosen)]
            tpl = INCIDENT_TEMPLATES[key]
            expected = dict(tpl["fields"])
            description = expected["description"]
            address = format_address(expected)
            scenarios.append(
                {
                    "title": f"{tpl['title']} №{index + 1}",
                    "description": description,
                    "category_code": key,
                    "difficulty": payload.get("difficulty", "basic"),
                    "briefing": {
                        "caller": tpl["caller"],
                        "dialogue": [
                            {"role": "caller", "text": description},
                            {"role": "caller", "text": f"Адрес: {address}"},
                        ],
                        "address": address,
                        "signs": expected.get("survey_signs", []),
                    },
                    "reference": {
                        "expected_fields": expected,
                        "expected_actions": EXPECTED_ACTION_SEQUENCE,
                        "expected_text": {
                            "keywords": ["принято", "направлена"],
                            "forbidden": ["не знаю", "перезвоните"],
                            "min_length": 20,
                            "response": {
                                "primary_status": "accepted",
                                "final_status": "work_completed",
                                "require_progress": True,
                                "min_comment_length": 15,
                                "comment_rules": {"forbidden": ["не знаю"]},
                            },
                        },
                    },
                    "questions": [
                        {
                            "text": "Какие признаки происшествия нужно отметить в опросной карте?",
                            "options": expected.get("survey_signs", []) + ["Признаков нет"],
                            "correct": expected.get("survey_signs", []),
                        },
                        {
                            "text": "Какой класс происшествия присваивается карточке?",
                            "options": [expected["incident_class"], "Иное происшествие"],
                            "correct": [expected["incident_class"]],
                        },
                    ],
                    "seed": rnd.random(),
                }
            )
        return {"model": STUB_MODEL_NAME, "scenarios": scenarios, "stub": True}

    async def correct_scenario(self, payload: dict[str, Any]) -> dict[str, Any]:
        comment = (payload.get("comment") or "").strip()
        scenario = dict(payload.get("scenario") or {})
        reference = dict(payload.get("reference") or {})
        scenario["description"] = f"{scenario.get('description', '')}\n[Уточнение преподавателя: {comment}]".strip()
        reference.setdefault("expected_text", {})
        reference["expected_text"]["teacher_note"] = comment
        return {
            "model": STUB_MODEL_NAME,
            "scenario": scenario,
            "reference": reference,
            "applied_comment": comment,
            "stub": True,
        }

    async def evaluate_attempt(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("lesson_mode") == "card_action" or payload.get("response", {}).get("statuses"):
            return self._evaluate_response(payload)

        submitted: dict[str, Any] = payload.get("submitted_payload") or {}
        expected: dict[str, Any] = payload.get("expected_fields") or {}
        actions: list[str] = [a.get("action_type") for a in payload.get("actions") or []]
        duration_s = float(payload.get("duration_seconds") or 0.0)
        norm_s = float(payload.get("norm_seconds") or settings.DEFAULT_CARD_TIME_LIMIT_SECONDS)
        text_rules: dict[str, Any] = payload.get("expected_text") or {}

        errors: list[dict[str, Any]] = []

        # 1. Полнота: обязательные поля карточки АРМ-112.
        required = payload.get("required_fields") or list(REQUIRED_CARD_FIELDS)
        if expected:
            #: Требовать можно только то, что есть в эталоне: у вызова «МКАД, 74 км» нет дома,
            #: а заявитель «вызывает мама» не называет ФИО. Классификация и опросная карта
            #: заполняются всегда.
            required = [f for f in required if f in expected or f in ALWAYS_REQUIRED]
        for field in required:
            if not _as_text(submitted.get(field)).strip():
                errors.append(
                    {
                        "category": "completeness",
                        "severity": "critical",
                        "code": "field_empty",
                        "message": f"Не заполнено обязательное поле «{_field_label(field)}»",
                        "field_code": field,
                        "expected": _as_text(expected.get(field)),
                        "actual": "",
                        "penalty": 15.0,
                    }
                )

        address_factor = float(
            payload.get("address_error_factor") or settings.SCORE_ADDRESS_ERROR_FACTOR
        )
        matched = 0.0
        comparable = 0.0
        address_errors = 0
        for field, value in expected.items():
            if field == "notification_services":
                comparable += 1.0
                service_errors = _services_check(submitted.get(field), value)
                errors.extend(service_errors)
                if not any(e["code"] == "service_missing" for e in service_errors):
                    matched += 1.0
                continue
            is_address = _is_address_field(field)
            field_weight = address_factor if is_address else 1.0
            comparable += field_weight
            actual = _as_text(submitted.get(field))
            reference_value = _as_text(value)
            if _normalize(actual) == _normalize(reference_value) or (
                is_address and address_rules.same(field, actual, reference_value)
            ):
                matched += field_weight
                continue
            if not actual.strip():
                if not is_address:
                    comparable -= field_weight
                    continue
                errors.append(
                    {
                        "category": "completeness",
                        "severity": "major",
                        "code": "address_incomplete",
                        "message": (
                            f"Адрес неполный: не заполнено поле «{_field_label(field)}»"
                        ),
                        "field_code": field,
                        "expected": reference_value,
                        "actual": "",
                        "penalty": round(5.0 * address_factor, 2),
                    }
                )
                continue
            if field in FREE_TEXT_FIELDS:
                #: Свободный текст (описание со слов заявителя) не сверяется дословно: важно,
                #: передана ли суть — доля значимых слов эталона, найденных в ответе.
                ratio = _keyword_share(actual, reference_value)
                if ratio >= 0.4:
                    matched += field_weight
                else:
                    errors.append({
                        "category": "completeness", "severity": "minor", "code": "description_incomplete",
                        "message": f"В поле «{_field_label(field)}» не хватает сути со слов заявителя",
                        "field_code": field, "expected": reference_value, "actual": actual, "penalty": 4.0,
                    })
                continue
            ratio = _similarity(_normalize(actual), _normalize(reference_value))
            if ratio >= 0.8 and not is_address:
                matched += field_weight
                continue
            if is_address:
                address_errors += 1
                errors.append(
                    {
                        "category": "data_accuracy",
                        "severity": "critical",
                        "code": "address_mismatch",
                        "message": (
                            f"Ошибка в адресе: поле «{_field_label(field)}» не совпадает с "
                            f"эталоном. Неверный адрес направляет силы в другой район"
                        ),
                        "field_code": field,
                        "expected": reference_value,
                        "actual": actual,
                        "penalty": round(10.0 * address_factor, 2),
                    }
                )
            else:
                errors.append(
                    {
                        "category": "data_accuracy",
                        "severity": "major" if ratio < 0.5 else "minor",
                        "code": "field_mismatch",
                        "message": f"Поле «{_field_label(field)}» не соответствует эталону",
                        "field_code": field,
                        "expected": reference_value,
                        "actual": actual,
                        "penalty": 10.0 if ratio < 0.5 else 4.0,
                    }
                )
        accuracy_score = 100.0 * matched / comparable if comparable else 100.0

        # 3. Регламент: последовательность действий.
        expected_actions = payload.get("expected_actions") or EXPECTED_ACTION_SEQUENCE
        #: Блоки карточки можно заполнять в любом порядке (инструкция «Заведение карточки», п.4):
        #: «тип» и «адрес» засчитываются в любой очерёдности, важны приём вызова первым и сохранение последним.
        swapped = [
            {"field_filled": "classified", "classified": "field_filled"}.get(a, a) for a in expected_actions
        ]
        procedure_score = max(_sequence_score(actions, expected_actions), _sequence_score(actions, swapped))
        missing = [a for a in expected_actions if a not in actions]
        for action in missing:
            errors.append(
                {
                    "category": "procedure",
                    "severity": "major",
                    "code": "action_missing",
                    "message": f"Не выполнено действие регламента: {action}",
                    "field_code": None,
                    "expected": action,
                    "actual": ", ".join(actions) or "—",
                    "penalty": 8.0,
                }
            )

        # 4. Тайминг относительно норматива.
        if norm_s <= 0:
            timing_score = 100.0
        elif duration_s <= norm_s:
            timing_score = 100.0
        else:
            overtime_ratio = (duration_s - norm_s) / norm_s
            timing_score = max(0.0, 100.0 - overtime_ratio * 60.0)
            errors.append(
                {
                    "category": "timing",
                    "severity": "critical" if overtime_ratio > 1 else "major",
                    "code": "norm_exceeded",
                    "message": (
                        f"Превышен норматив: {duration_s:.1f} с вместо {norm_s:.0f} с "
                        f"(+{duration_s - norm_s:.1f} с)"
                    ),
                    "field_code": None,
                    "expected": f"{norm_s:.0f}",
                    "actual": f"{duration_s:.1f}",
                    "penalty": 10.0 if overtime_ratio <= 1 else 20.0,
                }
            )

        # 5. Текст и грамматика свободных формулировок.
        free_text = " ".join(
            str(value) for key, value in submitted.items() if key in ("description", "operator_message", "note")
        )
        grammar = _grammar_check(free_text, text_rules)
        errors.extend(grammar["errors"])
        grammar_score = grammar["score"]

        weights = _weights(payload)
        score = round(
            weights["accuracy"] * accuracy_score
            + weights["procedure"] * procedure_score
            + weights["timing"] * timing_score
            + weights["grammar"] * grammar_score,
            2,
        )
        critical = sum(1 for e in errors if e["severity"] == "critical")
        max_errors = int(payload.get("max_errors") or settings.DEFAULT_MAX_ERRORS)
        min_score = float(payload.get("min_score") or 70.0)
        passed = score >= min_score and critical == 0 and len(errors) <= max_errors

        return {
            "model": STUB_MODEL_NAME,
            "version": "1.0",
            "score": score,
            "max_score": 100.0,
            "passed": passed,
            "timing_score": round(timing_score, 2),
            "procedure_score": round(procedure_score, 2),
            "accuracy_score": round(accuracy_score, 2),
            "grammar_score": round(grammar_score, 2),
            "errors": errors,
            "details": {
                "fields_matched": round(matched, 2),
                "fields_compared": round(comparable, 2),
                "address_errors": address_errors,
                "address_error_factor": address_factor,
                "actions_observed": actions,
                "actions_expected": expected_actions,
                "duration_seconds": duration_s,
                "norm_seconds": norm_s,
                "weights": {key: round(value, 4) for key, value in weights.items()},
            },
            "stub": True,
        }

    def _evaluate_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        response: dict[str, Any] = payload.get("response") or {}
        expected: dict[str, Any] = payload.get("expected_response") or {}
        statuses: list[dict[str, Any]] = [
            item for item in (response.get("statuses") or []) if not item.get("set_by_system")
        ]
        norm_s = float(payload.get("norm_seconds") or settings.DEFAULT_CARD_TIME_LIMIT_SECONDS)
        errors: list[dict[str, Any]] = []

        chain = [item["status"] for item in statuses]
        first_status = response.get("first_status")
        first_seconds = response.get("first_seconds")

        # 1. Первичный статус и норматив 30 секунд.
        if first_status is None:
            timing_score = 0.0
            errors.append(
                {
                    "category": "timing",
                    "severity": "critical",
                    "code": "primary_status_missing",
                    "message": (
                        "Не проставлен первичный статус «Принята»/«Не принята» — "
                        "карточка переходит в состояние «Не оповещено»"
                    ),
                    "field_code": None,
                    "expected": "accepted | not_accepted",
                    "actual": "—",
                    "penalty": 25.0,
                }
            )
        elif response.get("is_late"):
            overtime = max(0.0, float(first_seconds or 0) - norm_s)
            timing_score = max(0.0, 100.0 - (overtime / norm_s) * 60.0)
            errors.append(
                {
                    "category": "timing",
                    "severity": "critical" if overtime > norm_s else "major",
                    "code": "primary_status_late",
                    "message": (
                        f"Первичный статус проставлен через {float(first_seconds or 0):.1f} с "
                        f"при нормативе {norm_s:.0f} с (+{overtime:.1f} с)"
                    ),
                    "field_code": None,
                    "expected": f"{norm_s:.0f}",
                    "actual": f"{float(first_seconds or 0):.1f}",
                    "penalty": 15.0,
                }
            )
        else:
            timing_score = 100.0

        # 2. Правильность решения: принимать или не принимать к реагированию.
        expected_primary = expected.get("primary_status")
        if expected_primary and first_status and first_status != expected_primary:
            accuracy_score = 0.0
            errors.append(
                {
                    "category": "procedure",
                    "severity": "critical",
                    "code": "wrong_primary_status",
                    "message": (
                        "Решение не соответствует компетенции службы и характеру происшествия"
                    ),
                    "field_code": None,
                    "expected": expected_primary,
                    "actual": first_status,
                    "penalty": 20.0,
                }
            )
        else:
            accuracy_score = 100.0 if first_status else 0.0

        refusal_statuses = {"not_accepted", "work_refused"}
        if response.get("is_primary_service") and refusal_statuses.intersection(chain):
            accuracy_score = min(accuracy_score, 20.0)
            errors.append(
                {
                    "category": "procedure",
                    "severity": "critical",
                    "code": "primary_service_refused",
                    "message": (
                        "Отказ от реагирования на профильное происшествие: служба указана "
                        "в списке оповещения как профильная, происшествие в её компетенции"
                    ),
                    "field_code": None,
                    "expected": "accepted",
                    "actual": ", ".join(sorted(refusal_statuses.intersection(chain))),
                    "penalty": 25.0,
                }
            )

        # 3. Комментарии там, где они обязательны.
        grammar_penalty = 0.0
        min_length = int(expected.get("min_comment_length") or 15)
        for item in statuses:
            if item["status"] not in ("not_accepted", "work_refused"):
                continue
            comment = (item.get("comment") or "").strip()
            if not comment:
                errors.append(
                    {
                        "category": "completeness",
                        "severity": "critical",
                        "code": "comment_missing",
                        "message": (
                            f"К статусу «{item['status']}» не внесён комментарий с причиной"
                        ),
                        "field_code": item["status"],
                        "expected": "причина отказа",
                        "actual": "—",
                        "penalty": 20.0,
                    }
                )
                continue
            if len(comment) < min_length:
                errors.append(
                    {
                        "category": "completeness",
                        "severity": "major",
                        "code": "comment_incomplete",
                        "message": (
                            "Комментарий неполный: укажите причину и куда передана информация"
                        ),
                        "field_code": item["status"],
                        "expected": f"не менее {min_length} символов",
                        "actual": str(len(comment)),
                        "penalty": 8.0,
                    }
                )
            grammar = _grammar_check(comment, expected.get("comment_rules") or {})
            errors.extend(grammar["errors"])
            grammar_penalty += 100.0 - grammar["score"]

        # 4. Статусы хода выполнения работ и финальный статус.
        progress = [s for s in chain if s in ("response_started", "arrived", "work_in_progress")]
        expected_final = expected.get("final_status")
        procedure_hits = 0.0
        procedure_total = 0.0

        if expected.get("require_progress", True) and first_status == "accepted":
            procedure_total += 1
            if progress:
                procedure_hits += 1
            else:
                errors.append(
                    {
                        "category": "procedure",
                        "severity": "major",
                        "code": "progress_statuses_missing",
                        "message": (
                            "Нет статусов хода работ («Начало реагирования», «Прибытие», "
                            "«Проведение работ») — другие службы не видят, что реагирование идёт"
                        ),
                        "field_code": None,
                        "expected": "response_started → arrived → work_in_progress",
                        "actual": ", ".join(chain) or "—",
                        "penalty": 8.0,
                    }
                )
        if expected_final:
            procedure_total += 1
            if chain and chain[-1] == expected_final:
                procedure_hits += 1
            else:
                errors.append(
                    {
                        "category": "procedure",
                        "severity": "major",
                        "code": "final_status_mismatch",
                        "message": "Итоговый статус не соответствует результату реагирования",
                        "field_code": None,
                        "expected": expected_final,
                        "actual": chain[-1] if chain else "—",
                        "penalty": 10.0,
                    }
                )
        procedure_score = 100.0 * procedure_hits / procedure_total if procedure_total else 100.0

        grammar_score = max(0.0, 100.0 - grammar_penalty)
        score = round(
            0.35 * timing_score + 0.30 * accuracy_score + 0.25 * procedure_score + 0.10 * grammar_score,
            2,
        )
        critical = sum(1 for e in errors if e["severity"] == "critical")
        max_errors = int(payload.get("max_errors") or settings.DEFAULT_MAX_ERRORS)
        min_score = float(payload.get("min_score") or 70.0)
        passed = score >= min_score and critical == 0 and len(errors) <= max_errors

        return {
            "model": STUB_MODEL_NAME,
            "version": "1.0",
            "score": score,
            "max_score": 100.0,
            "passed": passed,
            "timing_score": round(timing_score, 2),
            "procedure_score": round(procedure_score, 2),
            "accuracy_score": round(accuracy_score, 2),
            "grammar_score": round(grammar_score, 2),
            "errors": errors,
            "details": {
                "mode": "card_action",
                "status_chain": chain,
                "first_status": first_status,
                "first_seconds": first_seconds,
                "norm_seconds": norm_s,
                "lifecycle_status": response.get("lifecycle_status"),
                "weights": {"timing": 0.35, "accuracy": 0.30, "procedure": 0.25, "grammar": 0.10},
            },
            "stub": True,
        }

    async def check_grammar(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = _grammar_check(payload.get("text") or "", payload.get("rules") or {})
        return {"model": STUB_MODEL_NAME, "score": result["score"], "errors": result["errors"], "stub": True}

    async def analytics(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"model": STUB_MODEL_NAME, "insights": [], "stub": True}

    async def recommendations(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Рекомендации собираются из статистики ошибок, переданной backend'ом."""
        buckets: list[dict[str, Any]] = payload.get("top_errors") or []
        items: list[dict[str, Any]] = []
        advice = {
            "timing": (
                "Отработать скорость приёма вызова",
                "Тренируйте заполнение адреса и типа происшествия «вслепую»: "
                "основная потеря времени — на первых двух полях.",
            ),
            "procedure": (
                "Повторить регламент обработки вызова",
                "Вернитесь к памятке «Работа на АРМ-112»: обязательна последовательность "
                "приём → классификация → передача в ДДС.",
            ),
            "data_accuracy": (
                "Уточнять данные у заявителя",
                "Переспрашивайте адрес и количество пострадавших, повторяя их вслух для подтверждения.",
            ),
            "completeness": (
                "Не оставлять обязательные поля пустыми",
                "Перед отправкой карточки проверяйте блок обязательных полей.",
            ),
            "grammar": (
                "Следить за формулировками",
                "Используйте типовые формулировки из справочной базы, избегайте сокращений.",
            ),
            "classification": (
                "Повторить классификатор происшествий",
                "Разберите отличия смежных категорий (ЖКХ/газ, медицина/ДТП с пострадавшими).",
            ),
            "syntax": (
                "Соблюдать требования к синтаксису ответа",
                "Ответ должен содержать подтверждение приёма и указание направленных служб.",
            ),
        }
        for bucket in buckets[:3]:
            title, text = advice.get(
                bucket.get("category", ""), ("Отработать типовую ошибку", "Разберите ошибку с преподавателем.")
            )
            items.append(
                {
                    "title": title,
                    "text": text,
                    "priority": 1 if bucket.get("share", 0) > 0.3 else 2,
                    "based_on": bucket,
                }
            )
        return {"model": STUB_MODEL_NAME, "recommendations": items, "stub": True}

    async def dialogue_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Без ML заявитель пересказывает карточку и дальше просит повторить."""
        card = (payload.get("context") or {}).get("card") or {}
        if int(payload.get("turn") or 0) == 0:
            parts = [card.get("description"), card.get("address")]
            text = ". ".join(str(p).rstrip(".") for p in parts if p) or "Алло, у нас происшествие!"
            return {"reply_text": f"Алло, это 112? {text}.", "end_call": False, "model": STUB_MODEL_NAME}
        return {"reply_text": "Повторите, пожалуйста, плохо слышно.", "end_call": False, "model": STUB_MODEL_NAME}

    async def index_material(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": STUB_MODEL_NAME,
            "indexed": True,
            "material_id": payload.get("material_id"),
            "chunks": 0,
            "stub": True,
        }

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "mode": "stub"}

    async def close(self) -> None:  # совместимость с HttpMLClient
        return None


# ------------------------------------------------------------------- утилиты стаба
def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, list | tuple | set):
        return ", ".join(sorted(_as_text(item) for item in value))
    if isinstance(value, dict):
        return ", ".join(f"{key}: {_as_text(item)}" for key, item in sorted(value.items()))
    return str(value)


def _field_label(code: str) -> str:
    return ARM112_FIELD_LABELS.get(code, code)


def _normalize(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _similarity(left: str, right: str) -> float:
    """Доля совпавших слов (мера Жаккара) — достаточно для учебной проверки полей."""
    left_set, right_set = set(left.split()), set(right.split())
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


#: Поля, где обучающийся пишет своими словами — сверяются по сути, а не дословно
FREE_TEXT_FIELDS = frozenset({"description", "operator_message", "address_text"})


def _stems(text: str) -> set[str]:
    """Основы значимых слов: без коротких слов и окончаний (первые 5 букв) — падежи не мешают."""
    return {w[:5] for w in re.findall(r"[а-яёa-z0-9]{4,}", (text or "").lower())}


def _keyword_share(actual: str, expected: str) -> float:
    """Доля основ слов эталона, которые есть в ответе обучающегося."""
    want = _stems(expected)
    return len(want & _stems(actual)) / len(want) if want else 1.0


#: Поля, которые обязательны в любой карточке, даже если эталон их не содержит
ALWAYS_REQUIRED = frozenset({"incident_class", "survey_signs", "description"})

#: Службы списка оповещения: код → слова, по которым служба узнаётся в подписи интерфейса
SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "101": ("101", "01", "мчс", "пожарн"),
    "102": ("102", "02", "омвд", "полиц"),
    "103": ("103", "03", "смп", "скорая"),
    "104": ("104", "04", "мосгаз", "газов"),
    "mosvodokanal": ("мосводоканал",),
    "zhilishnik": ("жилищник",),
    "moek": ("моэк",),
    "dps": ("дпс", "гибдд"),
    "codd": ("цодд",),
    "ods": ("одс",),
    "uprava": ("упр", "управ"),
    "mosbez": ("мос.без", "мосбез"),
}
EMERGENCY_SERVICES = frozenset({"101", "102", "103", "104"})


def _service_codes(value: Any) -> set[str]:
    """Коды служб из того, что прислал интерфейс: «Служба 101 (МЧС)», «101», «mosvodokanal»."""
    items = value if isinstance(value, list | tuple | set) else [value] if value else []
    codes: set[str] = set()
    for item in items:
        text = str(item.get("code") if isinstance(item, dict) else item).lower().strip()
        if text in SERVICE_ALIASES:
            codes.add(text)
            continue
        digits = re.findall(r"\b(10[1-4]|0[1-4])\b", text)
        if digits:
            codes.update("1" + d[-2:] for d in digits)
            continue
        for code, aliases in SERVICE_ALIASES.items():
            if any(alias in text for alias in aliases if not alias.isdigit()):
                codes.add(code)
                break
    return codes


def _services_check(actual: Any, expected: Any) -> list[dict[str, Any]]:
    """Выбор служб оператором (ТЗ 1.1): пропущенная служба — ошибка, лишняя экстренная — замечание."""
    want, got = _service_codes(expected), _service_codes(actual)
    errors: list[dict[str, Any]] = []
    for code in sorted(want - got):
        errors.append({
            "category": "data_accuracy", "severity": "major", "code": "service_missing",
            "message": f"Не выбрана служба «{service_title(code)}»",
            "field_code": "notification_services", "expected": service_title(code),
            "actual": ", ".join(service_title(c) for c in sorted(got)) or "—", "penalty": 8.0,
        })
    for code in sorted((got - want) & EMERGENCY_SERVICES):
        errors.append({
            "category": "data_accuracy", "severity": "minor", "code": "service_extra",
            "message": f"Лишняя служба «{service_title(code)}»: по этому вызову её не привлекают",
            "field_code": "notification_services", "expected": "—",
            "actual": service_title(code), "penalty": 3.0,
        })
    return errors


def _sequence_score(actual: list[str], expected: list[str]) -> float:
    """Доля эталонных действий, выполненных в правильном порядке (LCS-подход)."""
    if not expected:
        return 100.0
    actual = [a for a in actual if a]
    lcs = [[0] * (len(expected) + 1) for _ in range(len(actual) + 1)]
    for i in range(1, len(actual) + 1):
        for j in range(1, len(expected) + 1):
            if actual[i - 1] == expected[j - 1]:
                lcs[i][j] = lcs[i - 1][j - 1] + 1
            else:
                lcs[i][j] = max(lcs[i - 1][j], lcs[i][j - 1])
    return 100.0 * lcs[len(actual)][len(expected)] / len(expected)


def _grammar_check(text: str, rules: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    stripped = text.strip()

    min_length = int(rules.get("min_length") or 0)
    if min_length and len(stripped) < min_length:
        errors.append(
            {
                "category": "syntax",
                "severity": "minor",
                "code": "text_too_short",
                "message": f"Формулировка короче требуемых {min_length} символов",
                "field_code": None,
                "expected": str(min_length),
                "actual": str(len(stripped)),
                "penalty": 3.0,
            }
        )
    for keyword in rules.get("keywords") or []:
        if keyword and keyword.lower() not in stripped.lower():
            errors.append(
                {
                    "category": "syntax",
                    "severity": "minor",
                    "code": "keyword_missing",
                    "message": f"В ответе отсутствует обязательная формулировка «{keyword}»",
                    "field_code": None,
                    "expected": keyword,
                    "actual": stripped[:120],
                    "penalty": 4.0,
                }
            )
    for word in rules.get("forbidden") or []:
        if word and word.lower() in stripped.lower():
            errors.append(
                {
                    "category": "syntax",
                    "severity": "major",
                    "code": "forbidden_phrase",
                    "message": f"Недопустимая формулировка «{word}»",
                    "field_code": None,
                    "expected": "—",
                    "actual": word,
                    "penalty": 8.0,
                }
            )
    if stripped:
        if stripped[0].islower():
            errors.append(
                {
                    "category": "grammar",
                    "severity": "minor",
                    "code": "capital_letter",
                    "message": "Текст должен начинаться с заглавной буквы",
                    "field_code": None,
                    "expected": stripped[0].upper(),
                    "actual": stripped[0],
                    "penalty": 2.0,
                }
            )
        for pattern, code, message in _GRAMMAR_RULES:
            if re.search(pattern, stripped, flags=re.IGNORECASE):
                errors.append(
                    {
                        "category": "grammar",
                        "severity": "minor",
                        "code": code,
                        "message": message,
                        "field_code": None,
                        "expected": "—",
                        "actual": stripped[:120],
                        "penalty": 2.0,
                    }
                )
    score = max(0.0, 100.0 - sum(e["penalty"] for e in errors) * 2)
    return {"score": score, "errors": errors}


# ------------------------------------------------------------------ гибрид
class HybridMLClient:
    """ML-сервис с откатом на правила по каждому методу.

    ML-сервис команды реализует контракт частично: на то, чего он не умеет, он отвечает
    501, а при сбое или таймауте ответа нет вовсе. В обоих случаях метод выполняют правила
    StubMLClient, чтобы занятие не останавливалось (оценка не зависает в outbox, генерация
    не падает). Ответ правил помечен `stub: true` и `fallback_reason` — в ml_results видно,
    кто считал.
    """

    name = "hybrid"

    def __init__(self) -> None:
        self.http = HttpMLClient()
        self.rules = StubMLClient()

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await getattr(self.http, method)(payload)
        except IntegrationError as exc:
            logger.info("ml_fallback_to_rules", extra={"method": method, "reason": exc.message})
            response = await getattr(self.rules, method)(payload)
            response["fallback_reason"] = exc.message
            return response

    async def generate_scenarios(self, payload): return await self._call("generate_scenarios", payload)

    async def correct_scenario(self, payload): return await self._call("correct_scenario", payload)

    async def evaluate_attempt(self, payload): return await self._call("evaluate_attempt", payload)

    async def check_grammar(self, payload): return await self._call("check_grammar", payload)

    async def analytics(self, payload): return await self._call("analytics", payload)

    async def recommendations(self, payload): return await self._call("recommendations", payload)

    async def index_material(self, payload): return await self._call("index_material", payload)

    async def dialogue_turn(self, payload): return await self._call("dialogue_turn", payload)

    async def health(self) -> dict[str, Any]:
        return {**await self.http.health(), "fallback": "rules"}

    async def close(self) -> None:
        await self.http.close()


# -------------------------------------------------------------------- фабрика
_ml_client: MLClient | None = None


def get_ml_client() -> MLClient:
    global _ml_client
    if _ml_client is None:
        if settings.ML_USE_STUB:
            logger.info("ml_client_mode", extra={"mode": "stub"})
            _ml_client = StubMLClient()
        elif settings.ML_FALLBACK_TO_RULES:
            logger.info("ml_client_mode", extra={"mode": "hybrid", "url": settings.ML_SERVICE_URL})
            _ml_client = HybridMLClient()
        else:
            logger.info("ml_client_mode", extra={"mode": "http", "url": settings.ML_SERVICE_URL})
            _ml_client = HttpMLClient()
    return _ml_client


async def close_ml_client() -> None:
    global _ml_client
    if _ml_client is not None and hasattr(_ml_client, "close"):
        await _ml_client.close()  # type: ignore[attr-defined]
    _ml_client = None
