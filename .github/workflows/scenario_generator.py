import random
import uuid
from typing import Any, Dict, List, Optional


ALLOWED_DIFFICULTIES = {
    "easy",
    "medium",
    "hard",
}


CALLER_NAMES = [
    "Анна",
    "Алексей",
    "Мария",
    "Иван",
    "Елена",
    "Дмитрий",
    "Ольга",
    "Максим",
    "Наталья",
    "Сергей",
]


def _safe_str(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _combined(
    classification: Dict[str, Any],
) -> str:

    values = [
        classification.get("category", ""),
        classification.get("group", ""),
        classification.get("incident_type", ""),
        classification.get("ekp35_type", ""),
    ]

    return " ".join(
        _safe_str(value).lower()
        for value in values
        if value
    )


def _difficulty_description(
    difficulty: str,
) -> str:
    descriptions = {
        "easy": (
            "Базовый сценарий. "
            "Требуется собрать основные сведения о происшествии."
        ),
        "medium": (
            "Сценарий средней сложности. "
            "Помимо основных сведений требуется уточнить "
            "существенные обстоятельства происшествия."
        ),
        "hard": (
            "Сложный сценарий. "
            "Требуется собрать основные сведения и дополнительные "
            "обстоятельства, которые могут влиять на дальнейшую обработку."
        ),
    }

    return descriptions.get(
        difficulty,
        descriptions["medium"],
    )



def _get_incidents(
    classifier_data: Any,
) -> List[Dict[str, Any]]:

    if isinstance(classifier_data, list):
        return [
            item
            for item in classifier_data
            if isinstance(item, dict)
        ]

    if isinstance(classifier_data, dict):

        for key in (
            "incidents",
            "data",
            "items",
            "rows",
        ):
            value = classifier_data.get(key)

            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

    return []


def _find_incident(
    classifier_data: Any,
    incident_number: Optional[str] = None,
) -> Dict[str, Any]:


    incidents = _get_incidents(classifier_data)

    if not incidents:
        raise ValueError(
            "classifier_data не содержит инцидентов"
        )

    if incident_number is not None:
        target = str(incident_number).strip()

        for incident in incidents:
            number = (
                incident.get("incident_number")
                or incident.get("number")
                or incident.get("code")
            )

            if number is not None and str(number).strip() == target:
                return incident

        raise ValueError(
            f"Инцидент {incident_number} не найден "
            f"в официальном классификаторе"
        )

    return random.choice(incidents)


def _build_description(
    classification: Dict[str, Any],
) -> str:

    category = _safe_str(
        classification.get("category")
    )

    group = _safe_str(
        classification.get("group")
    )

    incident_type = _safe_str(
        classification.get("incident_type")
    )

    ekp35_type = _safe_str(
        classification.get("ekp35_type")
    )

    parts = []

    if category:
        parts.append(
            f"Категория: {category}"
        )

    if group:
        parts.append(
            f"Группа: {group}"
        )

    if incident_type:
        parts.append(
            f"Тип происшествия: {incident_type}"
        )

    if ekp35_type:
        parts.append(
            f"Тип ЕКП-35: {ekp35_type}"
        )

    return ". ".join(parts)



def _build_case_facts(
    classification: Dict[str, Any],
    difficulty: str,
) -> Dict[str, Any]:

    return {
        "category": classification.get(
            "category"
        ),

        "group": classification.get(
            "group"
        ),

        "incident_type": classification.get(
            "incident_type"
        ),

        "ekp35_type": classification.get(
            "ekp35_type"
        ),

        "difficulty_note": _difficulty_description(
            difficulty
        ),
    }


BASE_QUESTIONS = [
    "Где произошло происшествие?",
    "Что именно произошло?",
    "Есть ли пострадавшие?",
    "Расскажите подробнее о ситуации.",
]

BASE_EXPECTED_ACTIONS = [
    "Уточнить точный адрес или место происшествия.",
    "Уточнить, что именно произошло.",
    "Уточнить наличие пострадавших.",
    "Уточнить дополнительные обстоятельства происшествия.",
]


BASE_CRITERIA = [
    {
        "id": "location",
        "description": "Уточнить точный адрес или место происшествия",
        "weight": 20,
    },
    {
        "id": "event",
        "description": "Уточнить, что именно произошло",
        "weight": 20,
    },
    {
        "id": "victims",
        "description": "Уточнить наличие пострадавших",
        "weight": 20,
    },
    {
        "id": "clarification",
        "description": "Уточнить дополнительные обстоятельства происшествия",
        "weight": 25,
    },
]



def _detect_scenario_type(
    classification: Dict[str, Any],
) -> str:

    text = _combined(classification)



    if "дтп" in text or "дорожно-транспорт" in text:
        return "dtp"

    if "газ" in text:
        return "gas"

    if "лифт" in text:
        return "elevator"

    if (
        "пожар" in text
        or "возгора" in text
        or "горени" in text
        or "огн" in text
        or "дым" in text
    ):
        return "fire"

    return "general"


def _build_questions(
    classification: Dict[str, Any],
    difficulty: str,
) -> List[str]:

    questions = list(BASE_QUESTIONS)

    scenario_type = _detect_scenario_type(
        classification
    )

    if scenario_type == "fire":

        questions.extend(
            [
                "Есть ли открытое пламя или только дым?",
                "Что именно горит или дымит?",
                "Есть ли люди внутри здания или помещения?",
            ]
        )



    elif scenario_type == "dtp":

        questions.extend(
            [
                "Сколько автомобилей или других транспортных средств участвует?",
                "Перекрыто ли движение?",
            ]
        )


    elif scenario_type == "gas":

        questions.extend(
            [
                "Чувствуется ли запах газа?",
                "Есть ли люди рядом с предполагаемой утечкой или в опасной зоне?",
            ]
        )


    elif scenario_type == "elevator":

        questions.extend(
            [
                "Находятся ли люди в кабине лифта?",
                "Открываются ли двери лифта?",
            ]
        )


    if difficulty == "hard":

        questions.append(
            "Какие дополнительные обстоятельства "
            "могут повлиять на оценку ситуации?"
        )

        questions.append(
            "Что уже было сделано на месте происшествия?"
        )

    return questions



def _build_expected_actions(
    classification: Dict[str, Any],
    difficulty: str,
) -> List[str]:

    actions = list(BASE_EXPECTED_ACTIONS)

    scenario_type = _detect_scenario_type(
        classification
    )


    if scenario_type == "fire":

        actions.extend(
            [
                "Уточнить наличие открытого пламени.",
                "Уточнить, что именно горит или дымит.",
                "Уточнить наличие людей внутри здания или помещения.",
            ]
        )


    elif scenario_type == "dtp":

        actions.extend(
            [
                "Уточнить количество участвующих транспортных средств.",
                "Уточнить, перекрыто ли движение.",
            ]
        )


    elif scenario_type == "gas":

        actions.extend(
            [
                "Уточнить наличие запаха газа.",
                "Уточнить наличие людей рядом с утечкой или в опасной зоне.",
            ]
        )


    elif scenario_type == "elevator":

        actions.extend(
            [
                "Уточнить, находятся ли люди в кабине лифта.",
                "Уточнить, открываются ли двери лифта.",
            ]
        )


    if difficulty == "hard":

        actions.extend(
            [
                "Уточнить дополнительные обстоятельства, "
                "которые могут изменить оценку ситуации.",
                "Уточнить, какие действия уже были выполнены "
                "на месте происшествия.",
            ]
        )

    return actions



def _build_evaluation_criteria(
    classification: Dict[str, Any],
    difficulty: str,
) -> List[Dict[str, Any]]:

    criteria = [
        dict(item)
        for item in BASE_CRITERIA
    ]

    scenario_type = _detect_scenario_type(
        classification
    )


    if scenario_type == "fire":

        criteria.extend(
            [
                {
                    "id": "fire_open_flame",
                    "description": "Уточнить наличие открытого пламени",
                    "weight": 10,
                },
                {
                    "id": "fire_what_burns",
                    "description": "Уточнить, что именно горит или дымит",
                    "weight": 10,
                },
                {
                    "id": "fire_people",
                    "description": "Уточнить наличие людей внутри здания или помещения",
                    "weight": 10,
                },
            ]
        )


    elif scenario_type == "dtp":

        criteria.append(
            {
                "id": "dtp_details",
                "description": (
                    "Уточнить количество участвующих "
                    "транспортных средств и состояние движения"
                ),
                "weight": 15,
            }
        )


    elif scenario_type == "gas":

        criteria.append(
            {
                "id": "gas_details",
                "description": (
                    "Уточнить наличие запаха газа "
                    "и людей в опасной зоне"
                ),
                "weight": 15,
            }
        )


    elif scenario_type == "elevator":

        criteria.extend(
            [
                {
                    "id": "elevator_people",
                    "description": "Уточнить, находятся ли люди в кабине лифта",
                    "weight": 10,
                },
                {
                    "id": "elevator_doors",
                    "description": "Уточнить, открываются ли двери лифта",
                    "weight": 10,
                },
            ]
        )


    if difficulty == "hard":

        criteria.extend(
            [
                {
                    "id": "additional_circumstances",
                    "description": (
                        "Уточнить дополнительные обстоятельства, "
                        "которые могут изменить оценку ситуации"
                    ),
                    "weight": 10,
                },
                {
                    "id": "actions_taken",
                    "description": (
                        "Уточнить, какие действия уже были "
                        "выполнены на месте происшествия"
                    ),
                    "weight": 10,
                },
            ]
        )

    return criteria



def _build_service_response(
    classification: Dict[str, Any],
) -> Dict[str, Any]:

    main_service = (
        classification.get("main_service")
        or classification.get("service")
        or ""
    )

    return {
        "main_service": main_service,
        "source": "Klassifikator.xlsx",
    }



def _build_caller(
    classification: Dict[str, Any],
) -> Dict[str, Any]:

    return {
        "name": random.choice(CALLER_NAMES),


        "address": None,

        "emotion": random.choice(
            [
                "спокойный",
                "взволнованный",
                "испуганный",
                "растерянный",
            ]
        ),

        "classification_context": (
            classification.get("incident_type")
        ),
    }



def generate_scenario(
    classifier_data: Any,
    incident_number: Optional[str] = None,
    difficulty: str = "medium",
) -> Dict[str, Any]:


    difficulty = str(
        difficulty or "medium"
    ).lower().strip()

    if difficulty not in ALLOWED_DIFFICULTIES:
        raise ValueError(
            "difficulty должен быть одним из: "
            + ", ".join(sorted(ALLOWED_DIFFICULTIES))
        )


    incident = _find_incident(
        classifier_data=classifier_data,
        incident_number=incident_number,
    )


    classification = {
        "source": (
            incident.get("source")
            or "Klassifikator.xlsx"
        ),

        "verified": incident.get(
            "verified",
            True,
        ),

        "category_number": (
            incident.get("category_number")
            or incident.get("category_no")
            or incident.get("category_id")
        ),

        "category": incident.get(
            "category"
        ),

        "group": incident.get(
            "group"
        ),

        "incident_number": (
            incident.get("incident_number")
            or incident.get("number")
            or incident.get("code")
        ),

        "incident_type": incident.get(
            "incident_type"
        ),

        "ekp35_type": incident.get(
            "ekp35_type"
        ),

        "main_service": (
            incident.get("main_service")
            or incident.get("service")
        ),
    }



    scenario_id = (
        "SC-"
        + uuid.uuid4().hex[:8].upper()
    )



    questions = _build_questions(
        classification=classification,
        difficulty=difficulty,
    )

    expected_actions = _build_expected_actions(
        classification=classification,
        difficulty=difficulty,
    )

    evaluation_criteria = _build_evaluation_criteria(
        classification=classification,
        difficulty=difficulty,
    )


    if len(questions) != len(expected_actions):
        raise RuntimeError(
            "Ошибка генератора: количество questions "
            "не совпадает с количеством expected_actions"
        )

    if not evaluation_criteria:
        raise RuntimeError(
            "Ошибка генератора: evaluation_criteria пуст"
        )


    service_response = _build_service_response(
        classification
    )


    scenario = {
        "schema_version": "2.1",

        "scenario_id": scenario_id,

        "status": "ready",

        "difficulty": difficulty,

        "title": (
            classification.get("incident_type")
            or "Сценарий System-112"
        ),

        "classification": classification,

        "description": _build_description(
            classification
        ),

        "caller": _build_caller(
            classification
        ),

        "case_facts": _build_case_facts(
            classification=classification,
            difficulty=difficulty,
        ),

        "questions": questions,

        "expected_actions": expected_actions,

        "evaluation_criteria": evaluation_criteria,

        "service_responses": [
            service_response
        ],

        "metadata": {
            "classification_source": "Klassifikator.xlsx",

            "classification_verified": classification.get(
                "verified",
                True,
            ),

            "scenario_type": _detect_scenario_type(
                classification
            ),

            "difficulty": difficulty,

            "questions_count": len(
                questions
            ),

            "expected_actions_count": len(
                expected_actions
            ),

            "criteria_count": len(
                evaluation_criteria
            ),

            "criteria_ids": [
                criterion["id"]
                for criterion in evaluation_criteria
            ],
        },

        "requires_manual_review": False,
    }

    return scenario
